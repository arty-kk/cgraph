import ast
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.errors import ExternalServiceError
from app.infra import cache, redis_client

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class _AsyncClient:
    def __init__(self, *, get_payload: str | None = '{"ok": true}'):
        self.get_payload = get_payload
        self.get_calls: list[str] = []
        self.setex_calls: list[tuple[str, int, str]] = []
        self.delete_calls: list[str] = []
        self.scan_values: list[str] = ["stubgraph:k:1", "stubgraph:k:2"]

    async def get(self, key: str):
        self.get_calls.append(key)
        return self.get_payload

    async def setex(self, key: str, ttl: int, payload: str):
        self.setex_calls.append((key, ttl, payload))

    async def delete(self, key: str):
        self.delete_calls.append(key)

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
    assert client.delete_calls == ["stubgraph:k:1", "stubgraph:k:2"]


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

    assert exc.value.context == {"key": "stubgraph:k"}
