import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import arq_client


class _FakeArqClient:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


@pytest.fixture(autouse=True)
def _reset_arq_pool() -> None:
    asyncio.run(arq_client.close_arq_pool_async())
    yield
    asyncio.run(arq_client.close_arq_pool_async())


@pytest.mark.anyio
async def test_get_arq_pool_async_concurrent_init_is_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_calls = 0
    client = _FakeArqClient()

    async def _fake_create_pool(*args, **kwargs):
        nonlocal create_calls
        _ = (args, kwargs)
        create_calls += 1
        await asyncio.sleep(0)
        return client

    monkeypatch.setattr(arq_client, "create_pool", _fake_create_pool)

    results = await asyncio.gather(*[arq_client.get_arq_pool_async() for _ in range(10)])

    assert create_calls == 1
    assert all(result is client for result in results)


@pytest.mark.anyio
async def test_arq_pool_repeated_lifecycle_init_close_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeArqClient] = []

    async def _fake_create_pool(*args, **kwargs):
        _ = (args, kwargs)
        client = _FakeArqClient()
        created.append(client)
        return client

    monkeypatch.setattr(arq_client, "create_pool", _fake_create_pool)

    first = await arq_client.get_arq_pool_async()
    await arq_client.close_arq_pool_async()
    second = await arq_client.get_arq_pool_async()

    assert len(created) == 2
    assert first is created[0]
    assert second is created[1]
    assert first is not second
    assert first.close_calls == 1
    assert second.close_calls == 0
    assert arq_client._arq_pool is second
