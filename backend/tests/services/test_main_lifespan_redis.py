import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main


async def _noop_async():
    return None


def test_lifespan_initializes_and_closes_runtime_in_order(monkeypatch):
    calls: list[str] = []

    async def _record(name: str):
        calls.append(name)

    monkeypatch.setattr(main, "init_async_db", lambda: _record("init_db"))
    monkeypatch.setattr(main, "init_redis_pool_async", lambda: _record("init_redis"))
    monkeypatch.setattr(main, "init_fs_runtime", lambda: _record("init_fs"))
    monkeypatch.setattr(main, "init_cpu_runtime", lambda: _record("init_cpu"))
    monkeypatch.setattr(main, "init_external_io_runtime", lambda: _record("init_external_io"))

    monkeypatch.setattr(main, "close_redis_pool_async", lambda: _record("close_redis"))
    monkeypatch.setattr(main, "close_async_openai_client", lambda: _record("close_openai"))
    monkeypatch.setattr(main, "close_fs_runtime", lambda: _record("close_fs"))
    monkeypatch.setattr(main, "close_cpu_runtime", lambda: _record("close_cpu"))
    monkeypatch.setattr(main, "close_external_io_runtime", lambda: _record("close_external_io"))
    monkeypatch.setattr(main, "close_scan_runtime", lambda: _record("close_scan"))
    monkeypatch.setattr(main, "close_async_db", lambda: _record("close_db"))

    monkeypatch.setattr(main.settings, "storage_backend", "local")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert calls == [
        "init_redis",
        "init_db",
        "init_fs",
        "init_cpu",
        "init_external_io",
        "close_redis",
        "close_openai",
        "close_fs",
        "close_cpu",
        "close_external_io",
        "close_scan",
        "close_db",
    ]


def test_lifespan_closes_runtime_even_if_startup_fails(monkeypatch):
    calls: list[str] = []

    async def _fake_init_redis():
        calls.append("init_redis")

    async def _fake_init_db():
        calls.append("init_db")
        raise RuntimeError("boom")

    async def _record(name: str):
        calls.append(name)

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "close_s3_runtime", lambda: _record("close_s3"))
    monkeypatch.setattr(main, "close_redis_pool_async", lambda: _record("close_redis"))
    monkeypatch.setattr(main, "close_async_openai_client", lambda: _record("close_openai"))
    monkeypatch.setattr(main, "close_fs_runtime", lambda: _record("close_fs"))
    monkeypatch.setattr(main, "close_cpu_runtime", lambda: _record("close_cpu"))
    monkeypatch.setattr(main, "close_external_io_runtime", lambda: _record("close_external_io"))
    monkeypatch.setattr(main, "close_scan_runtime", lambda: _record("close_scan"))
    monkeypatch.setattr(main, "close_async_db", lambda: _record("close_db"))

    monkeypatch.setattr(main.settings, "storage_backend", "s3")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with pytest.raises(RuntimeError, match="boom"):
        with TestClient(main.app):
            pass

    assert calls == [
        "init_redis",
        "init_db",
        "close_s3",
        "close_redis",
        "close_openai",
        "close_fs",
        "close_cpu",
        "close_external_io",
        "close_scan",
        "close_db",
    ]


def test_lifespan_repeated_shutdown_remains_stable(monkeypatch):
    calls: list[str] = []

    async def _record(name: str):
        calls.append(name)

    monkeypatch.setattr(main, "init_async_db", lambda: _record("init_db"))
    monkeypatch.setattr(main, "init_redis_pool_async", lambda: _record("init_redis"))
    monkeypatch.setattr(main, "init_fs_runtime", lambda: _record("init_fs"))
    monkeypatch.setattr(main, "init_cpu_runtime", lambda: _record("init_cpu"))
    monkeypatch.setattr(main, "init_external_io_runtime", lambda: _record("init_external_io"))

    monkeypatch.setattr(main, "close_s3_runtime", lambda: _record("close_s3"))
    monkeypatch.setattr(main, "close_redis_pool_async", lambda: _record("close_redis"))
    monkeypatch.setattr(main, "close_async_openai_client", lambda: _record("close_openai"))
    monkeypatch.setattr(main, "close_fs_runtime", lambda: _record("close_fs"))
    monkeypatch.setattr(main, "close_cpu_runtime", lambda: _record("close_cpu"))
    monkeypatch.setattr(main, "close_external_io_runtime", lambda: _record("close_external_io"))
    monkeypatch.setattr(main, "close_scan_runtime", lambda: _record("close_scan"))
    monkeypatch.setattr(main, "close_async_db", lambda: _record("close_db"))

    monkeypatch.setattr(main.settings, "storage_backend", "local")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    for _ in range(2):
        with TestClient(main.app) as client:
            assert client.get("/health").status_code == 200

    assert calls.count("init_db") == 2
    assert calls.count("close_db") == 2
    assert calls.count("close_redis") == 2


def test_db_session_middleware_skips_health(monkeypatch):
    calls = {"enter": 0}

    class _Ctx:
        async def __aenter__(self):
            calls["enter"] += 1
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    monkeypatch.setattr(main, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(main, "init_async_db", lambda: _noop_async())
    monkeypatch.setattr(main, "init_redis_pool_async", lambda: _noop_async())
    monkeypatch.setattr(main, "init_fs_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "init_cpu_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "init_external_io_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_s3_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_redis_pool_async", lambda: _noop_async())
    monkeypatch.setattr(main, "close_fs_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_cpu_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_external_io_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_async_openai_client", lambda: _noop_async())
    monkeypatch.setattr(main, "close_scan_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_async_db", lambda: _noop_async())
    monkeypatch.setattr(main.settings, "auth_enabled", False)
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert calls["enter"] == 0
