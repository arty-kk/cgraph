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
_lock = asyncio.Lock()


def _build_session() -> Any:
    aioboto3 = importlib.import_module("aioboto3")
    return aioboto3.Session(
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
    )


async def init_s3_runtime() -> None:
    global _session, _client, _client_cm
    async with _lock:
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
    async with _lock:
        if _client_cm is not None:
            await _client_cm.__aexit__(None, None, None)
        _session = None
        _client_cm = None
        _client = None


def get_s3_client() -> Any:
    if _client is None:
        raise S3RuntimeError("S3 runtime is not initialized")
    return _client
