import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import redis_client


class _AsyncClient:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.mark.anyio
async def test_init_redis_pool_async_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[_AsyncClient] = []

    def _from_url(*args, **kwargs):
        _ = (args, kwargs)
        client = _AsyncClient()
        created.append(client)
        return client

    await redis_client.close_redis_pool_async()
    monkeypatch.setattr(redis_client.redis_async.Redis, "from_url", _from_url)

    await asyncio.gather(
        redis_client.init_redis_pool_async(),
        redis_client.init_redis_pool_async(),
        redis_client.init_redis_pool_async(),
    )

    assert len(created) == 1
    assert redis_client.get_async_redis_client() is created[0]


@pytest.mark.anyio
async def test_get_async_redis_client_fails_after_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _AsyncClient()
    await redis_client.close_redis_pool_async()
    monkeypatch.setattr(redis_client.redis_async.Redis, "from_url", lambda *args, **kwargs: client)

    await redis_client.init_redis_pool_async()
    await redis_client.close_redis_pool_async()

    assert client.closed is True
    with pytest.raises(RuntimeError):
        redis_client.get_async_redis_client()
