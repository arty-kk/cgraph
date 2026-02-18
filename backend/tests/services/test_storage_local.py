import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import storage  # noqa: E402
from app.config import settings  # noqa: E402
from app.storage import delete_patch_blob, read_patch_blob, store_patch_blob  # noqa: E402


class TestLocalStorage(unittest.TestCase):
    def test_store_read_delete_patch(self) -> None:
        original_dir = settings.db_dir
        original_backend = settings.storage_backend
        try:
            with TemporaryDirectory() as tmpdir:
                settings.db_dir = Path(tmpdir)
                settings.storage_backend = "local"
                meta = store_patch_blob("test patch")
                text = read_patch_blob(meta)
                self.assertEqual(text, "test patch")
                delete_patch_blob(meta)
                file_path = Path(tmpdir) / meta["file"]
                self.assertFalse(file_path.exists())
        finally:
            settings.db_dir = original_dir
            settings.storage_backend = original_backend


if __name__ == "__main__":
    unittest.main()


@pytest.mark.anyio
async def test_storage_async_wrappers_use_to_thread(monkeypatch):
    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        if func is storage.store_patch_blob:
            return {"sha256": "sha"}
        if func is storage.read_patch_blob:
            return "patch"
        if func is storage.get_patch_download_url:
            return "https://example.test/diff"
        if func is storage.delete_patch_blob:
            return None
        raise AssertionError("unexpected call")

    monkeypatch.setattr(storage.asyncio, "to_thread", _fake_to_thread)

    store_meta = await storage.store_patch_blob_async("patch")
    patch_text = await storage.read_patch_blob_async({"sha256": "sha"})
    download_url = await storage.get_patch_download_url_async({"storage": "s3"})
    await storage.delete_patch_blob_async({"sha256": "sha"})

    assert store_meta == {"sha256": "sha"}
    assert patch_text == "patch"
    assert download_url == "https://example.test/diff"
    assert [call[0] for call in calls] == [
        storage.store_patch_blob,
        storage.read_patch_blob,
        storage.get_patch_download_url,
        storage.delete_patch_blob,
    ]
