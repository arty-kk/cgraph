from __future__ import annotations

import asyncio

from ..celery_tasks import consume_worker_queue_once_async
from ..config import settings
from ..logging import get_logger
from .runtime_lifecycle import build_cleanup_steps, build_startup_steps

logger = get_logger("stubgraph.async_worker_runtime")

_worker_runtime_task: asyncio.Task[None] | None = None
_worker_runtime_stop: asyncio.Event | None = None
_worker_runtime_lock: asyncio.Lock | None = None
_worker_runtime_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_runtime_lock() -> asyncio.Lock:
    global _worker_runtime_lock, _worker_runtime_lock_loop
    loop = asyncio.get_running_loop()
    if _worker_runtime_lock is None or _worker_runtime_lock_loop is not loop:
        _worker_runtime_lock = asyncio.Lock()
        _worker_runtime_lock_loop = loop
    return _worker_runtime_lock


async def _startup_worker_resources_async() -> None:
    for name, startup in build_startup_steps(role="worker_core"):
        await startup()
        logger.info("Async worker startup step completed", extra={"step": name})


async def _cleanup_worker_resources_async() -> None:
    for name, cleanup in build_cleanup_steps(role="worker_core"):
        try:
            await cleanup()
        except Exception:  # noqa: BLE001
            logger.exception("Async worker cleanup failed", extra={"step": name})


async def _consumer_loop_async(stop_event: asyncio.Event) -> None:
    default_queue = (settings.celery_queue_default or "medium").strip() or "medium"
    queues = ["light", "medium", "heavy"]
    if default_queue not in queues:
        queues.append(default_queue)
    while not stop_event.is_set():
        consumed = False
        for queue in queues:
            consumed = await consume_worker_queue_once_async(queue=queue, timeout_seconds=1)
            if consumed or stop_event.is_set():
                break
        if not consumed:
            await asyncio.sleep(0.05)


async def init_worker_runtime_async() -> None:
    global _worker_runtime_task, _worker_runtime_stop
    async with _get_runtime_lock():
        if _worker_runtime_task is not None:
            return
        await _startup_worker_resources_async()
        stop_event = asyncio.Event()
        _worker_runtime_stop = stop_event
        _worker_runtime_task = asyncio.create_task(
            _consumer_loop_async(stop_event), name="async-worker-consumer-loop"
        )


async def close_worker_runtime_async() -> None:
    global _worker_runtime_task, _worker_runtime_stop
    async with _get_runtime_lock():
        task = _worker_runtime_task
        stop_event = _worker_runtime_stop
        _worker_runtime_task = None
        _worker_runtime_stop = None
    if stop_event is not None:
        stop_event.set()
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await _cleanup_worker_resources_async()
