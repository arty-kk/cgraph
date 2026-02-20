from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic


class _IndexedSession:
    async def execute(self, _query):
        class _Result:
            def first(self):
                return (1,)

        return _Result()


class TestAgenticSearchTextLimitsRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_search_text_respects_max_matches(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "many.txt").write_text(("needle x\n" * 200), encoding="utf-8")
            session = _IndexedSession()
            meta = agentic.AgenticMeta(
                fs_ops_semaphore=asyncio.Semaphore(2),
                cpu_ops_semaphore=asyncio.Semaphore(2),
            )

            with patch("app.llm.agentic.tools.search_text_paths_async", return_value=["many.txt"]):
                result = await agentic._tool_search_text_async(
                    session,
                    1,
                    root,
                    {"query": "needle", "max_files": 1, "max_matches": 7, "context_chars": 80},
                    max_file_chars=5_000,
                    meta=meta,
                )

        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["max_matches"], 7)
        self.assertEqual(len(data["matches"]), 7)

    async def test_search_text_truncation_flags_and_scan_cap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = ("x" * 240) + "needle-after-limit"
            (root / "truncate.txt").write_text(payload, encoding="utf-8")
            session = _IndexedSession()
            meta = agentic.AgenticMeta(
                fs_ops_semaphore=asyncio.Semaphore(2),
                cpu_ops_semaphore=asyncio.Semaphore(2),
            )

            with patch("app.llm.agentic.tools.search_text_paths_async", return_value=["truncate.txt"]):
                result = await agentic._tool_search_text_async(
                    session,
                    1,
                    root,
                    {"query": "needle-after-limit", "max_files": 1, "max_matches": 5, "context_chars": 80},
                    max_file_chars=200,
                    meta=meta,
                )

        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["scan_max_chars_per_file"], 200)
        self.assertEqual(data["scanned_files"], 1)
        self.assertEqual(data["truncated_files"], 1)
        self.assertEqual(data["matches"], [])
        self.assertEqual(data["matched_files"], 0)


if __name__ == "__main__":
    unittest.main()
