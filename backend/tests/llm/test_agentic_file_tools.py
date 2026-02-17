import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402


class _FakeReadable:
    def __init__(self, text: str) -> None:
        self.text = text
        self.read_calls: list[int] = []

    def read(self, size: int = -1) -> str:
        self.read_calls.append(size)
        if size is None or size < 0:
            return self.text
        return self.text[:size]

    def __enter__(self) -> "_FakeReadable":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeIterable:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.read_called = False
        self.lines_yielded = 0

    def read(self, *args, **kwargs) -> str:
        self.read_called = True
        raise AssertionError("read should not be called")

    def __iter__(self):
        for line in self.lines:
            self.lines_yielded += 1
            yield line

    def __enter__(self) -> "_FakeIterable":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class TestAgenticFileTools(unittest.TestCase):
    def test_get_file_reads_with_limit_and_truncates(self) -> None:
        meta = agentic.AgenticMeta()
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "sample.txt"
            file_path.write_text("x" * 500, encoding="utf-8")
            args = {"path": "sample.txt", "max_chars": 250}
            max_file_chars = 300
            expected_max_chars = min(
                agentic._clamp_int(args["max_chars"], max_file_chars, 200, 50_000), max_file_chars
            )
            fake = _FakeReadable("y" * (expected_max_chars + 10))
            with patch.object(Path, "open", return_value=fake) as mocked_open:
                result = agentic._tool_get_file(1, root, meta, args, max_file_chars=max_file_chars)
            self.assertTrue(result["ok"])
            self.assertTrue(result["data"]["truncated"])
            self.assertEqual(len(result["data"]["content"]), expected_max_chars)
            self.assertEqual(fake.read_calls, [expected_max_chars + 1])
            _, kwargs = mocked_open.call_args
            self.assertEqual(kwargs, {"encoding": "utf-8", "errors": "replace"})

    def test_get_file_lines_iterates_without_read(self) -> None:
        meta = agentic.AgenticMeta()
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "lines.txt"
            file_path.write_text("placeholder\n", encoding="utf-8")
            args = {"path": "lines.txt", "start_line": 2, "end_line": 4, "max_chars": 220}
            max_file_chars = 300
            expected_max_chars = min(
                agentic._clamp_int(args["max_chars"], max_file_chars, 200, 50_000), max_file_chars
            )
            lines = ["a" * 120 + "\n"] * 6
            fake = _FakeIterable(lines)
            with patch.object(Path, "open", return_value=fake) as mocked_open:
                result = agentic._tool_get_file_lines(
                    1,
                    root,
                    meta,
                    args,
                    max_file_chars=max_file_chars,
                )
            self.assertTrue(result["ok"])
            self.assertTrue(result["data"]["truncated"])
            self.assertEqual(len(result["data"]["content"]), expected_max_chars)
            self.assertFalse(fake.read_called)
            self.assertLessEqual(fake.lines_yielded, args["end_line"])
            _, kwargs = mocked_open.call_args
            self.assertEqual(kwargs, {"encoding": "utf-8", "errors": "replace"})


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
