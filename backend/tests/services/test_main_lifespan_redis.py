import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main


async def _noop_async():
    return None


def test_lifespan_initializes_and_closes_runtime_in_order(monkeypatch):
    calls: list[str] = []
    original_openai_api_key = main.settings.openai_api_key

    async def _record(name: str):
        calls.append(name)

    monkeypatch.setattr(
        main,
        "build_startup_steps",
        lambda *, role: [
            ("init_redis", lambda: _record("init_redis")),
            ("init_db", lambda: _record("init_db")),
            ("init_fs", lambda: _record("init_fs")),
            ("init_cpu", lambda: _record("init_cpu")),
            ("init_external_io", lambda: _record("init_external_io")),
            ("init_openai", lambda: _record("init_openai")),
        ],
    )
    monkeypatch.setattr(
        main,
        "build_cleanup_steps",
        lambda *, role: [
            ("close_redis", lambda: _record("close_redis")),
            ("close_openai", lambda: _record("close_openai")),
            ("close_fs", lambda: _record("close_fs")),
            ("close_cpu", lambda: _record("close_cpu")),
            ("close_external_io", lambda: _record("close_external_io")),
            ("close_scan", lambda: _record("close_scan")),
            ("close_db", lambda: _record("close_db")),
        ],
    )

    monkeypatch.setattr(main.settings, "storage_backend", "local")
    monkeypatch.setattr(main.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    try:
        with TestClient(main.app) as client:
            response = client.get("/health")
            assert response.status_code == 200
    finally:
        main.settings.openai_api_key = original_openai_api_key

    assert calls == [
        "init_redis",
        "init_db",
        "init_fs",
        "init_cpu",
        "init_external_io",
        "init_openai",
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

    monkeypatch.setattr(
        main,
        "build_startup_steps",
        lambda *, role: [("init_redis", _fake_init_redis), ("init_db", _fake_init_db)],
    )
    monkeypatch.setattr(
        main,
        "build_cleanup_steps",
        lambda *, role: [
            ("close_s3", lambda: _record("close_s3")),
            ("close_redis", lambda: _record("close_redis")),
            ("close_openai", lambda: _record("close_openai")),
            ("close_fs", lambda: _record("close_fs")),
            ("close_cpu", lambda: _record("close_cpu")),
            ("close_external_io", lambda: _record("close_external_io")),
            ("close_scan", lambda: _record("close_scan")),
            ("close_db", lambda: _record("close_db")),
        ],
    )

    monkeypatch.setattr(main.settings, "storage_backend", "s3")
    monkeypatch.setattr(main.settings, "openai_api_key", "")
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
    original_openai_api_key = main.settings.openai_api_key

    async def _record(name: str):
        calls.append(name)

    monkeypatch.setattr(
        main,
        "build_startup_steps",
        lambda *, role: [
            ("init_redis", lambda: _record("init_redis")),
            ("init_db", lambda: _record("init_db")),
            ("init_fs", lambda: _record("init_fs")),
            ("init_cpu", lambda: _record("init_cpu")),
            ("init_external_io", lambda: _record("init_external_io")),
            ("init_openai", lambda: _record("init_openai")),
        ],
    )
    monkeypatch.setattr(
        main,
        "build_cleanup_steps",
        lambda *, role: [
            ("close_s3", lambda: _record("close_s3")),
            ("close_redis", lambda: _record("close_redis")),
            ("close_openai", lambda: _record("close_openai")),
            ("close_fs", lambda: _record("close_fs")),
            ("close_cpu", lambda: _record("close_cpu")),
            ("close_external_io", lambda: _record("close_external_io")),
            ("close_scan", lambda: _record("close_scan")),
            ("close_db", lambda: _record("close_db")),
        ],
    )

    monkeypatch.setattr(main.settings, "storage_backend", "local")
    monkeypatch.setattr(main.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    try:
        for _ in range(2):
            with TestClient(main.app) as client:
                assert client.get("/health").status_code == 200
    finally:
        main.settings.openai_api_key = original_openai_api_key

    assert calls.count("init_db") == 2
    assert calls.count("close_db") == 2
    assert calls.count("close_redis") == 2


def test_db_session_dependency_skips_health(monkeypatch):
    calls = {"enter": 0}

    class _Ctx:
        async def __aenter__(self):
            calls["enter"] += 1
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    monkeypatch.setattr(main, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(main, "build_startup_steps", lambda *, role: [("noop", lambda: _noop_async())])
    monkeypatch.setattr(main, "build_cleanup_steps", lambda *, role: [("noop", lambda: _noop_async())])
    monkeypatch.setattr(main.settings, "auth_enabled", False)
    monkeypatch.setattr(main.settings, "openai_api_key", "")
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert calls["enter"] == 0
