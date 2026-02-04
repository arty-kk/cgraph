#backend/app/infra/rate_limit.py
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from redis import RedisError

from ..config import settings
from ..logging import get_logger
from .redis_client import get_redis_client

logger = get_logger("stubgraph.rate_limit")


def _client_id(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_response() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "rate_limited", "message": "Превышен лимит запросов"}},
    )


def allow_request(request: Request) -> bool:
    if not settings.rate_limit_enabled:
        return True
    limit = int(settings.rate_limit_requests_per_minute)
    key = f"stubgraph:rl:{_client_id(request)}"
    try:
        client = get_redis_client()
        count = client.incr(key)
        if count == 1:
            client.expire(key, 60)
        return count <= limit
    except RedisError as exc:
        logger.warning("Rate limit check failed", extra={"reason": str(exc)})
        return True
