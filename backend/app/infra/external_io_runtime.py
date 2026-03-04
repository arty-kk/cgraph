"""Shared runtime for bounded async execution of external OpenAI I/O."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import Any, Awaitable, Callable, Literal, TypeVar

from ..config import settings

T = TypeVar("T")
OpenAIIOKind = Literal["short", "long"]

_OPENAI_IO_SHORT_CONCURRENCY = 16
_OPENAI_IO_LONG_CONCURRENCY = 4
_STORAGE_SDK_IO_CONCURRENCY = 8


@dataclass
class ExternalIORuntime:
    short_semaphore: asyncio.Semaphore
    long_semaphore: asyncio.Semaphore
    storage_sdk_semaphore: asyncio.Semaphore
    storage_sdk_executor: ThreadPoolExecutor
    loop: asyncio.AbstractEventLoop
    short_limit: int
    long_limit: int
    storage_sdk_limit: int


_external_io_runtime: ExternalIORuntime | None = None
_external_io_runtime_lock: asyncio.Lock | None = None
_external_io_runtime_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_external_io_runtime_lock() -> asyncio.Lock:
    global _external_io_runtime_lock, _external_io_runtime_lock_loop
    loop = asyncio.get_running_loop()
    if _external_io_runtime_lock is None or _external_io_runtime_lock_loop is not loop:
        _external_io_runtime_lock = asyncio.Lock()
        _external_io_runtime_lock_loop = loop
    return _external_io_runtime_lock


def _openai_short_limit() -> int:
    raw = getattr(settings, "openai_io_short_concurrency", _OPENAI_IO_SHORT_CONCURRENCY)
    return max(1, int(raw))


def _openai_long_limit() -> int:
    raw = getattr(settings, "openai_io_long_concurrency", _OPENAI_IO_LONG_CONCURRENCY)
    return max(1, int(raw))


def _storage_sdk_limit() -> int:
    raw = getattr(settings, "storage_sdk_io_concurrency", _STORAGE_SDK_IO_CONCURRENCY)
    return max(1, int(raw))


async def init_external_io_runtime() -> None:
    global _external_io_runtime
    async with _get_external_io_runtime_lock():
        if _external_io_runtime is not None:
            return
        loop = asyncio.get_running_loop()
        short_limit = _openai_short_limit()
        long_limit = _openai_long_limit()
        storage_sdk_limit = _storage_sdk_limit()
        _external_io_runtime = ExternalIORuntime(
            short_semaphore=asyncio.Semaphore(short_limit),
            long_semaphore=asyncio.Semaphore(long_limit),
            storage_sdk_semaphore=asyncio.Semaphore(storage_sdk_limit),
            storage_sdk_executor=ThreadPoolExecutor(
                max_workers=storage_sdk_limit,
                thread_name_prefix="storage-sdk-io",
            ),
            loop=loop,
            short_limit=short_limit,
            long_limit=long_limit,
            storage_sdk_limit=storage_sdk_limit,
        )


async def _get_external_io_runtime() -> ExternalIORuntime:
    global _external_io_runtime
    if _external_io_runtime is None:
        await init_external_io_runtime()
    runtime = _external_io_runtime
    current_loop = asyncio.get_running_loop()
    if runtime is not None and runtime.loop is current_loop:
        return runtime

    old_runtime: ExternalIORuntime | None = None
    async with _get_external_io_runtime_lock():
        runtime = _external_io_runtime
        if runtime is not None and runtime.loop is current_loop:
            return runtime
        old_runtime = runtime
        short_limit = _openai_short_limit()
        long_limit = _openai_long_limit()
        storage_sdk_limit = _storage_sdk_limit()
        runtime = ExternalIORuntime(
            short_semaphore=asyncio.Semaphore(short_limit),
            long_semaphore=asyncio.Semaphore(long_limit),
            storage_sdk_semaphore=asyncio.Semaphore(storage_sdk_limit),
            storage_sdk_executor=ThreadPoolExecutor(
                max_workers=storage_sdk_limit,
                thread_name_prefix="storage-sdk-io",
            ),
            loop=current_loop,
            short_limit=short_limit,
            long_limit=long_limit,
            storage_sdk_limit=storage_sdk_limit,
        )
        _external_io_runtime = runtime

    if old_runtime is not None:
        await current_loop.run_in_executor(
            None,
            partial(old_runtime.storage_sdk_executor.shutdown, wait=True, cancel_futures=False),
        )

    if runtime is None:
        raise RuntimeError("External I/O runtime is not initialized")
    return runtime


async def close_external_io_runtime() -> None:
    global _external_io_runtime
    runtime: ExternalIORuntime | None
    async with _get_external_io_runtime_lock():
        runtime = _external_io_runtime
        _external_io_runtime = None
    if runtime is None:
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        partial(runtime.storage_sdk_executor.shutdown, wait=True, cancel_futures=False),
    )


async def run_openai_io_async(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    kind: OpenAIIOKind,
) -> T:
    runtime = await _get_external_io_runtime()
    if kind == "short":
        semaphore = runtime.short_semaphore
    elif kind == "long":
        semaphore = runtime.long_semaphore
    else:
        raise ValueError("kind must be either 'short' or 'long'")

    acquired = False
    try:
        await semaphore.acquire()
        acquired = True
        return await coro_factory()
    finally:
        if acquired:
            semaphore.release()


async def run_storage_sdk_io_async(
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    runtime = await _get_external_io_runtime()
    acquired = False
    try:
        await runtime.storage_sdk_semaphore.acquire()
        acquired = True
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            runtime.storage_sdk_executor,
            partial(fn, *args, **kwargs),
        )
    finally:
        if acquired:
            runtime.storage_sdk_semaphore.release()
