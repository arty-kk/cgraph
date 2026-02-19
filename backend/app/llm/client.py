# backend/app/llm/client.py
from __future__ import annotations

import inspect

from openai import AsyncOpenAI

from ..config import settings

_async_client: AsyncOpenAI | None = None


def get_async_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY не задан. Экспортируй переменную окружения OPENAI_API_KEY."
        )

    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

    return _async_client


async def close_async_openai_client() -> None:
    global _async_client
    client = _async_client
    if client is None:
        return
    try:
        for method_name in ("aclose", "close"):
            method = getattr(client, method_name, None)
            if method is None:
                continue
            result = method()
            if inspect.isawaitable(result):
                await result
            break
    finally:
        _async_client = None
