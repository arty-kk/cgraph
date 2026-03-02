from __future__ import annotations

import asyncio
import importlib
from typing import Any

from .config import settings


class S3RuntimeError(RuntimeError):
    pass


_session: Any | None = None
_client: Any | None = None
_client_cm: Any | None = None
_s3_runtime_lock: asyncio.Lock | None = None
_s3_runtime_lock_loop: asyncio.AbstractEventLoop | None = None


def _get_s3_runtime_lock() -> asyncio.Lock:
    global _s3_runtime_lock, _s3_runtime_lock_loop
    loop = asyncio.get_running_loop()
    if _s3_runtime_lock is None or _s3_runtime_lock_loop is not loop:
        _s3_runtime_lock = asyncio.Lock()
        _s3_runtime_lock_loop = loop
    return _s3_runtime_lock


def _build_session() -> Any:
    aioboto3 = importlib.import_module("aioboto3")
    return aioboto3.Session(
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
    )


async def init_s3_runtime() -> None:
    global _session, _client, _client_cm
    async with _get_s3_runtime_lock():
        if _client is not None:
            return
        _session = _build_session()
        _client_cm = _session.client(
            "s3",
            region_name=settings.s3_region or None,
            endpoint_url=settings.s3_endpoint_url or None,
        )
        _client = await _client_cm.__aenter__()


async def close_s3_runtime() -> None:
    global _session, _client, _client_cm
    async with _get_s3_runtime_lock():
        saved_cm = _client_cm
        _session = None
        _client_cm = None
        _client = None
    if saved_cm is not None:
        await saved_cm.__aexit__(None, None, None)


def get_s3_client() -> Any:
    if _client is None:
        raise S3RuntimeError("S3 runtime is not initialized")
    return _client
