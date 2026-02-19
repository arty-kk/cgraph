import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main


def test_lifespan_initializes_and_closes_redis_pool(monkeypatch):
    calls: list[str] = []

    async def _fake_init_db():
        calls.append("init_db")

    async def _fake_init_redis():
        calls.append("init_redis")

    async def _fake_close_redis():
        calls.append("close_redis")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)

    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert calls == ["init_db", "init_redis", "close_redis"]


def test_lifespan_closes_redis_pool_on_startup_error(monkeypatch):
    calls: list[str] = []

    async def _fake_init_db():
        calls.append("init_db")

    async def _fake_init_redis():
        calls.append("init_redis")
        raise RuntimeError("boom")

    async def _fake_close_redis():
        calls.append("close_redis")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)

    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    try:
        with TestClient(main.app):
            pass
    except RuntimeError:
        pass

    assert calls == ["init_db", "init_redis", "close_redis"]
