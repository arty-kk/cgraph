import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main, s3_runtime
from app.config import settings


@pytest.mark.anyio
async def test_lifespan_initializes_and_closes_s3_runtime_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original_backend = settings.storage_backend

    async def _fake_init_db() -> None:
        calls.append("init_db")

    async def _fake_init_s3() -> None:
        calls.append("init_s3")

    async def _fake_close_s3() -> None:
        calls.append("close_s3")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_s3_runtime", _fake_init_s3)
    monkeypatch.setattr(main, "close_s3_runtime", _fake_close_s3)

    try:
        settings.storage_backend = "s3"
        async with main.lifespan(FastAPI()):
            calls.append("inside")
    finally:
        settings.storage_backend = original_backend

    assert calls == ["init_db", "init_s3", "inside", "close_s3"]


@pytest.mark.anyio
async def test_s3_runtime_init_and_close_are_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = {"count": 0}
    exited = {"count": 0}

    class _ClientCtx:
        async def __aenter__(self):
            entered["count"] += 1
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            exited["count"] += 1

    class _Session:
        def client(self, *_args, **_kwargs):
            return _ClientCtx()

    monkeypatch.setattr(s3_runtime, "_build_session", lambda: _Session())

    await s3_runtime.close_s3_runtime()
    await s3_runtime.init_s3_runtime()
    await s3_runtime.init_s3_runtime()
    await s3_runtime.close_s3_runtime()
    await s3_runtime.close_s3_runtime()

    assert entered["count"] == 1
    assert exited["count"] == 1
