import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.storage import (  # noqa: E402
    delete_patch_blob_async,
    get_patch_download_url_async,
    read_patch_blob_async,
    store_patch_blob_async,
)


@pytest.mark.anyio
async def test_store_read_delete_patch_async_local() -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            meta = await store_patch_blob_async("test patch")
            text = await read_patch_blob_async(meta)

            assert text == "test patch"
            await delete_patch_blob_async(meta)
            file_path = Path(tmpdir) / meta["file"]
            assert not file_path.exists()
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend


@pytest.mark.anyio
async def test_store_patch_blob_async_does_not_overwrite_existing_file() -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            meta = await store_patch_blob_async("first")
            await store_patch_blob_async("second")

            text = await read_patch_blob_async(meta)
            assert text == "first"
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend


@pytest.mark.anyio
async def test_storage_async_local_concurrent_roundtrip() -> None:
    original_dir = settings.db_dir
    original_backend = settings.storage_backend
    try:
        with TemporaryDirectory() as tmpdir:
            settings.db_dir = Path(tmpdir)
            settings.storage_backend = "local"

            payloads = [f"patch-{idx}" for idx in range(8)]
            metas = await asyncio.gather(*[store_patch_blob_async(payload) for payload in payloads])
            texts = await asyncio.gather(*[read_patch_blob_async(meta) for meta in metas])

            assert texts == payloads
            await asyncio.gather(*[delete_patch_blob_async(meta) for meta in metas])
            urls = await asyncio.gather(*[get_patch_download_url_async(meta) for meta in metas])
            assert urls == [None] * len(metas)
    finally:
        settings.db_dir = original_dir
        settings.storage_backend = original_backend
