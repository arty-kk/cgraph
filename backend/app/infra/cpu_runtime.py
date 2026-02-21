"""Shared runtime for bounded async execution of synchronous CPU-oriented operations."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from threading import Lock
from typing import Any, Callable

from ..config import settings
from ..logging import get_logger

logger = get_logger("stubgraph.cpu_runtime")

_CPU_RUNTIME_MAX_WORKERS = 8
_CPU_RUNTIME_MAX_CONCURRENCY = 16
_CPU_RUNTIME_SLOW_TASK_MS = 750.0
_CPU_RUNTIME_SLOW_WAIT_MS = 200.0


@dataclass
class CpuRuntime:
    executor: ThreadPoolExecutor
    semaphore: asyncio.Semaphore
    loop: asyncio.AbstractEventLoop
    max_concurrency: int
    lock: Lock
    queue_depth: int = 0
    peak_queue_depth: int = 0
    in_flight: int = 0
    peak_in_flight: int = 0


_cpu_runtime: CpuRuntime | None = None
_cpu_runtime_lock = asyncio.Lock()


def _cpu_max_workers() -> int:
    raw = getattr(settings, "cpu_runtime_max_workers", _CPU_RUNTIME_MAX_WORKERS)
    return max(1, int(raw))


def _cpu_max_concurrency() -> int:
    raw = getattr(settings, "cpu_runtime_max_concurrency", _CPU_RUNTIME_MAX_CONCURRENCY)
    return max(1, int(raw))


def _cpu_slow_wait_ms() -> float:
    raw = getattr(settings, "cpu_runtime_slow_wait_ms", _CPU_RUNTIME_SLOW_WAIT_MS)
    return max(0.0, float(raw))


def _cpu_slow_task_ms() -> float:
    raw = getattr(settings, "cpu_runtime_slow_task_ms", _CPU_RUNTIME_SLOW_TASK_MS)
    return max(0.0, float(raw))


async def init_cpu_runtime() -> None:
    global _cpu_runtime
    async with _cpu_runtime_lock:
        if _cpu_runtime is not None:
            return
        loop = asyncio.get_running_loop()
        max_workers = _cpu_max_workers()
        max_concurrency = _cpu_max_concurrency()
        _cpu_runtime = CpuRuntime(
            executor=ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cpu-runtime"),
            semaphore=asyncio.Semaphore(max_concurrency),
            loop=loop,
            max_concurrency=max_concurrency,
            lock=Lock(),
        )


async def _get_cpu_runtime() -> CpuRuntime:
    global _cpu_runtime
    if _cpu_runtime is None:
        await init_cpu_runtime()
    runtime = _cpu_runtime
    current_loop = asyncio.get_running_loop()
    if runtime is not None and runtime.loop is current_loop:
        return runtime

    old_runtime: CpuRuntime | None = None
    async with _cpu_runtime_lock:
        runtime = _cpu_runtime
        if runtime is not None and runtime.loop is current_loop:
            return runtime
        old_runtime = runtime
        max_workers = _cpu_max_workers()
        max_concurrency = _cpu_max_concurrency()
        runtime = CpuRuntime(
            executor=ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cpu-runtime"),
            semaphore=asyncio.Semaphore(max_concurrency),
            loop=current_loop,
            max_concurrency=max_concurrency,
            lock=Lock(),
        )
        _cpu_runtime = runtime

    if old_runtime is not None:
        await current_loop.run_in_executor(
            None,
            partial(old_runtime.executor.shutdown, wait=True, cancel_futures=True),
        )
    return runtime


async def close_cpu_runtime() -> None:
    global _cpu_runtime
    async with _cpu_runtime_lock:
        runtime = _cpu_runtime
        _cpu_runtime = None
    if runtime is None:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, partial(runtime.executor.shutdown, wait=True, cancel_futures=True))


async def run_cpu_io_async(
    fn: Callable[..., Any],
    *args: Any,
    operation: str | None = None,
    **kwargs: Any,
) -> Any:
    runtime = await _get_cpu_runtime()
    operation_name = operation or getattr(fn, "__name__", "cpu_io")

    with runtime.lock:
        runtime.queue_depth += 1
        runtime.peak_queue_depth = max(runtime.peak_queue_depth, runtime.queue_depth)
        queued_now = runtime.queue_depth

    queued_at = time.perf_counter()
    acquired = False
    try:
        await runtime.semaphore.acquire()
        acquired = True

        wait_ms = (time.perf_counter() - queued_at) * 1000.0
        with runtime.lock:
            runtime.queue_depth = max(0, runtime.queue_depth - 1)
            runtime.in_flight += 1
            runtime.peak_in_flight = max(runtime.peak_in_flight, runtime.in_flight)
            in_flight_now = runtime.in_flight
            queue_depth_now = runtime.queue_depth

        started_at = time.perf_counter()
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(runtime.executor, partial(fn, *args, **kwargs))
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            with runtime.lock:
                runtime.in_flight = max(0, runtime.in_flight - 1)
                in_flight_after = runtime.in_flight

            if wait_ms >= _cpu_slow_wait_ms() or elapsed_ms >= _cpu_slow_task_ms():
                logger.warning(
                    "CPU runtime backpressure detected",
                    extra={
                        "operation": operation_name,
                        "wait_ms": round(wait_ms, 3),
                        "elapsed_ms": round(elapsed_ms, 3),
                        "queue_depth": queue_depth_now,
                        "in_flight": in_flight_now,
                        "in_flight_after": in_flight_after,
                        "max_concurrency": runtime.max_concurrency,
                    },
                )

        return result
    finally:
        if not acquired:
            with runtime.lock:
                runtime.queue_depth = max(0, runtime.queue_depth - 1)
        if acquired:
            runtime.semaphore.release()
