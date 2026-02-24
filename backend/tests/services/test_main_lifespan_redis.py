import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main


async def _noop_async():
    return None


def test_lifespan_initializes_and_closes_runtime_in_order(monkeypatch):
    calls: list[str] = []

    async def _fake_init_db():
        calls.append("init_db")

    async def _fake_init_redis():
        calls.append("init_redis")

    async def _fake_init_fs():
        calls.append("init_fs")

    async def _fake_close_redis():
        calls.append("close_redis")

    async def _fake_close_openai():
        calls.append("close_openai")

    async def _fake_close_fs():
        calls.append("close_fs")

    async def _fake_close_db():
        calls.append("close_db")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "init_fs_runtime", _fake_init_fs)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)
    monkeypatch.setattr(main, "close_fs_runtime", _fake_close_fs)
    monkeypatch.setattr(main, "close_async_openai_client", _fake_close_openai)
    monkeypatch.setattr(main, "close_async_db", _fake_close_db)

    monkeypatch.setattr(main.settings, "storage_backend", "local")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert calls == [
        "init_db",
        "init_redis",
        "init_fs",
        "close_redis",
        "close_fs",
        "close_openai",
        "close_db",
    ]


def test_lifespan_closes_runtime_even_if_startup_fails(monkeypatch):
    calls: list[str] = []

    async def _fake_init_db():
        calls.append("init_db")
        raise RuntimeError("boom")

    async def _fake_init_redis():
        calls.append("init_redis")

    async def _fake_init_fs():
        calls.append("init_fs")

    async def _fake_close_s3():
        calls.append("close_s3")

    async def _fake_close_redis():
        calls.append("close_redis")

    async def _fake_close_fs():
        calls.append("close_fs")

    async def _fake_close_openai():
        calls.append("close_openai")

    async def _fake_close_db():
        calls.append("close_db")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "init_fs_runtime", _fake_init_fs)
    monkeypatch.setattr(main, "close_s3_runtime", _fake_close_s3)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)
    monkeypatch.setattr(main, "close_fs_runtime", _fake_close_fs)
    monkeypatch.setattr(main, "close_async_openai_client", _fake_close_openai)
    monkeypatch.setattr(main, "close_async_db", _fake_close_db)

    monkeypatch.setattr(main.settings, "storage_backend", "s3")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    try:
        with TestClient(main.app):
            pass
    except RuntimeError:
        pass

    assert calls == [
        "init_db",
        "close_s3",
        "close_redis",
        "close_fs",
        "close_openai",
        "close_db",
    ]


def test_lifespan_repeated_runs_do_not_leak_cleanup_calls(monkeypatch):
    calls: list[str] = []

    async def _fake_init_db():
        calls.append("init_db")

    async def _fake_init_redis():
        calls.append("init_redis")

    async def _fake_init_fs():
        calls.append("init_fs")

    async def _fake_close_redis():
        calls.append("close_redis")

    async def _fake_close_fs():
        calls.append("close_fs")

    async def _fake_close_openai():
        calls.append("close_openai")

    async def _fake_close_db():
        calls.append("close_db")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "init_fs_runtime", _fake_init_fs)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)
    monkeypatch.setattr(main, "close_fs_runtime", _fake_close_fs)
    monkeypatch.setattr(main, "close_async_openai_client", _fake_close_openai)
    monkeypatch.setattr(main, "close_async_db", _fake_close_db)

    monkeypatch.setattr(main.settings, "storage_backend", "local")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    for _ in range(3):
        with TestClient(main.app) as client:
            assert client.get("/health").status_code == 200

    assert calls.count("init_db") == 3
    assert calls.count("init_redis") == 3
    assert calls.count("init_fs") == 3
    assert calls.count("close_redis") == 3
    assert calls.count("close_fs") == 3
    assert calls.count("close_openai") == 3
    assert calls.count("close_db") == 3


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
    monkeypatch.setattr(main, "init_celery_producer_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_s3_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_redis_pool_async", lambda: _noop_async())
    monkeypatch.setattr(main, "close_fs_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_cpu_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_celery_producer_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_async_openai_client", lambda: _noop_async())
    monkeypatch.setattr(main, "close_scan_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_async_db", lambda: _noop_async())
    monkeypatch.setattr(main.settings, "auth_enabled", False)
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert calls["enter"] == 0


def test_db_session_middleware_keeps_api_session(monkeypatch):
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
    monkeypatch.setattr(main, "init_celery_producer_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_s3_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_redis_pool_async", lambda: _noop_async())
    monkeypatch.setattr(main, "close_fs_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_cpu_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_celery_producer_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_async_openai_client", lambda: _noop_async())
    monkeypatch.setattr(main, "close_scan_runtime", lambda: _noop_async())
    monkeypatch.setattr(main, "close_async_db", lambda: _noop_async())
    monkeypatch.setattr(main.settings, "auth_enabled", False)
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/api/unknown")

    assert response.status_code == 404
    assert calls["enter"] == 1
