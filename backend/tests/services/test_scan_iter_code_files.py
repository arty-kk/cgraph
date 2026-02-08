import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.scan import iter_code_files  # noqa: E402


class TestIterCodeFiles(unittest.TestCase):
    def test_allows_dot_dirs_from_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".config").mkdir()
            (root / ".git").mkdir()

            (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
            (root / ".config" / "tool.json").write_text("{}", encoding="utf-8")
            (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")

            found = {path.relative_to(root).as_posix() for path in iter_code_files(root)}

            self.assertIn(".github/workflows/ci.yml", found)
            self.assertIn(".config/tool.json", found)
            self.assertNotIn(".git/config", found)


if __name__ == "__main__":
    unittest.main()
