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
from app.llm.agentic import context as agentic_context


class _EmptyResult:
    def all(self):
        return []

    def scalars(self):
        return self

    def first(self):
        return None


class _SessionStub:
    async def execute(self, _query, _params=None):
        return _EmptyResult()


class TestAgenticSeedContextConcurrencyRuntime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        agentic_context._SEED_FS_SEMAPHORE = None

    async def test_seed_context_keeps_event_loop_responsive_under_parallel_load(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for idx in range(24):
                (root / f"f{idx}.txt").write_text(("line\n" * 300), encoding="utf-8")

            stop = asyncio.Event()
            ticks = 0

            async def _heartbeat() -> None:
                nonlocal ticks
                while not stop.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)

            async def _run_once(i: int) -> dict:
                return await agentic._seed_context_async(
                    _SessionStub(),
                    1,
                    root,
                    f"f{i % 24}.txt",
                    depth=1,
                    max_file_chars=2_000,
                )

            hb_task = asyncio.create_task(_heartbeat())
            started = time.perf_counter()
            try:
                rows = await asyncio.wait_for(
                    asyncio.gather(*[_run_once(i) for i in range(120)]),
                    timeout=12,
                )
            finally:
                stop.set()
                await hb_task
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 12)
        self.assertGreater(ticks, 5)
        self.assertEqual(len(rows), 120)

    async def test_seed_context_fs_ops_respect_runtime_limit(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for idx in range(12):
                (root / f"f{idx}.txt").write_text("x" * 500, encoding="utf-8")

            limit = max(1, int(agentic_context.settings.llm_agentic_fs_ops_concurrency))
            in_flight = 0
            max_in_flight = 0
            lock = asyncio.Lock()
            original_run_fs = agentic_context.run_fs_io_async

            async def _instrumented_run_fs_io_async(fn, *args, operation=None, **kwargs):
                nonlocal in_flight, max_in_flight
                async with lock:
                    in_flight += 1
                    max_in_flight = max(max_in_flight, in_flight)
                try:
                    await asyncio.sleep(0.01)
                    return await original_run_fs(fn, *args, operation=operation, **kwargs)
                finally:
                    async with lock:
                        in_flight -= 1

            async def _run_once(i: int) -> dict:
                return await agentic._seed_context_async(
                    _SessionStub(),
                    1,
                    root,
                    f"f{i % 12}.txt",
                    depth=1,
                    max_file_chars=200,
                )

            with patch("app.llm.agentic.context.run_fs_io_async", side_effect=_instrumented_run_fs_io_async):
                await asyncio.wait_for(
                    asyncio.gather(*[_run_once(i) for i in range(80)]),
                    timeout=12,
                )

        self.assertLessEqual(max_in_flight, limit)


    async def test_seed_context_runs_independent_branches_concurrently(self) -> None:
        async def _slow_contract(*_args, **_kwargs):
            await asyncio.sleep(0.16)
            return {"kind": "contract"}

        async def _slow_node(*_args, **_kwargs):
            await asyncio.sleep(0.09)
            return {"path": "f0.txt"}

        async def _slow_api(*_args, **_kwargs):
            await asyncio.sleep(0.13)
            return ([{"path": "/r"}], [{"path": "/c"}])

        async def _slow_outbound(*_args, **_kwargs):
            await asyncio.sleep(0.2)
            return ["out"]

        async def _slow_inbound(*_args, **_kwargs):
            await asyncio.sleep(0.18)
            return ["in"]

        with (
            patch("app.llm.agentic.context._run_seed_fs_io_async", return_value=("f0.txt", "")),
            patch("app.llm.agentic.context._load_contract_async", side_effect=_slow_contract),
            patch("app.llm.agentic.context._load_target_node_metrics_async", side_effect=_slow_node),
            patch("app.llm.agentic.context._load_api_hints_async", side_effect=_slow_api),
            patch("app.llm.agentic.context._load_outbound_hint_async", side_effect=_slow_outbound),
            patch("app.llm.agentic.context._load_inbound_hint_async", side_effect=_slow_inbound),
        ):
            started = time.perf_counter()
            seed = await agentic._seed_context_async(
                _SessionStub(),
                1,
                Path("."),
                "f0.txt",
                depth=2,
                max_file_chars=200,
            )
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.35)
        self.assertEqual(seed["graph_hint"]["outbound"], ["out"])
        self.assertEqual(seed["graph_hint"]["inbound"], ["in"])

    async def test_seed_context_preserves_shape_with_partial_parallel_failures(self) -> None:
        async def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        with (
            patch("app.llm.agentic.context._run_seed_fs_io_async", return_value=("f0.txt", "payload")),
            patch("app.llm.agentic.context._load_contract_async", side_effect=_boom),
            patch("app.llm.agentic.context._load_target_node_metrics_async", side_effect=_boom),
            patch("app.llm.agentic.context._load_api_hints_async", side_effect=_boom),
            patch("app.llm.agentic.context._load_outbound_hint_async", return_value=[]),
            patch("app.llm.agentic.context._load_inbound_hint_async", return_value=[]),
        ):
            seed = await agentic._seed_context_async(
                _SessionStub(),
                1,
                Path("."),
                "f0.txt",
                depth=3,
                max_file_chars=200,
            )

        self.assertEqual(
            set(seed.keys()),
            {"target_path", "target_file", "target_contract", "target_node", "api_hint", "graph_hint"},
        )
        self.assertEqual(seed["target_contract"], {})
        self.assertEqual(seed["target_node"], {})
        self.assertEqual(seed["api_hint"]["routes_in_file"], [])
        self.assertEqual(seed["api_hint"]["calls_in_file"], [])
        self.assertEqual(
            seed["api_hint"]["note"],
            "Use search_routes/search_api_calls/route_usages for project-wide API mapping.",
        )
        self.assertEqual(
            seed["graph_hint"]["note"],
            "Lists are truncated hints. Use get_neighbors() to expand.",
        )

    async def test_seed_context_handles_missing_and_oversized_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "big.txt").write_text("a" * 10_000, encoding="utf-8")

            missing = await agentic._seed_context_async(
                _SessionStub(),
                1,
                root,
                "missing.txt",
                depth=1,
                max_file_chars=100,
            )
            big = await agentic._seed_context_async(
                _SessionStub(),
                1,
                root,
                "big.txt",
                depth=1,
                max_file_chars=128,
            )

        self.assertEqual(missing["target_path"], "missing.txt")
        self.assertEqual(missing["target_file"]["content"], "")
        self.assertEqual(big["target_path"], "big.txt")
        self.assertEqual(len(big["target_file"]["content"]), 128)


if __name__ == "__main__":
    unittest.main()
