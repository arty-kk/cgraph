# backend/app/infra/redis_client.py
from __future__ import annotations

import redis

from ..config import settings


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
