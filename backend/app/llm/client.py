# backend/app/llm/client.py
from __future__ import annotations

from openai import AsyncOpenAI, OpenAI

from ..config import settings

_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


def get_openai_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY не задан. Экспортируй переменную окружения OPENAI_API_KEY."
        )

    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

    return _client


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
