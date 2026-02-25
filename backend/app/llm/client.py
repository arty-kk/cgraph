# backend/app/llm/client.py
from __future__ import annotations

import asyncio
import inspect

from openai import AsyncOpenAI

from ..config import settings

_async_client: AsyncOpenAI | None = None
_client_lock: asyncio.Lock | None = None
_client_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_client_lock() -> asyncio.Lock:
    global _client_lock, _client_lock_loop
    loop = asyncio.get_running_loop()
    if _client_lock is None or _client_lock_loop is not loop:
        _client_lock = asyncio.Lock()
        _client_lock_loop = loop
    return _client_lock


async def init_async_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY не задан. Экспортируй переменную окружения OPENAI_API_KEY."
        )

    global _async_client
    async with _get_client_lock():
        if _async_client is None:
            _async_client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.openai_timeout_seconds,
                max_retries=settings.openai_max_retries,
            )
        return _async_client


def get_async_openai_client() -> AsyncOpenAI:
    if _async_client is None:
        raise RuntimeError(
            "AsyncOpenAI клиент не инициализирован. "
            "Вызови await init_async_openai_client() в runtime startup."
        )
    return _async_client


async def close_async_openai_client() -> None:
    global _async_client
    async with _get_client_lock():
        client = _async_client
        _async_client = None

    if client is None:
        return

    for method_name in ("aclose", "close"):
        method = getattr(client, method_name, None)
        if method is None:
            continue
        result = method()
        if inspect.isawaitable(result):
            await result
        break
