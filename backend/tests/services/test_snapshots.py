import io
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.snapshots import prepare_snapshot_root, store_snapshot_blob  # noqa: E402


class TestSnapshots(unittest.TestCase):
    def test_store_and_extract_snapshot(self) -> None:
        original_dir = settings.db_dir
        original_backend = settings.storage_backend
        try:
            with TemporaryDirectory() as tmpdir:
                settings.db_dir = Path(tmpdir)
                settings.storage_backend = "local"
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as zf:
                    zf.writestr("repo/README.md", "hello")
                meta = store_snapshot_blob(buffer.getvalue(), "repo.zip")
                root = prepare_snapshot_root(meta)
                self.assertTrue((root / "repo" / "README.md").exists())
        finally:
            settings.db_dir = original_dir
            settings.storage_backend = original_backend


if __name__ == "__main__":
    unittest.main()
