import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402


class TestAgenticFileToolsAsync(unittest.IsolatedAsyncioTestCase):
    async def test_get_file_async_uses_to_thread_for_file_read(self) -> None:
        meta = agentic.AgenticMeta()
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "sample.txt"
            file_path.write_text("x" * 100, encoding="utf-8")
            args = {"path": "sample.txt", "max_chars": 50}
            calls = 0

            async def _fake_to_thread(fn, *a, **kw):
                nonlocal calls
                calls += 1
                return fn(*a, **kw)

            with patch("app.llm.agentic.tools.asyncio.to_thread", side_effect=_fake_to_thread):
                result = await agentic._tool_get_file_async(1, root, meta, args, max_file_chars=80)

        self.assertTrue(result["ok"])
        self.assertIn("data", result)
        self.assertIsNone(result["error"])
        self.assertEqual(calls, 1)

    async def test_get_file_lines_async_schema_and_to_thread(self) -> None:
        meta = agentic.AgenticMeta()
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "lines.txt"
            file_path.write_text("a\n" * 5, encoding="utf-8")
            args = {"path": "lines.txt", "start_line": 2, "end_line": 3, "max_chars": 30}
            calls = 0

            async def _fake_to_thread(fn, *a, **kw):
                nonlocal calls
                calls += 1
                return fn(*a, **kw)

            with patch("app.llm.agentic.tools.asyncio.to_thread", side_effect=_fake_to_thread):
                result = await agentic._tool_get_file_lines_async(
                    1,
                    root,
                    meta,
                    args,
                    max_file_chars=100,
                )

        self.assertEqual(set(result.keys()), {"ok", "data", "error"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["start_line"], 2)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
