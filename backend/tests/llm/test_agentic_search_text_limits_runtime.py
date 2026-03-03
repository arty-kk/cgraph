from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic
from app.llm.agentic import tools as agentic_tools


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


    async def test_search_text_pipeline_has_bounded_stage_concurrency(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = [f"f{idx}.txt" for idx in range(6)]
            for rel_path in paths:
                (root / rel_path).write_text("needle\n", encoding="utf-8")

            session = _IndexedSession()
            meta = agentic.AgenticMeta()
            read_in_flight = 0
            read_peak = 0
            cpu_in_flight = 0
            cpu_peak = 0
            lock = asyncio.Lock()
            real_read = agentic_tools._read_file_under_root_async
            real_cpu = agentic_tools._search_text_cpu_async

            async def _tracked_read(*args, **kwargs):
                nonlocal read_in_flight, read_peak
                async with lock:
                    read_in_flight += 1
                    read_peak = max(read_peak, read_in_flight)
                await asyncio.sleep(0.01)
                try:
                    return await real_read(*args, **kwargs)
                finally:
                    async with lock:
                        read_in_flight -= 1

            async def _tracked_cpu(*args, **kwargs):
                nonlocal cpu_in_flight, cpu_peak
                async with lock:
                    cpu_in_flight += 1
                    cpu_peak = max(cpu_peak, cpu_in_flight)
                await asyncio.sleep(0.01)
                try:
                    return await real_cpu(*args, **kwargs)
                finally:
                    async with lock:
                        cpu_in_flight -= 1

            with (
                patch.object(agentic_tools.settings, "llm_agentic_fs_ops_concurrency", 2),
                patch("app.llm.agentic.tools.search_text_paths_async", return_value=paths),
                patch("app.llm.agentic.tools._read_file_under_root_async", side_effect=_tracked_read),
                patch("app.llm.agentic.tools._search_text_cpu_async", side_effect=_tracked_cpu),
            ):
                result = await agentic._tool_search_text_async(
                    session,
                    1,
                    root,
                    {"query": "needle", "max_files": len(paths), "max_matches": 20, "context_chars": 80},
                    max_file_chars=5_000,
                    meta=meta,
                )

        self.assertTrue(result["ok"])
        self.assertLessEqual(read_peak, 2)
        self.assertLessEqual(cpu_peak, 2)

    async def test_search_text_preserves_result_order_under_parallel_execution(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ["03.txt", "01.txt", "02.txt", "04.txt"]
            for rel_path in paths:
                (root / rel_path).write_text(f"needle in {rel_path}\n", encoding="utf-8")

            session = _IndexedSession()

            real_read = agentic_tools._read_file_under_root_async

            async def _read_with_delay(root_arg, rel_path, reader, *, meta):
                delay = {"03.txt": 0.03, "01.txt": 0.01, "02.txt": 0.02, "04.txt": 0.0}[rel_path]
                await asyncio.sleep(delay)
                return await real_read(root_arg, rel_path, reader, meta=meta)

            with (
                patch.object(agentic_tools.settings, "llm_agentic_fs_ops_concurrency", 2),
                patch("app.llm.agentic.tools.search_text_paths_async", return_value=paths),
                patch("app.llm.agentic.tools._read_file_under_root_async", side_effect=_read_with_delay),
            ):
                result = await agentic._tool_search_text_async(
                    session,
                    1,
                    root,
                    {"query": "needle", "max_files": len(paths), "max_matches": 20, "context_chars": 80},
                    max_file_chars=5_000,
                    meta=agentic.AgenticMeta(),
                )

        self.assertTrue(result["ok"])
        data = result["data"]
        ordered_paths = [item["path"] for item in data["matches"]]
        self.assertEqual(ordered_paths, paths)

    async def test_search_text_contract_and_short_circuit_are_preserved(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = ["a.txt", "b.txt", "c.txt", "d.txt"]
            (root / "a.txt").write_text(("x" * 230) + "needle", encoding="utf-8")
            (root / "b.txt").write_text("needle\n", encoding="utf-8")
            (root / "c.txt").write_text("needle\n", encoding="utf-8")
            (root / "d.txt").write_text("needle\n", encoding="utf-8")

            session = _IndexedSession()
            with (
                patch.object(agentic_tools.settings, "llm_agentic_fs_ops_concurrency", 2),
                patch("app.llm.agentic.tools.search_text_paths_async", return_value=paths),
            ):
                result = await agentic._tool_search_text_async(
                    session,
                    1,
                    root,
                    {"query": "needle", "max_files": len(paths), "max_matches": 1, "context_chars": 80},
                    max_file_chars=200,
                    meta=agentic.AgenticMeta(),
                )

        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(
            set(data.keys()),
            {
                "query",
                "prefix",
                "case_sensitive",
                "max_files",
                "max_matches",
                "context_chars",
                "scan_max_chars_per_file",
                "scanned_files",
                "matched_files",
                "truncated_files",
                "matches",
            },
        )
        self.assertEqual(data["max_matches"], 1)
        self.assertEqual(len(data["matches"]), 1)
        self.assertGreaterEqual(data["truncated_files"], 1)
        self.assertLess(data["scanned_files"], len(paths))

    async def test_search_text_truncation_flags_and_scan_cap(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = ("x" * 240) + "needle-after-limit"
            (root / "truncate.txt").write_text(payload, encoding="utf-8")
            session = _IndexedSession()
            meta = agentic.AgenticMeta(
                fs_ops_semaphore=asyncio.Semaphore(2),
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
        self.assertEqual(len(data["matches"]), 1)
        self.assertEqual(data["matches"][0]["path"], "truncate.txt")
        self.assertEqual(data["matched_files"], 1)


if __name__ == "__main__":
    unittest.main()
