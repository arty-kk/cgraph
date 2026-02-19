# backend/app/infra/rate_limit.py
from __future__ import annotations

import ipaddress
from functools import lru_cache

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.asyncio import RedisError as AsyncRedisError

from ..config import settings
from ..logging import get_logger
from .redis_client import get_async_redis_client

logger = get_logger("stubgraph.rate_limit")


@lru_cache(maxsize=1)
def _parse_trusted_proxy_networks(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    if not raw:
        return []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw.split(","):
        cidr = entry.strip()
        if not cidr:
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Invalid trusted proxy CIDR ignored", extra={"cidr": cidr})
    return networks


def _client_is_trusted_proxy(client_host: str) -> bool:
    if not client_host:
        return False
    try:
        client_ip = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    raw = (settings.trusted_proxy_cidrs or "").strip()
    for network in _parse_trusted_proxy_networks(raw):
        if client_ip in network:
            return True
    return False


def _client_id(request: Request) -> str:
    client_host = request.client.host if request.client and request.client.host else ""
    if _client_is_trusted_proxy(client_host):
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            try:
                ipaddress.ip_address(forwarded)
                return forwarded
            except ValueError:
                logger.warning(
                    "Invalid X-Forwarded-For IP, falling back to client host",
                    extra={"forwarded": forwarded},
                )
    if client_host:
        return client_host
    return "unknown"


def rate_limit_response() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "rate_limited", "message": "Превышен лимит запросов"}},
    )


async def allow_request_async(request: Request) -> bool:
    if not settings.rate_limit_enabled:
        return True
    limit = int(settings.rate_limit_requests_per_minute)
    key = f"stubgraph:rl:{_client_id(request)}"
    try:
        client = get_async_redis_client()
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 60)
        return count <= limit
    except AsyncRedisError as exc:
        logger.warning("Rate limit check failed", extra={"reason": str(exc)})
        return False
