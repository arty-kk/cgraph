import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import rate_limit


class _FakeRedisClient:
    def __init__(self):
        self.incr_calls: list[str] = []
        self.expire_calls: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        self.incr_calls.append(key)
        return 1

    async def expire(self, key: str, seconds: int) -> None:
        self.expire_calls.append((key, seconds))


@pytest.mark.anyio
async def test_allow_request_async_uses_shared_client_concurrently(
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

    await asyncio.gather(
        rate_limit.allow_request_async(request),
        rate_limit.allow_request_async(request),
    )

    assert get_client_calls == 2
    assert len(client.incr_calls) == 2
    assert len(client.expire_calls) == 2
