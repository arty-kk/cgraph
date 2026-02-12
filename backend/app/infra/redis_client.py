# backend/app/infra/redis_client.py
from __future__ import annotations

import redis
import redis.asyncio as redis_async
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ..config import settings


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


@asynccontextmanager
async def async_redis_client() -> AsyncIterator[redis_async.Redis]:
    client = redis_async.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
