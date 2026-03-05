from __future__ import annotations

import json
from typing import Any

from redis.asyncio import RedisError

from ..config import settings
from ..errors import ExternalServiceError
from ..logging import get_logger
from .cpu_runtime import run_cpu_io_async
from .redis_client import get_async_redis_client

logger = get_logger("stubgraph.cache")


def _cache_key(parts: list[str]) -> str:
    return "stubgraph:" + ":".join(parts)


def _serialize_cache_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _serialize_cache_entries(entries: list[Any]) -> list[str]:
    return [_serialize_cache_payload(payload) for payload in entries]


def _deserialize_cache_payload(payload: str | bytes) -> dict | list:
    return json.loads(payload)


def _deserialize_cache_payloads(payloads: list[str | bytes]) -> list[dict | list]:
    return [_deserialize_cache_payload(payload) for payload in payloads]


def _cache_payload_size_bytes(serialized_payload: str) -> int:
    return len(serialized_payload.encode("utf-8"))


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
        return await run_cpu_io_async(
            _deserialize_cache_payload,
            data,
            operation="cache.deserialize_get",
        )
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
        serialized_payload = await run_cpu_io_async(
            _serialize_cache_payload,
            payload,
            operation="cache.serialize_set",
        )
        if _cache_payload_size_bytes(serialized_payload) > settings.cache_entry_max_bytes:
            return
        client = get_async_redis_client()
        await client.setex(key, ttl, serialized_payload)
    except RedisError as exc:
        logger.warning("Cache write failed", extra={"reason": str(exc)})
        raise ExternalServiceError("Не удалось записать кэш", context={"key": key}) from exc


async def cache_mget_json_async(parts_list: list[list[str]]) -> list[dict | list | None]:
    if not parts_list:
        return []
    if not settings.cache_enabled:
        return [None for _ in parts_list]
    keys = [_cache_key(parts) for parts in parts_list]
    try:
        client = get_async_redis_client()
        payloads = await client.mget(keys)
    except RedisError as exc:
        logger.warning("Cache read failed", extra={"reason": str(exc)})
        raise ExternalServiceError("Не удалось прочитать кэш", context={"keys": keys}) from exc

    non_empty_payloads = [payload for payload in payloads if payload]
    decoded_non_empty: list[dict | list]
    if non_empty_payloads:
        try:
            decoded_non_empty = await run_cpu_io_async(
                _deserialize_cache_payloads,
                non_empty_payloads,
                operation="cache.deserialize_mget",
            )
        except json.JSONDecodeError:
            decoded_non_empty = []
    else:
        decoded_non_empty = []

    decoded: list[dict | list | None] = []
    decoded_index = 0
    for payload in payloads:
        if not payload:
            decoded.append(None)
            continue
        if decoded_non_empty and decoded_index < len(decoded_non_empty):
            decoded.append(decoded_non_empty[decoded_index])
            decoded_index += 1
            continue
        try:
            decoded.append(
                await run_cpu_io_async(
                    _deserialize_cache_payload,
                    payload,
                    operation="cache.deserialize_mget_fallback",
                )
            )
        except json.JSONDecodeError:
            decoded.append(None)
    return decoded


async def cache_mset_json_async(
    entries: list[tuple[list[str], Any]],
    *,
    ttl_seconds: int | None = None,
) -> None:
    if not entries or not settings.cache_enabled:
        return

    ttl = int(ttl_seconds or settings.cache_default_ttl_seconds)
    try:
        serialized_payloads = await run_cpu_io_async(
            _serialize_cache_entries,
            [payload for _parts, payload in entries],
            operation="cache.serialize_mset",
        )
        client = get_async_redis_client()
        pipeline = client.pipeline(transaction=False)
        for (parts, _payload), serialized_payload in zip(entries, serialized_payloads):
            if _cache_payload_size_bytes(serialized_payload) > settings.cache_entry_max_bytes:
                continue
            key = _cache_key(parts)
            pipeline.setex(key, ttl, serialized_payload)
        await pipeline.execute()
    except RedisError as exc:
        logger.warning("Cache write failed", extra={"reason": str(exc)})
        raise ExternalServiceError("Не удалось записать кэш", context={"entries": len(entries)}) from exc


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
