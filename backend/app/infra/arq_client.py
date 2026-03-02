from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from ..config import settings

_arq_pool: ArqRedis | None = None
_arq_pool_lock: asyncio.Lock | None = None
_arq_pool_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_arq_pool_lock() -> asyncio.Lock:
    global _arq_pool_lock, _arq_pool_lock_loop
    loop = asyncio.get_running_loop()
    if _arq_pool_lock is None or _arq_pool_lock_loop is not loop:
        _arq_pool_lock = asyncio.Lock()
        _arq_pool_lock_loop = loop
    return _arq_pool_lock


def _build_redis_settings() -> RedisSettings:
    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or "0"),
        username=parsed.username,
        password=parsed.password,
        ssl=parsed.scheme.endswith("s"),
    )


async def get_arq_pool_async() -> ArqRedis:
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool
    async with _get_arq_pool_lock():
        if _arq_pool is None:
            _arq_pool = await create_pool(_build_redis_settings())
    return _arq_pool


async def close_arq_pool_async() -> None:
    global _arq_pool
    async with _get_arq_pool_lock():
        pool = _arq_pool
        _arq_pool = None
    if pool is not None:
        await pool.aclose()
