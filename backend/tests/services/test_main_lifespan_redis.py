import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main


def test_lifespan_initializes_and_closes_runtime_in_order(monkeypatch):
    calls: list[str] = []

    async def _fake_init_db():
        calls.append("init_db")

    async def _fake_init_redis():
        calls.append("init_redis")

    async def _fake_close_redis():
        calls.append("close_redis")

    async def _fake_close_openai():
        calls.append("close_openai")

    async def _fake_close_db():
        calls.append("close_db")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)
    monkeypatch.setattr(main, "close_async_openai_client", _fake_close_openai)
    monkeypatch.setattr(main, "close_async_db", _fake_close_db)

    monkeypatch.setattr(main.settings, "storage_backend", "local")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert calls == ["init_db", "init_redis", "close_redis", "close_openai", "close_db"]


def test_lifespan_closes_runtime_even_if_startup_fails(monkeypatch):
    calls: list[str] = []

    async def _fake_init_db():
        calls.append("init_db")
        raise RuntimeError("boom")

    async def _fake_init_redis():
        calls.append("init_redis")

    async def _fake_close_s3():
        calls.append("close_s3")

    async def _fake_close_redis():
        calls.append("close_redis")

    async def _fake_close_openai():
        calls.append("close_openai")

    async def _fake_close_db():
        calls.append("close_db")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "close_s3_runtime", _fake_close_s3)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)
    monkeypatch.setattr(main, "close_async_openai_client", _fake_close_openai)
    monkeypatch.setattr(main, "close_async_db", _fake_close_db)

    monkeypatch.setattr(main.settings, "storage_backend", "s3")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    try:
        with TestClient(main.app):
            pass
    except RuntimeError:
        pass

    assert calls == ["init_db", "close_s3", "close_redis", "close_openai", "close_db"]
