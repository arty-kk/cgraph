import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.append(str(Path(__file__).resolve().parents[2]))

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
