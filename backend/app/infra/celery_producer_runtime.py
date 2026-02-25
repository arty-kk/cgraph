"""Shared runtime for bounded async execution of producer transport operations."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, TypeVar

from ..config import settings

T = TypeVar("T")

_CELERY_PRODUCER_MAX_WORKERS = 4
_CELERY_PRODUCER_CONCURRENCY = 16


@dataclass
class CeleryProducerRuntime:
    executor: ThreadPoolExecutor
    semaphore: asyncio.Semaphore
    loop: asyncio.AbstractEventLoop


_producer_runtime: CeleryProducerRuntime | None = None
_producer_runtime_lock = asyncio.Lock()


def _producer_max_workers() -> int:
    raw = getattr(
        settings,
        "task_queue_producer_workers",
        _CELERY_PRODUCER_MAX_WORKERS,
    )
    return max(1, int(raw))


def _producer_concurrency_limit() -> int:
    raw = getattr(
        settings,
        "task_queue_producer_concurrency",
        _CELERY_PRODUCER_CONCURRENCY,
    )
    return max(1, int(raw))


async def init_celery_producer_runtime() -> None:
    global _producer_runtime
    async with _producer_runtime_lock:
        if _producer_runtime is not None:
            return
        loop = asyncio.get_running_loop()
        _producer_runtime = CeleryProducerRuntime(
            executor=ThreadPoolExecutor(
                max_workers=_producer_max_workers(),
                thread_name_prefix="celery-producer-runtime",
            ),
            semaphore=asyncio.Semaphore(_producer_concurrency_limit()),
            loop=loop,
        )


async def _get_celery_producer_runtime() -> CeleryProducerRuntime:
    global _producer_runtime
    if _producer_runtime is None:
        await init_celery_producer_runtime()
    runtime = _producer_runtime
    current_loop = asyncio.get_running_loop()
    if runtime is not None and runtime.loop is current_loop:
        return runtime

    old_runtime: CeleryProducerRuntime | None = None
    async with _producer_runtime_lock:
        runtime = _producer_runtime
        if runtime is not None and runtime.loop is current_loop:
            return runtime

        old_runtime = runtime
        runtime = CeleryProducerRuntime(
            executor=ThreadPoolExecutor(
                max_workers=_producer_max_workers(),
                thread_name_prefix="celery-producer-runtime",
            ),
            semaphore=asyncio.Semaphore(_producer_concurrency_limit()),
            loop=current_loop,
        )
        _producer_runtime = runtime

    if old_runtime is not None:
        await current_loop.run_in_executor(
            None,
            partial(old_runtime.executor.shutdown, wait=True, cancel_futures=True),
        )
    return runtime


async def close_celery_producer_runtime() -> None:
    global _producer_runtime
    async with _producer_runtime_lock:
        runtime = _producer_runtime
        _producer_runtime = None
    if runtime is None:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        partial(runtime.executor.shutdown, wait=True, cancel_futures=True),
    )


async def run_celery_producer_io_async(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    runtime = await _get_celery_producer_runtime()
    async with runtime.semaphore:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(runtime.executor, partial(fn, *args, **kwargs))
