import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main, s3_runtime
from app.config import settings


@pytest.mark.anyio
async def test_lifespan_initializes_and_closes_s3_runtime_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_backend = settings.storage_backend

    async def _fake_init_db() -> None:
        calls.append("init_db")

    async def _fake_init_redis() -> None:
        calls.append("init_redis")

    async def _fake_init_s3() -> None:
        calls.append("init_s3")

    async def _fake_close_s3() -> None:
        calls.append("close_s3")

    async def _fake_close_redis() -> None:
        calls.append("close_redis")

    async def _fake_close_openai() -> None:
        calls.append("close_openai")

    async def _fake_close_db() -> None:
        calls.append("close_db")

    monkeypatch.setattr(main, "init_async_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis_pool_async", _fake_init_redis)
    monkeypatch.setattr(main, "init_s3_runtime", _fake_init_s3)
    monkeypatch.setattr(main, "close_s3_runtime", _fake_close_s3)
    monkeypatch.setattr(main, "close_redis_pool_async", _fake_close_redis)
    monkeypatch.setattr(main, "close_async_openai_client", _fake_close_openai)
    monkeypatch.setattr(main, "close_async_db", _fake_close_db)

    try:
        settings.storage_backend = "s3"
        async with main.lifespan(FastAPI()):
            calls.append("inside")
    finally:
        settings.storage_backend = original_backend

    assert calls == [
        "init_db",
        "init_redis",
        "init_s3",
        "inside",
        "close_s3",
        "close_redis",
        "close_openai",
        "close_db",
    ]


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


@pytest.mark.anyio
async def test_s3_runtime_concurrent_init_close_reuses_single_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = {"count": 0}
    exited = {"count": 0}
    client = object()

    class _ClientCtx:
        async def __aenter__(self):
            entered["count"] += 1
            return client

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            exited["count"] += 1

    class _Session:
        def client(self, *_args, **_kwargs):
            return _ClientCtx()

    monkeypatch.setattr(s3_runtime, "_build_session", lambda: _Session())

    await s3_runtime.close_s3_runtime()
    clients = await asyncio.gather(*[s3_runtime.init_s3_runtime() for _ in range(20)])
    _ = clients

    fetched = await asyncio.gather(
        *[asyncio.to_thread(s3_runtime.get_s3_client) for _ in range(20)]
    )
    await asyncio.gather(*[s3_runtime.close_s3_runtime() for _ in range(20)])

    assert all(item is client for item in fetched)
    assert entered["count"] == 1
    assert exited["count"] == 1


@pytest.mark.anyio
async def test_s3_runtime_reinit_keeps_signed_url_generation_working(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Client:
        def generate_presigned_url(self, _method: str, *, Params: dict, ExpiresIn: int):
            _ = ExpiresIn
            return f"https://signed/{Params['Bucket']}/{Params['Key']}"

    class _ClientCtx:
        async def __aenter__(self):
            return _Client()

        async def __aexit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb

    class _Session:
        def client(self, *_args, **_kwargs):
            return _ClientCtx()

    from app import storage

    monkeypatch.setattr(s3_runtime, "_build_session", lambda: _Session())
    monkeypatch.setattr(storage, "get_s3_client", s3_runtime.get_s3_client)

    await s3_runtime.close_s3_runtime()
    await s3_runtime.init_s3_runtime()
    first = await storage._s3_signed_url_async("bucket", "patches/first.diff")
    await s3_runtime.close_s3_runtime()
    await s3_runtime.init_s3_runtime()
    second = await storage._s3_signed_url_async("bucket", "patches/second.diff")
    await s3_runtime.close_s3_runtime()

    assert first == "https://signed/bucket/patches/first.diff"
    assert second == "https://signed/bucket/patches/second.diff"
