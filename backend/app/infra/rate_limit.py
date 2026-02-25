# backend/app/infra/rate_limit.py
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from functools import lru_cache

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.asyncio import RedisError as AsyncRedisError
from redis.exceptions import NoScriptError

from ..config import settings
from ..logging import get_logger
from .redis_client import get_async_redis_client

logger = get_logger("stubgraph.rate_limit")

_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_LUA_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
""".strip()
_RATE_LIMIT_LUA_SHA: str | None = None
_RATE_LIMIT_LUA_SHA_LOCK: asyncio.Lock | None = None
_RATE_LIMIT_LUA_SHA_LOCK_LOOP: asyncio.AbstractEventLoop | None = None


def _get_rate_limit_lua_sha_lock() -> asyncio.Lock:
    global _RATE_LIMIT_LUA_SHA_LOCK
    global _RATE_LIMIT_LUA_SHA_LOCK_LOOP

    current_loop = asyncio.get_running_loop()
    if _RATE_LIMIT_LUA_SHA_LOCK is None or _RATE_LIMIT_LUA_SHA_LOCK_LOOP is not current_loop:
        _RATE_LIMIT_LUA_SHA_LOCK = asyncio.Lock()
        _RATE_LIMIT_LUA_SHA_LOCK_LOOP = current_loop
    return _RATE_LIMIT_LUA_SHA_LOCK


async def _get_rate_limit_lua_sha(client) -> str:
    global _RATE_LIMIT_LUA_SHA

    if _RATE_LIMIT_LUA_SHA is not None:
        return _RATE_LIMIT_LUA_SHA

    async with _get_rate_limit_lua_sha_lock():
        if _RATE_LIMIT_LUA_SHA is not None:
            return _RATE_LIMIT_LUA_SHA
        sha = await client.script_load(_RATE_LIMIT_LUA_SCRIPT)
        _RATE_LIMIT_LUA_SHA = sha
        return sha


async def _run_rate_limit_increment(client, key: str) -> int:
    global _RATE_LIMIT_LUA_SHA

    sha = await _get_rate_limit_lua_sha(client)
    try:
        return int(await client.evalsha(sha, 1, key, _RATE_LIMIT_WINDOW_SECONDS))
    except NoScriptError:
        count = int(await client.eval(_RATE_LIMIT_LUA_SCRIPT, 1, key, _RATE_LIMIT_WINDOW_SECONDS))
        script_sha = hashlib.sha1(_RATE_LIMIT_LUA_SCRIPT.encode("utf-8")).hexdigest()
        async with _get_rate_limit_lua_sha_lock():
            _RATE_LIMIT_LUA_SHA = script_sha
        return count


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
        count = await _run_rate_limit_increment(client, key)
        return count <= limit
    except AsyncRedisError as exc:
        # Fail-safe policy: when Redis is unavailable, block request to avoid limit bypass.
        logger.warning("Rate limit check failed", extra={"reason": str(exc)})
        return False
