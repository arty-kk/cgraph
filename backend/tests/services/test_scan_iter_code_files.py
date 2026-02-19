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


    def test_large_tree_keeps_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            expected: list[str] = []
            for folder_idx in range(25):
                folder = root / f"pkg_{folder_idx:02d}"
                folder.mkdir(parents=True)
                for file_idx in range(20):
                    rel = f"pkg_{folder_idx:02d}/file_{file_idx:02d}.py"
                    (root / rel).write_text("print('ok')\n", encoding="utf-8")
                    expected.append(rel)

            actual = [path.relative_to(root).as_posix() for path in iter_code_files(root)]

            self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
