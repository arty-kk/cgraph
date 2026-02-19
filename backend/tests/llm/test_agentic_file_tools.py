import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402
from app.llm.agentic import tools as agentic_tools  # noqa: E402


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

    async def test_get_file_async_preserves_not_found_error_shape(self) -> None:
        meta = agentic.AgenticMeta()
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = await agentic._tool_get_file_async(
                1,
                root,
                meta,
                {"path": "missing.txt", "max_chars": 50},
                max_file_chars=80,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "not_found")
        self.assertEqual(result["error"]["details"], {"path": "missing.txt"})

    async def test_get_file_lines_async_preserves_not_a_file_error_shape(self) -> None:
        meta = agentic.AgenticMeta()
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "folder").mkdir()
            result = await agentic._tool_get_file_lines_async(
                1,
                root,
                meta,
                {"path": "folder", "start_line": 1, "end_line": 2, "max_chars": 50},
                max_file_chars=80,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "not_a_file")
        self.assertEqual(result["error"]["details"], {"path": "folder"})

    async def test_get_file_async_preserves_read_failed_error_shape(self) -> None:
        meta = agentic.AgenticMeta()
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "boom.txt").write_text("hello", encoding="utf-8")

            with patch(
                "app.llm.agentic.tools._resolve_and_read_file_under_root",
                side_effect=agentic_tools._file_read_failed("boom.txt", "denied: boom.txt"),
            ):
                result = await agentic._tool_get_file_async(
                    1,
                    root,
                    meta,
                    {"path": "boom.txt", "max_chars": 50},
                    max_file_chars=80,
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "read_failed")
        self.assertEqual(
            result["error"]["details"],
            {"path": "boom.txt", "reason": "denied: boom.txt"},
        )


if __name__ == "__main__":
    unittest.main()
