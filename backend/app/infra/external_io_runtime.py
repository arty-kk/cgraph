"""Shared runtime for bounded async execution of external OpenAI I/O."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, TypeVar

from ..config import settings

T = TypeVar("T")
OpenAIIOKind = Literal["short", "long"]

_OPENAI_IO_SHORT_CONCURRENCY = 16
_OPENAI_IO_LONG_CONCURRENCY = 4


@dataclass
class ExternalIORuntime:
    short_semaphore: asyncio.Semaphore
    long_semaphore: asyncio.Semaphore
    short_limit: int
    long_limit: int


_external_io_runtime: ExternalIORuntime | None = None
_external_io_runtime_lock = asyncio.Lock()


def _openai_short_limit() -> int:
    raw = getattr(settings, "openai_io_short_concurrency", _OPENAI_IO_SHORT_CONCURRENCY)
    return max(1, int(raw))


def _openai_long_limit() -> int:
    raw = getattr(settings, "openai_io_long_concurrency", _OPENAI_IO_LONG_CONCURRENCY)
    return max(1, int(raw))


async def init_external_io_runtime() -> None:
    global _external_io_runtime
    async with _external_io_runtime_lock:
        if _external_io_runtime is not None:
            return
        short_limit = _openai_short_limit()
        long_limit = _openai_long_limit()
        _external_io_runtime = ExternalIORuntime(
            short_semaphore=asyncio.Semaphore(short_limit),
            long_semaphore=asyncio.Semaphore(long_limit),
            short_limit=short_limit,
            long_limit=long_limit,
        )


async def _get_external_io_runtime() -> ExternalIORuntime:
    if _external_io_runtime is None:
        await init_external_io_runtime()
    runtime = _external_io_runtime
    if runtime is None:
        raise RuntimeError("External I/O runtime is not initialized")
    return runtime


async def close_external_io_runtime() -> None:
    global _external_io_runtime
    async with _external_io_runtime_lock:
        _external_io_runtime = None


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
