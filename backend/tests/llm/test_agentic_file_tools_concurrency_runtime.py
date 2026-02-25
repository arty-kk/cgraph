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


class _FakeExecResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    async def execute(self, *_args, **_kwargs):
        return _FakeExecResult()


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

    async def test_fallback_fs_limiter_bounds_parallelism_without_meta(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for idx in range(10):
                (root / f"f{idx}.txt").write_text(f"line-{idx}\n" * 40, encoding="utf-8")

            in_flight = 0
            peak = 0
            lock = asyncio.Lock()
            real_runner = agentic_tools.run_fs_io_async

            async def _tracked_runner(fn, *args, operation: str):
                nonlocal in_flight, peak
                async with lock:
                    in_flight += 1
                    peak = max(peak, in_flight)
                await asyncio.sleep(0.01)
                try:
                    return await real_runner(fn, *args, operation=operation)
                finally:
                    async with lock:
                        in_flight -= 1

            agentic_tools._FS_OPS_FALLBACK_SEMAPHORE = None
            with (
                patch.object(agentic_tools.settings, "llm_agentic_fs_ops_concurrency", 3),
                patch("app.llm.agentic.tools.run_fs_io_async", side_effect=_tracked_runner),
            ):
                results = await asyncio.gather(
                    *[
                        agentic_tools._read_text_under_root_async(
                            root,
                            f"f{i % 10}.txt",
                            meta=None,
                        )
                        for i in range(40)
                    ]
                )

        self.assertTrue(all(item is not None for item in results))
        self.assertLessEqual(peak, 3)

    async def test_compare_api_contract_route_build_respects_shared_fs_limit(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            routes = []
            for idx in range(16):
                src = f"route_{idx}.py"
                (root / src).write_text("def handler():\n    return {'ok': True}\n", encoding="utf-8")
                routes.append(
                    {
                        "route": {
                            "method": "GET",
                            "path": f"/api/r/{idx}",
                            "source_path": src,
                            "handler_name": "handler",
                            "lineno": 1,
                        },
                        "matches": [],
                        "resolved_full_paths": [f"/api/r/{idx}"],
                    }
                )

            async def _fake_route_usages(_session, _project_id: int, _args: dict) -> dict:
                return agentic._tool_ok({"routes": routes})

            in_flight = 0
            peak = 0
            lock = asyncio.Lock()
            real_runner = agentic_tools.run_fs_io_async

            async def _tracked_runner(fn, *args, operation: str):
                nonlocal in_flight, peak
                async with lock:
                    in_flight += 1
                    peak = max(peak, in_flight)
                await asyncio.sleep(0.01)
                try:
                    return await real_runner(fn, *args, operation=operation)
                finally:
                    async with lock:
                        in_flight -= 1

            agentic_tools._FS_OPS_FALLBACK_SEMAPHORE = None
            with (
                patch.object(agentic_tools.settings, "llm_agentic_fs_ops_concurrency", 4),
                patch("app.llm.agentic.tools._tool_route_usages_async", side_effect=_fake_route_usages),
                patch("app.llm.agentic.tools.run_fs_io_async", side_effect=_tracked_runner),
                patch("app.llm.agentic.tools._load_ts_typedefs_by_name", return_value={}),
            ):
                results = await asyncio.gather(
                    *[
                        agentic_tools._tool_compare_api_contract_async(
                            _FakeSession(),
                            1,
                            root,
                            {"path": "/api/r", "method": "GET", "route_limit": 16, "call_limit": 1},
                        )
                        for _ in range(12)
                    ]
                )

        self.assertTrue(all(item.get("ok") for item in results))
        self.assertLessEqual(peak, 4)


if __name__ == "__main__":
    unittest.main()
