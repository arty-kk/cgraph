# backend/app/infra/redis_client.py
from __future__ import annotations

from contextlib import contextmanager
from threading import Lock

import redis
import redis.asyncio as redis_async

from ..config import settings


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


@contextmanager
def sync_redis_client() -> redis.Redis:
    client = get_redis_client()
    try:
        yield client
    finally:
        client.close()


_async_redis_client_singleton: redis_async.Redis | None = None
_async_redis_client_lock = Lock()


async def init_redis_pool_async() -> redis_async.Redis:
    global _async_redis_client_singleton
    if _async_redis_client_singleton is not None:
        return _async_redis_client_singleton
    with _async_redis_client_lock:
        if _async_redis_client_singleton is None:
            _async_redis_client_singleton = redis_async.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
    return _async_redis_client_singleton


def get_async_redis_client() -> redis_async.Redis:
    if _async_redis_client_singleton is None:
        raise RuntimeError("Async Redis client is not initialized")
    return _async_redis_client_singleton


async def close_redis_pool_async() -> None:
    global _async_redis_client_singleton
    client = _async_redis_client_singleton
    _async_redis_client_singleton = None
    if client is not None:
        await client.aclose()
