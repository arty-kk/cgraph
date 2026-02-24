from __future__ import annotations

import asyncio
import sys
import time
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


class TestAgenticSearchTextConcurrencyRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_search_text_cpu_work_does_not_block_event_loop(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for idx in range(6):
                (root / f"file_{idx}.txt").write_text("needle\n" * 500, encoding="utf-8")

            session = _IndexedSession()
            meta = agentic.AgenticMeta(
                fs_ops_semaphore=asyncio.Semaphore(6),
            )
            stop = asyncio.Event()
            ticks = 0

            async def _heartbeat() -> None:
                nonlocal ticks
                while not stop.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)

            original_cpu = agentic_tools._search_text_cpu

            def _slow_cpu(**kwargs):
                time.sleep(0.03)
                return original_cpu(**kwargs)

            async def _run_once() -> dict:
                return await agentic._tool_search_text_async(
                    session,
                    1,
                    root,
                    {"query": "needle", "max_files": 6, "max_matches": 30, "context_chars": 80},
                    max_file_chars=4_000,
                    meta=meta,
                )

            with patch("app.llm.agentic.tools.search_text_paths_async", return_value=[f"file_{i}.txt" for i in range(6)]), patch(
                "app.llm.agentic.tools._search_text_cpu", side_effect=_slow_cpu
            ):
                hb_task = asyncio.create_task(_heartbeat())
                started = time.perf_counter()
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*[_run_once() for _ in range(6)]),
                        timeout=12,
                    )
                finally:
                    stop.set()
                    await hb_task
                elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 12)
        self.assertGreater(ticks, 5)
        for result in results:
            self.assertTrue(result["ok"])
            self.assertLessEqual(len(result["data"]["matches"]), 30)


if __name__ == "__main__":
    unittest.main()
