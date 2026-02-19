from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic


class TestAgenticFileToolsConcurrencyRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_file_tools_remain_responsive(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for idx in range(20):
                (root / f"f{idx}.txt").write_text((f"line-{idx}\n" * 100), encoding="utf-8")

            meta = agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(4))
            stop = asyncio.Event()
            ticks = 0

            async def _heartbeat() -> None:
                nonlocal ticks
                while not stop.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)

            async def _run_get_file(idx: int) -> dict:
                return await agentic._tool_get_file_async(
                    1,
                    root,
                    meta,
                    {"path": f"f{idx % 20}.txt", "max_chars": 400},
                    max_file_chars=1000,
                )

            async def _run_get_file_lines(idx: int) -> dict:
                return await agentic._tool_get_file_lines_async(
                    1,
                    root,
                    meta,
                    {
                        "path": f"f{idx % 20}.txt",
                        "start_line": 2,
                        "end_line": 8,
                        "max_chars": 300,
                    },
                    max_file_chars=1000,
                )

            hb_task = asyncio.create_task(_heartbeat())
            started = time.perf_counter()
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(
                        *[_run_get_file(i) for i in range(80)],
                        *[_run_get_file_lines(i) for i in range(80)],
                    ),
                    timeout=10,
                )
            finally:
                stop.set()
                await hb_task
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 10)
        self.assertGreater(ticks, 5, "event loop heartbeat must progress during file tool load")
        self.assertEqual(len(results), 160)
        for item in results:
            self.assertTrue(item["ok"])
            self.assertIsNone(item["error"])
            self.assertIn("path", item["data"])


if __name__ == "__main__":
    unittest.main()
