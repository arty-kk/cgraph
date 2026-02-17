import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.infra import cache


class _SyncClient:
    def __init__(self, data: str | None = None):
        self._data = data
        self.closed = False
        self.setex_calls: list[tuple[str, int, str]] = []
        self.deleted: list[str] = []

    def get(self, _key: str):
        return self._data

    def setex(self, key: str, ttl: int, payload: str):
        self.setex_calls.append((key, ttl, payload))

    def scan_iter(self, match: str):
        _ = match
        yield "stubgraph:a"
        yield "stubgraph:b"

    def delete(self, key: str):
        self.deleted.append(key)

    def close(self):
        self.closed = True


@pytest.mark.anyio
async def test_cache_get_json_closes_sync_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _SyncClient('{"ok": true}')

    class _Ctx:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            client.close()
            return False

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "sync_redis_client", lambda: _Ctx())

    result = cache.cache_get_json(["k"])

    assert result == {"ok": True}
    assert client.closed is True


@pytest.mark.anyio
async def test_cache_set_json_closes_sync_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _SyncClient()

    class _Ctx:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            client.close()
            return False

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache.settings, "cache_default_ttl_seconds", 60)
    monkeypatch.setattr(cache, "sync_redis_client", lambda: _Ctx())

    cache.cache_set_json(["k"], {"x": 1})

    assert client.setex_calls
    assert client.closed is True


@pytest.mark.anyio
async def test_cache_invalidate_prefix_closes_sync_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _SyncClient()

    class _Ctx:
        def __enter__(self):
            return client

        def __exit__(self, exc_type, exc, tb):
            client.close()
            return False

    monkeypatch.setattr(cache.settings, "cache_enabled", True)
    monkeypatch.setattr(cache, "sync_redis_client", lambda: _Ctx())

    cache.cache_invalidate_prefix(["k"])

    assert client.deleted == ["stubgraph:a", "stubgraph:b"]
    assert client.closed is True
