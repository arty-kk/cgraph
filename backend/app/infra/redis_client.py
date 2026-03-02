# backend/app/infra/redis_client.py
from __future__ import annotations

import asyncio

import redis.asyncio as redis_async

from ..config import settings

_async_redis_client_singleton: redis_async.Redis | None = None
_async_redis_client_lock: asyncio.Lock | None = None
_async_redis_client_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_async_redis_client_lock() -> asyncio.Lock:
    global _async_redis_client_lock, _async_redis_client_lock_loop
    loop = asyncio.get_running_loop()
    if _async_redis_client_lock is None or _async_redis_client_lock_loop is not loop:
        _async_redis_client_lock = asyncio.Lock()
        _async_redis_client_lock_loop = loop
    return _async_redis_client_lock


async def init_redis_pool_async() -> redis_async.Redis:
    global _async_redis_client_singleton
    if _async_redis_client_singleton is not None:
        return _async_redis_client_singleton
    async with _get_async_redis_client_lock():
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
    async with _get_async_redis_client_lock():
        client = _async_redis_client_singleton
        _async_redis_client_singleton = None
    if client is not None:
        await client.aclose()
