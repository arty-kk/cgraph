"""Shared runtime for bounded async execution of synchronous Celery producer I/O."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, TypeVar

from ..config import settings

T = TypeVar("T")

_CELERY_PRODUCER_CONCURRENCY = 16

_producer_semaphore: asyncio.Semaphore | None = None
_producer_runtime_lock = asyncio.Lock()


def _producer_concurrency_limit() -> int:
    raw = getattr(
        settings,
        "task_queue_producer_concurrency",
        _CELERY_PRODUCER_CONCURRENCY,
    )
    return max(1, int(raw))


async def init_celery_producer_runtime() -> None:
    global _producer_semaphore
    async with _producer_runtime_lock:
        if _producer_semaphore is not None:
            return
        _producer_semaphore = asyncio.Semaphore(_producer_concurrency_limit())


async def _get_celery_producer_runtime() -> asyncio.Semaphore:
    if _producer_semaphore is None:
        await init_celery_producer_runtime()
    semaphore = _producer_semaphore
    if semaphore is None:
        raise RuntimeError("Celery producer runtime is not initialized")
    return semaphore


async def close_celery_producer_runtime() -> None:
    global _producer_semaphore
    async with _producer_runtime_lock:
        _producer_semaphore = None


async def run_celery_producer_io_async(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    semaphore = await _get_celery_producer_runtime()
    acquired = False
    try:
        await semaphore.acquire()
        acquired = True
        return await asyncio.to_thread(fn, *args, **kwargs)
    finally:
        if acquired:
            semaphore.release()

