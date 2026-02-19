import asyncio
import sys
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
