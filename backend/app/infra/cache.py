from __future__ import annotations

import json
from typing import Any

from redis.asyncio import RedisError

from ..config import settings
from ..errors import ExternalServiceError
from ..logging import get_logger
from .redis_client import get_async_redis_client

logger = get_logger("stubgraph.cache")


def _cache_key(parts: list[str]) -> str:
    return "stubgraph:" + ":".join(parts)


async def cache_get_json_async(parts: list[str]) -> dict | list | None:
    if not settings.cache_enabled:
        return None
    key = _cache_key(parts)
    try:
        client = get_async_redis_client()
        data = await client.get(key)
        if not data:
            return None
    except RedisError as exc:
        logger.warning("Cache read failed", extra={"reason": str(exc)})
        raise ExternalServiceError("Не удалось прочитать кэш", context={"key": key}) from exc
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


async def cache_set_json_async(
    parts: list[str], payload: Any, *, ttl_seconds: int | None = None
) -> None:
    if not settings.cache_enabled:
        return
    key = _cache_key(parts)
    ttl = int(ttl_seconds or settings.cache_default_ttl_seconds)
    try:
        client = get_async_redis_client()
        await client.setex(key, ttl, json.dumps(payload, ensure_ascii=False))
    except RedisError as exc:
        logger.warning("Cache write failed", extra={"reason": str(exc)})
        raise ExternalServiceError("Не удалось записать кэш", context={"key": key}) from exc


async def cache_invalidate_prefix_async(parts: list[str]) -> None:
    if not settings.cache_enabled:
        return
    key = _cache_key(parts)
    pattern = f"{key}*"
    deleted_count = 0
    batches = 0
    batch: list[str] = []

    async def _delete_batch(client: Any, keys: list[str]) -> None:
        try:
            await client.unlink(*keys)
            return
        except (AttributeError, NotImplementedError):
            pass
        except RedisError as unlink_exc:
            message = str(unlink_exc).lower()
            if "unlink" not in message or "unknown command" not in message:
                raise

        pipeline = client.pipeline(transaction=False)
        for batch_key in keys:
            pipeline.delete(batch_key)
        await pipeline.execute()

    try:
        client = get_async_redis_client()
        async for match in client.scan_iter(match=pattern):
            batch.append(match)
            if len(batch) >= settings.cache_invalidate_batch_size:
                await _delete_batch(client, batch)
                deleted_count += len(batch)
                batches += 1
                batch.clear()
        if batch:
            await _delete_batch(client, batch)
            deleted_count += len(batch)
            batches += 1
    except RedisError as exc:
        logger.warning("Cache invalidate failed", extra={"reason": str(exc)})
        raise ExternalServiceError(
            "Не удалось инвалидировать кэш",
            context={
                "key": key,
                "pattern": pattern,
                "deleted_count": deleted_count,
                "batches": batches,
            },
        ) from exc
