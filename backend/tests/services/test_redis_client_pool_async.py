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


@pytest.fixture(autouse=True)
def _reset_async_redis_pool() -> None:
    asyncio.run(redis_client.close_redis_pool_async())
    yield
    asyncio.run(redis_client.close_redis_pool_async())


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


@pytest.mark.anyio
async def test_close_redis_pool_async_is_safe_under_concurrent_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_AsyncClient] = []

    def _from_url(*args, **kwargs):
        _ = (args, kwargs)
        client = _AsyncClient()
        created.append(client)
        return client

    await redis_client.close_redis_pool_async()
    monkeypatch.setattr(redis_client.redis_async.Redis, "from_url", _from_url)

    await redis_client.init_redis_pool_async()
    await asyncio.gather(
        redis_client.close_redis_pool_async(),
        redis_client.close_redis_pool_async(),
        redis_client.close_redis_pool_async(),
    )

    assert len(created) == 1
    assert created[0].closed is True


@pytest.mark.anyio
async def test_init_and_close_redis_pool_async_race_does_not_double_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _RaceClient(_AsyncClient):
        async def aclose(self):
            events.append("close")
            await asyncio.sleep(0)
            self.closed = True

    created: list[_RaceClient] = []

    def _from_url(*args, **kwargs):
        _ = (args, kwargs)
        client = _RaceClient()
        created.append(client)
        events.append("create")
        return client

    await redis_client.close_redis_pool_async()
    monkeypatch.setattr(redis_client.redis_async.Redis, "from_url", _from_url)

    await redis_client.init_redis_pool_async()
    await asyncio.gather(
        redis_client.close_redis_pool_async(),
        redis_client.init_redis_pool_async(),
    )

    assert events.count("close") == 1
    assert events.count("create") == 2
    assert redis_client.get_async_redis_client() is created[-1]


def test_init_redis_pool_async_safe_across_event_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    created: list[_AsyncClient] = []

    def _from_url(*args, **kwargs):
        _ = (args, kwargs)
        client = _AsyncClient()
        created.append(client)
        return client

    asyncio.run(redis_client.close_redis_pool_async())
    monkeypatch.setattr(redis_client.redis_async.Redis, "from_url", _from_url)

    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            asyncio.run(redis_client.init_redis_pool_async())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(created) == 1
