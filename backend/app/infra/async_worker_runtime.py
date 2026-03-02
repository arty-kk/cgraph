from __future__ import annotations

import asyncio

from ..celery_tasks import consume_queued_task_payload_async
from ..services.routing_calibration_service import calibrate_routing_policy_thresholds_async
from ..config import settings
from ..infra.redis_client import get_async_redis_client, init_redis_pool_async
from ..logging import get_logger
from .runtime_lifecycle import build_cleanup_steps, build_startup_steps

logger = get_logger("stubgraph.async_worker_runtime")

_worker_runtime_tasks: set[asyncio.Task[None]] = set()
_worker_runtime_scheduler_task: asyncio.Task[None] | None = None
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
    default_queue = (settings.task_queue_default or "medium").strip() or "medium"
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
        await init_redis_pool_async()
        client = get_async_redis_client()
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




async def _routing_calibration_scheduler_loop_async(*, stop_event: asyncio.Event) -> None:
    interval_seconds = max(1, int(settings.llm_routing_calibration_interval_minutes)) * 60
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            continue
        except asyncio.TimeoutError:
            pass
        try:
            await calibrate_routing_policy_thresholds_async()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Async worker routing calibration tick failed")

async def init_worker_runtime_async() -> None:
    global _worker_runtime_scheduler_task, _worker_runtime_stop
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
        scheduler_task: asyncio.Task[None] | None = None
        if bool(settings.llm_routing_calibration_enabled):
            scheduler_task = asyncio.create_task(
                _routing_calibration_scheduler_loop_async(stop_event=stop_event),
                name="async-worker-routing-calibration-scheduler",
            )
        _worker_runtime_stop = stop_event
        _worker_runtime_scheduler_task = scheduler_task
        _worker_runtime_tasks.clear()
        _worker_runtime_tasks.update(tasks)


async def close_worker_runtime_async() -> None:
    global _worker_runtime_scheduler_task, _worker_runtime_stop
    async with _get_runtime_lock():
        stop_event = _worker_runtime_stop
        scheduler_task = _worker_runtime_scheduler_task
        tasks = tuple(_worker_runtime_tasks)
        _worker_runtime_stop = None
        _worker_runtime_scheduler_task = None
        _worker_runtime_tasks.clear()
    if stop_event is not None:
        stop_event.set()
    to_cancel = list(tasks)
    if scheduler_task is not None:
        to_cancel.append(scheduler_task)
    if to_cancel:
        for task in to_cancel:
            task.cancel()
        await asyncio.gather(*to_cancel, return_exceptions=True)
    await _cleanup_worker_resources_async()
