"""Shared runtime for bounded async execution of synchronous FS/context-bound operations.

FS runtime contract:
- accepts Path/descriptor and other thread-affine/non-pickle-safe context;
- use this runtime for direct filesystem/object-handle operations.

CPU-pure and pickle-safe workloads must use CPU process runtime.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from threading import Lock
from typing import Any, Callable, Literal

from ..config import settings
from ..logging import get_logger

logger = get_logger("stubgraph.fs_runtime")

FsRuntimeLaneName = Literal["interactive", "bulk"]

_FS_RUNTIME_INTERACTIVE_MAX_WORKERS = 8
_FS_RUNTIME_INTERACTIVE_MAX_CONCURRENCY = 32
_FS_RUNTIME_BULK_MAX_WORKERS = 8
_FS_RUNTIME_BULK_MAX_CONCURRENCY = 32
_FS_RUNTIME_SLOW_TASK_MS = 750.0
_FS_RUNTIME_SLOW_WAIT_MS = 200.0


@dataclass
class FsRuntimeLane:
    executor: ThreadPoolExecutor
    semaphore: asyncio.Semaphore
    max_concurrency: int
    lock: Lock
    queue_depth: int = 0
    peak_queue_depth: int = 0
    in_flight: int = 0
    peak_in_flight: int = 0


@dataclass
class FsRuntime:
    loop: asyncio.AbstractEventLoop
    interactive: FsRuntimeLane
    bulk: FsRuntimeLane


_fs_runtime: FsRuntime | None = None
_fs_runtime_lock: asyncio.Lock | None = None
_fs_runtime_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_fs_runtime_lock() -> asyncio.Lock:
    global _fs_runtime_lock, _fs_runtime_lock_loop
    loop = asyncio.get_running_loop()
    if _fs_runtime_lock is None or _fs_runtime_lock_loop is not loop:
        _fs_runtime_lock = asyncio.Lock()
        _fs_runtime_lock_loop = loop
    return _fs_runtime_lock


def _fs_interactive_max_workers() -> int:
    return max(1, int(settings.fs_runtime_interactive_max_workers or _FS_RUNTIME_INTERACTIVE_MAX_WORKERS))


def _fs_interactive_max_concurrency() -> int:
    return max(
        1,
        int(
            settings.fs_runtime_interactive_max_concurrency
            or _FS_RUNTIME_INTERACTIVE_MAX_CONCURRENCY
        ),
    )


def _fs_bulk_max_workers() -> int:
    return max(1, int(settings.fs_runtime_bulk_max_workers or _FS_RUNTIME_BULK_MAX_WORKERS))


def _fs_bulk_max_concurrency() -> int:
    return max(1, int(settings.fs_runtime_bulk_max_concurrency or _FS_RUNTIME_BULK_MAX_CONCURRENCY))


def _build_lane(name: FsRuntimeLaneName) -> FsRuntimeLane:
    if name == "interactive":
        max_workers = _fs_interactive_max_workers()
        max_concurrency = _fs_interactive_max_concurrency()
    else:
        max_workers = _fs_bulk_max_workers()
        max_concurrency = _fs_bulk_max_concurrency()
    return FsRuntimeLane(
        executor=ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"fs-runtime-{name}"),
        semaphore=asyncio.Semaphore(max_concurrency),
        max_concurrency=max_concurrency,
        lock=Lock(),
    )


def _build_runtime(loop: asyncio.AbstractEventLoop) -> FsRuntime:
    return FsRuntime(
        loop=loop,
        interactive=_build_lane("interactive"),
        bulk=_build_lane("bulk"),
    )


def _get_lane_state(runtime: FsRuntime, lane: FsRuntimeLaneName) -> FsRuntimeLane:
    if lane == "interactive":
        return runtime.interactive
    if lane == "bulk":
        return runtime.bulk
    raise ValueError(f"Unsupported fs runtime lane: {lane}")


async def _shutdown_runtime(runtime: FsRuntime, loop: asyncio.AbstractEventLoop) -> None:
    await loop.run_in_executor(
        None,
        partial(runtime.interactive.executor.shutdown, wait=True, cancel_futures=True),
    )
    await loop.run_in_executor(
        None,
        partial(runtime.bulk.executor.shutdown, wait=True, cancel_futures=True),
    )


async def init_fs_runtime() -> None:
    global _fs_runtime
    async with _get_fs_runtime_lock():
        if _fs_runtime is not None:
            return
        _fs_runtime = _build_runtime(asyncio.get_running_loop())


async def _get_fs_runtime() -> FsRuntime:
    global _fs_runtime
    if _fs_runtime is None:
        await init_fs_runtime()
    runtime = _fs_runtime
    current_loop = asyncio.get_running_loop()
    if runtime is not None and runtime.loop is current_loop:
        return runtime

    old_runtime: FsRuntime | None = None
    async with _get_fs_runtime_lock():
        runtime = _fs_runtime
        if runtime is not None and runtime.loop is current_loop:
            return runtime
        old_runtime = runtime
        runtime = _build_runtime(current_loop)
        _fs_runtime = runtime

    if old_runtime is not None:
        await _shutdown_runtime(old_runtime, current_loop)
    return runtime


async def close_fs_runtime() -> None:
    global _fs_runtime
    async with _get_fs_runtime_lock():
        runtime = _fs_runtime
        _fs_runtime = None
    if runtime is None:
        return
    await _shutdown_runtime(runtime, asyncio.get_running_loop())


async def run_fs_io_async(
    fn: Callable[..., Any],
    *args: Any,
    operation: str | None = None,
    lane: FsRuntimeLaneName = "interactive",
    **kwargs: Any,
) -> Any:
    runtime = await _get_fs_runtime()
    lane_state = _get_lane_state(runtime, lane)
    operation_name = operation or getattr(fn, "__name__", "fs_io")

    with lane_state.lock:
        lane_state.queue_depth += 1
        lane_state.peak_queue_depth = max(lane_state.peak_queue_depth, lane_state.queue_depth)
        queued_now = lane_state.queue_depth
        peak_queue = lane_state.peak_queue_depth

    queued_at = time.perf_counter()
    acquired = False
    try:
        await lane_state.semaphore.acquire()
        acquired = True

        wait_ms = (time.perf_counter() - queued_at) * 1000.0
        with lane_state.lock:
            lane_state.queue_depth = max(0, lane_state.queue_depth - 1)
            lane_state.in_flight += 1
            lane_state.peak_in_flight = max(lane_state.peak_in_flight, lane_state.in_flight)
            in_flight_now = lane_state.in_flight
            peak_in_flight = lane_state.peak_in_flight
            queue_depth_now = lane_state.queue_depth

        started_at = time.perf_counter()
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(lane_state.executor, partial(fn, *args, **kwargs))
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            with lane_state.lock:
                lane_state.in_flight = max(0, lane_state.in_flight - 1)
                in_flight_after = lane_state.in_flight

            if wait_ms >= _FS_RUNTIME_SLOW_WAIT_MS or elapsed_ms >= _FS_RUNTIME_SLOW_TASK_MS:
                logger.warning(
                    "FS runtime backpressure detected",
                    extra={
                        "lane": lane,
                        "operation": operation_name,
                        "wait_ms": round(wait_ms, 3),
                        "queue_depth_enqueued": queued_now,
                        "elapsed_ms": round(elapsed_ms, 3),
                        "queue_depth": queue_depth_now,
                        "peak_queue_depth": peak_queue,
                        "in_flight": in_flight_now,
                        "in_flight_after": in_flight_after,
                        "peak_in_flight": peak_in_flight,
                        "max_concurrency": lane_state.max_concurrency,
                    },
                )

        return result
    finally:
        if not acquired:
            with lane_state.lock:
                lane_state.queue_depth = max(0, lane_state.queue_depth - 1)
        if acquired:
            lane_state.semaphore.release()
