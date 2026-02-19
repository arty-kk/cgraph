import ast
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.errors import ExternalServiceError
from app.infra import cache, redis_client

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class _AsyncPipeline:
    def __init__(self, client: "_AsyncClient") -> None:
        self.client = client
        self.batch: list[str] = []

    def delete(self, key: str) -> None:
        self.batch.append(key)

    async def execute(self) -> None:
        self.client.pipeline_execute_calls += 1
        batch_no = self.client.pipeline_execute_calls
        self.client.pipeline_batches.append(list(self.batch))
        if batch_no == self.client.fail_on_pipeline_batch:
            raise cache.RedisError(f"pipeline batch {batch_no} failed")


class _AsyncClient:
    def __init__(
        self,
        *,
        get_payload: str | None = '{"ok": true}',
        scan_values: list[str] | None = None,
        fail_on_unlink_batch: int | None = None,
        fail_on_pipeline_batch: int | None = None,
        unlink_unavailable: bool = False,
    ):
        self.get_payload = get_payload
        self.get_calls: list[str] = []
        self.setex_calls: list[tuple[str, int, str]] = []
        self.scan_values: list[str] = scan_values or ["stubgraph:k:1", "stubgraph:k:2"]
        self.unlink_batches: list[list[str]] = []
        self.pipeline_batches: list[list[str]] = []
        self.unlink_calls = 0
        self.pipeline_execute_calls = 0
        self.fail_on_unlink_batch = fail_on_unlink_batch
        self.fail_on_pipeline_batch = fail_on_pipeline_batch
        self.unlink_unavailable = unlink_unavailable

    async def get(self, key: str):
        self.get_calls.append(key)
        return self.get_payload

    async def setex(self, key: str, ttl: int, payload: str):
        self.setex_calls.append((key, ttl, payload))

    async def unlink(self, *keys: str):
        if self.unlink_unavailable:
            raise AttributeError("unlink is unavailable")
        self.unlink_calls += 1
        self.unlink_batches.append(list(keys))
        if self.unlink_calls == self.fail_on_unlink_batch:
            raise cache.RedisError(f"unlink batch {self.unlink_calls} failed")

    def pipeline(self, transaction: bool = False):
        _ = transaction
        return _AsyncPipeline(self)

    async def scan_iter(self, match: str):
        _ = match
        for item in self.scan_values:
            yield item


def _load_function_names(relative_path: str) -> set[str]:
    path = BACKEND_ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_sync_cache_and_redis_api_is_not_publicly_available() -> None:
    assert not hasattr(cache, "cache_get_json")
    assert not hasattr(cache, "cache_set_json")
    assert not hasattr(cache, "cache_invalidate_prefix")
    assert not hasattr(redis_client, "get_redis_client")
    assert not hasattr(redis_client, "sync_redis_client")


def test_sync_cache_and_redis_api_is_absent_in_source_contract() -> None:
    cache_functions = _load_function_names("app/infra/cache.py")
    redis_functions = _load_function_names("app/infra/redis_client.py")

    assert {"cache_get_json", "cache_set_json", "cache_invalidate_prefix"}.isdisjoint(cache_functions)
    assert {"get_redis_client", "sync_redis_client"}.isdisjoint(redis_functions)


@pytest.mark.anyio
async def test_cache_get_json_async_returns_none_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _AsyncClient(get_payload="not-json")

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "get_async_redis_client", lambda: client)

    result = await cache.cache_get_json_async(["k"])

    assert result is None


@pytest.mark.anyio
async def test_cache_async_uses_shared_client_for_concurrent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _AsyncClient()
    get_client_calls = 0

    def _get_client():
        nonlocal get_client_calls
        get_client_calls += 1
        return client

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache.settings, "cache_default_ttl_seconds", 60)
    monkeypatch.setattr(cache, "get_async_redis_client", _get_client)

    await asyncio.gather(
        cache.cache_get_json_async(["k"]),
        cache.cache_set_json_async(["k"], {"x": 1}),
        cache.cache_invalidate_prefix_async(["k"]),
    )

    assert get_client_calls == 3
    assert len(client.get_calls) == 1
    assert len(client.setex_calls) == 1
    assert client.unlink_batches == [["stubgraph:k:1", "stubgraph:k:2"]]


@pytest.mark.anyio
async def test_cache_get_json_async_maps_redis_error_to_external_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient:
        async def get(self, _key: str):
            raise cache.RedisError("boom")

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "get_async_redis_client", lambda: _FailingClient())

    with pytest.raises(ExternalServiceError) as exc:
        await cache.cache_get_json_async(["k"])

    assert exc.value.context == {"key": "stubgraph:k"}


@pytest.mark.anyio
async def test_cache_set_json_async_maps_redis_error_to_external_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient:
        async def setex(self, _key: str, _ttl: int, _payload: str):
            raise cache.RedisError("boom")

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache.settings, "cache_default_ttl_seconds", 60)
    monkeypatch.setattr(cache, "get_async_redis_client", lambda: _FailingClient())

    with pytest.raises(ExternalServiceError) as exc:
        await cache.cache_set_json_async(["k"], {"x": 1})

    assert exc.value.context == {"key": "stubgraph:k"}


@pytest.mark.anyio
async def test_cache_invalidate_prefix_async_uses_batched_unlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_values = [f"stubgraph:k:{index}" for index in range(1, 2501)]
    client = _AsyncClient(scan_values=scan_values)

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache.settings, "cache_invalidate_batch_size", 1000)
    monkeypatch.setattr(cache, "get_async_redis_client", lambda: client)

    await cache.cache_invalidate_prefix_async(["k"])

    assert client.unlink_calls == 3
    assert [len(batch) for batch in client.unlink_batches] == [1000, 1000, 500]
    assert client.pipeline_execute_calls == 0


@pytest.mark.anyio
async def test_cache_invalidate_prefix_async_falls_back_to_pipeline_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_values = [f"stubgraph:k:{index}" for index in range(1, 2201)]
    client = _AsyncClient(scan_values=scan_values, unlink_unavailable=True)

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache.settings, "cache_invalidate_batch_size", 1000)
    monkeypatch.setattr(cache, "get_async_redis_client", lambda: client)

    await cache.cache_invalidate_prefix_async(["k"])

    assert client.unlink_calls == 0
    assert client.pipeline_execute_calls == 3
    assert [len(batch) for batch in client.pipeline_batches] == [1000, 1000, 200]


@pytest.mark.anyio
async def test_cache_invalidate_prefix_async_returns_partial_stats_on_second_batch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_values = [f"stubgraph:k:{index}" for index in range(1, 2501)]
    client = _AsyncClient(scan_values=scan_values, fail_on_unlink_batch=2)

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache.settings, "cache_invalidate_batch_size", 1000)
    monkeypatch.setattr(cache, "get_async_redis_client", lambda: client)

    with pytest.raises(ExternalServiceError) as exc:
        await cache.cache_invalidate_prefix_async(["k"])

    assert exc.value.context == {
        "key": "stubgraph:k",
        "pattern": "stubgraph:k*",
        "deleted_count": 1000,
        "batches": 1,
    }


@pytest.mark.anyio
async def test_cache_invalidate_prefix_async_maps_redis_error_to_external_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingClient:
        async def scan_iter(self, match: str):
            _ = match
            raise cache.RedisError("boom")
            yield  # pragma: no cover

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "get_async_redis_client", lambda: _FailingClient())

    with pytest.raises(ExternalServiceError) as exc:
        await cache.cache_invalidate_prefix_async(["k"])

    assert exc.value.context == {
        "key": "stubgraph:k",
        "pattern": "stubgraph:k*",
        "deleted_count": 0,
        "batches": 0,
    }
