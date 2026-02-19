import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import storage
from app.config import settings


class _Body:
    def __init__(self, payload: bytes):
        self.payload = payload

    async def read(self) -> bytes:
        return self.payload


class _FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.deleted: list[tuple[str, str]] = []

    async def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
        _ = ContentType
        self.objects[(Bucket, Key)] = Body

    async def get_object(self, *, Bucket: str, Key: str):
        return {"Body": _Body(self.objects[(Bucket, Key)])}

    async def delete_object(self, *, Bucket: str, Key: str):
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)

    def generate_presigned_url(self, _method: str, *, Params: dict, ExpiresIn: int):
        _ = ExpiresIn
        return f"https://signed/{Params['Bucket']}/{Params['Key']}"


@pytest.mark.anyio
async def test_patch_blob_s3_concurrent_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket
    fake = _FakeS3()
    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)

    try:
        settings.storage_backend = "s3"
        settings.s3_bucket = "bucket"

        payloads = [f"patch-{idx}" for idx in range(6)]
        metas = await asyncio.gather(*[storage.store_patch_blob_async(payload) for payload in payloads])
        read_back = await asyncio.gather(*[storage.read_patch_blob_async(meta) for meta in metas])
        urls = await asyncio.gather(*[storage.get_patch_download_url_async(meta) for meta in metas])
        await asyncio.gather(*[storage.delete_patch_blob_async(meta) for meta in metas])

        assert read_back == payloads
        assert all(url and url.startswith("https://signed/bucket/") for url in urls)
        assert len(fake.deleted) == len(payloads)
    finally:
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_s3_signed_url_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeS3()
    called = {"value": False}

    async def _fake_to_thread(func, *args, **kwargs):
        called["value"] = True
        return func(*args, **kwargs)

    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)
    monkeypatch.setattr(storage.asyncio, "to_thread", _fake_to_thread)

    url = await storage._s3_signed_url_async("bucket", "patches/a.diff")

    assert called["value"] is True
    assert url == "https://signed/bucket/patches/a.diff"


@pytest.mark.anyio
async def test_s3_signed_url_async_sdk_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    original_backend = settings.storage_backend
    original_bucket = settings.s3_bucket

    class _FailingS3(_FakeS3):
        def generate_presigned_url(self, _method: str, *, Params: dict, ExpiresIn: int):
            _ = (Params, ExpiresIn)
            raise RuntimeError("sdk error")

    fake = _FailingS3()
    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)

    try:
        settings.storage_backend = "s3"
        settings.s3_bucket = "bucket"

        meta = await storage.store_patch_blob_async("patch")
        assert "download_url" not in meta
        assert await storage.get_patch_download_url_async(meta) is None
    finally:
        settings.storage_backend = original_backend
        settings.s3_bucket = original_bucket


@pytest.mark.anyio
async def test_s3_signed_url_async_respects_semaphore_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    limit = 2
    current = 0
    max_seen = 0
    lock = threading.Lock()

    class _BlockingS3(_FakeS3):
        def generate_presigned_url(self, _method: str, *, Params: dict, ExpiresIn: int):
            nonlocal current, max_seen
            _ = (_method, Params, ExpiresIn)
            with lock:
                current += 1
                max_seen = max(max_seen, current)
            time.sleep(0.05)
            with lock:
                current -= 1
            return "https://signed/bucket/key"

    fake = _BlockingS3()
    monkeypatch.setattr(storage, "get_s3_client", lambda: fake)
    monkeypatch.setattr(storage, "_S3_SIGNED_URL_SEMAPHORE", asyncio.Semaphore(limit))

    urls = await asyncio.gather(
        *[storage._s3_signed_url_async("bucket", f"patches/{idx}.diff") for idx in range(8)]
    )

    assert all(url == "https://signed/bucket/key" for url in urls)
    assert max_seen <= limit
