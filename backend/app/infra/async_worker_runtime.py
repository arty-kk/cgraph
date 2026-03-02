from __future__ import annotations

import asyncio

from ..celery_tasks import consume_queued_task_payload_async
from ..config import settings
from ..logging import get_logger
from ..services.task_queue import get_task_transport_redis_client_async
from .runtime_lifecycle import build_cleanup_steps, build_startup_steps

logger = get_logger("stubgraph.async_worker_runtime")

_worker_runtime_tasks: set[asyncio.Task[None]] = set()
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


def _build_worker_queues() -> list[str]:
    default_queue = (settings.celery_queue_default or "medium").strip() or "medium"
    queues = ["light", "medium", "heavy"]
    if default_queue not in queues:
        queues.append(default_queue)
    return queues


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


async def _consume_once_safe_async(*, queues: list[str], timeout_seconds: int = 1) -> bool:
    try:
        client = await get_task_transport_redis_client_async()
        item = await client.brpop(queues, timeout=timeout_seconds)
        if item is None:
            return False
        _, payload_raw = item
        await consume_queued_task_payload_async(payload_raw)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Async worker consumer failed")
        return False


async def _consumer_loop_async(*, stop_event: asyncio.Event, queues: list[str]) -> None:
    while not stop_event.is_set():
        consumed = await _consume_once_safe_async(queues=queues, timeout_seconds=1)
        if not consumed:
            await asyncio.sleep(0.05)


async def init_worker_runtime_async() -> None:
    global _worker_runtime_stop
    async with _get_runtime_lock():
        if _worker_runtime_tasks:
            return
        await _startup_worker_resources_async()
        stop_event = asyncio.Event()
        queues = _build_worker_queues()
        tasks = {
            asyncio.create_task(
                _consumer_loop_async(stop_event=stop_event, queues=queues),
                name=f"async-worker-consumer-loop-{idx}",
            )
            for idx in range(settings.worker_runtime_concurrency)
        }
        _worker_runtime_stop = stop_event
        _worker_runtime_tasks.clear()
        _worker_runtime_tasks.update(tasks)


async def close_worker_runtime_async() -> None:
    global _worker_runtime_stop
    async with _get_runtime_lock():
        stop_event = _worker_runtime_stop
        tasks = tuple(_worker_runtime_tasks)
        _worker_runtime_stop = None
        _worker_runtime_tasks.clear()
    if stop_event is not None:
        stop_event.set()
    if tasks:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    await _cleanup_worker_resources_async()
