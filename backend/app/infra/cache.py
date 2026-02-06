# backend/app/infra/cache.py
from __future__ import annotations

import json
from typing import Any

from redis import RedisError

from ..config import settings
from ..logging import get_logger
from .redis_client import get_redis_client

logger = get_logger("stubgraph.cache")


def _cache_key(parts: list[str]) -> str:
    return "stubgraph:" + ":".join(parts)


def cache_get_json(parts: list[str]) -> dict | list | None:
    if not settings.cache_enabled:
        return None
    key = _cache_key(parts)
    try:
        client = get_redis_client()
        data = client.get(key)
        if not data:
            return None
    except RedisError as exc:
        logger.warning("Cache read failed", extra={"reason": str(exc)})
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def cache_set_json(parts: list[str], payload: Any, *, ttl_seconds: int | None = None) -> None:
    if not settings.cache_enabled:
        return
    key = _cache_key(parts)
    ttl = int(ttl_seconds or settings.cache_default_ttl_seconds)
    try:
        client = get_redis_client()
        client.setex(key, ttl, json.dumps(payload, ensure_ascii=False))
    except RedisError as exc:
        logger.warning("Cache write failed", extra={"reason": str(exc)})


def cache_invalidate_prefix(parts: list[str]) -> None:
    if not settings.cache_enabled:
        return
    key = _cache_key(parts)
    try:
        client = get_redis_client()
        for match in client.scan_iter(match=f"{key}*"):
            client.delete(match)
    except RedisError as exc:
        logger.warning("Cache invalidate failed", extra={"reason": str(exc)})
