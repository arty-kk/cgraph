import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from redis.exceptions import NoScriptError

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import rate_limit


class _FakeRedisClient:
    def __init__(self):
        self.script_load_calls = 0
        self.evalsha_calls: list[tuple[str, int, str, int]] = []
        self.eval_calls: list[tuple[str, int, str, int]] = []

    async def script_load(self, script: str) -> str:
        self.script_load_calls += 1
        return "script-sha-1"

    async def evalsha(self, sha: str, numkeys: int, key: str, ttl: int) -> int:
        self.evalsha_calls.append((sha, numkeys, key, ttl))
        return len(self.evalsha_calls)

    async def eval(self, script: str, numkeys: int, key: str, ttl: int) -> int:
        self.eval_calls.append((script, numkeys, key, ttl))
        return 1


class _FakeRedisClientNoScript(_FakeRedisClient):
    async def evalsha(self, sha: str, numkeys: int, key: str, ttl: int) -> int:
        self.evalsha_calls.append((sha, numkeys, key, ttl))
        raise NoScriptError("NOSCRIPT No matching script. Please use EVAL.")


@pytest.mark.anyio
async def test_allow_request_async_uses_evalsha_concurrently_with_single_sha_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeRedisClient()
    get_client_calls = 0

    def _get_client():
        nonlocal get_client_calls
        get_client_calls += 1
        return client

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit.settings, "rate_limit_requests_per_minute", 10)
    monkeypatch.setattr(rate_limit, "get_async_redis_client", _get_client)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA", None)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA_LOCK", None)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA_LOCK_LOOP", None)

    await asyncio.gather(
        rate_limit.allow_request_async(request),
        rate_limit.allow_request_async(request),
    )

    assert get_client_calls == 2
    assert client.script_load_calls == 1
    assert len(client.evalsha_calls) == 2
    assert len(client.eval_calls) == 0
    assert all(call[-1] == 60 for call in client.evalsha_calls)


@pytest.mark.anyio
async def test_allow_request_async_falls_back_to_eval_on_noscript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeRedisClientNoScript()

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit.settings, "rate_limit_requests_per_minute", 10)
    monkeypatch.setattr(rate_limit, "get_async_redis_client", lambda: client)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA", None)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA_LOCK", None)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA_LOCK_LOOP", None)

    is_allowed = await rate_limit.allow_request_async(request)

    assert is_allowed is True
    assert client.script_load_calls == 1
    assert len(client.evalsha_calls) == 1
    assert len(client.eval_calls) == 1
    assert client.eval_calls[0][3] == 60


@pytest.mark.anyio
async def test_allow_request_async_does_not_reset_window_after_first_increment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_state: dict[str, dict[str, int]] = {}

    class _AtomicLuaRedis:
        async def script_load(self, script: str) -> str:
            return "script-sha-atomic"

        async def evalsha(self, sha: str, numkeys: int, key: str, ttl: int) -> int:
            state = key_state.setdefault(key, {"count": 0, "ttl_sets": 0})
            state["count"] += 1
            if state["count"] == 1:
                state["ttl_sets"] += 1
            return state["count"]

        async def eval(self, script: str, numkeys: int, key: str, ttl: int) -> int:
            raise AssertionError("EVAL should not be used when EVALSHA succeeds")

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
    monkeypatch.setattr(rate_limit.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(rate_limit.settings, "rate_limit_requests_per_minute", 10)
    monkeypatch.setattr(rate_limit, "get_async_redis_client", lambda: _AtomicLuaRedis())
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA", None)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA_LOCK", None)
    monkeypatch.setattr(rate_limit, "_RATE_LIMIT_LUA_SHA_LOCK_LOOP", None)

    await asyncio.gather(*[rate_limit.allow_request_async(request) for _ in range(10)])

    state = key_state["stubgraph:rl:127.0.0.1"]
    assert state["count"] == 10
    assert state["ttl_sets"] == 1
