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


class _PoolTracker:
    def __init__(self, pool_limit: int) -> None:
        self.pool_limit = pool_limit
        self.sem = asyncio.Semaphore(pool_limit)
        self.lock = asyncio.Lock()
        self.active = 0
        self.max_active = 0
        self.per_call_sessions: dict[int, set[int]] = {}

    async def execute(self, call_id: int, session_id: int) -> _EmptyResult:
        async with self.sem:
            async with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                self.per_call_sessions.setdefault(call_id, set()).add(session_id)
            try:
                await asyncio.sleep(0.01)
                return _EmptyResult()
            finally:
                async with self.lock:
                    self.active -= 1


class _TrackedSession:
    def __init__(self, tracker: _PoolTracker, call_id: int, session_id: int) -> None:
        self._tracker = tracker
        self._call_id = call_id
        self._session_id = session_id

    async def execute(self, _query, _params=None):
        return await self._tracker.execute(self._call_id, self._session_id)


class TestAgenticSeedContextConcurrencyRuntime(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        agentic_context._SEED_FS_SEMAPHORE = None
        agentic_context._SEED_FS_SEMAPHORE_LOOP = None
        agentic_context._SEED_FS_SEMAPHORE_LOCK = None
        agentic_context._SEED_FS_SEMAPHORE_LOCK_LOOP = None

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

    async def test_seed_context_performs_db_branches_sequentially_on_one_session(self) -> None:
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

        self.assertGreater(elapsed, 0.65)
        self.assertEqual(seed["graph_hint"]["outbound"], ["out"])
        self.assertEqual(seed["graph_hint"]["inbound"], ["in"])

    async def test_seed_context_does_not_open_local_async_session_factory(self) -> None:
        async def _forbidden_local_session_factory(*_args, **_kwargs):
            raise AssertionError("seed_context must not open AsyncSessionLocal")

        with patch(
            "app.llm.agentic.context.AsyncSessionLocal",
            side_effect=_forbidden_local_session_factory,
            create=True,
        ):
            seed = await agentic._seed_context_async(
                _SessionStub(),
                1,
                Path("."),
                "f0.txt",
                depth=1,
                max_file_chars=200,
            )

        self.assertIn("target_path", seed)

    async def test_seed_context_concurrent_calls_use_single_external_session_per_call(self) -> None:
        tracker = _PoolTracker(pool_limit=2)

        async def _contract(session, _project_id, _root, _target_norm):
            await session.execute("SELECT 1")
            return {"kind": "contract"}

        async def _neighbors(session, _project_id, _target_norm, _depth):
            await session.execute("SELECT 1")
            return ["n"]

        async def _node(session, _project_id, _target_norm):
            await session.execute("SELECT 1")
            return {"path": "f0.txt"}

        async def _api(session, _project_id, _target_norm):
            await session.execute("SELECT 1")
            return ([], [])

        async def _run_once(call_id: int) -> dict:
            session = _TrackedSession(tracker, call_id=call_id, session_id=10_000 + call_id)
            return await agentic._seed_context_async(
                session,
                1,
                Path("."),
                "f0.txt",
                depth=2,
                max_file_chars=200,
            )

        with (
            patch("app.llm.agentic.context._run_seed_fs_io_async", return_value=("f0.txt", "")),
            patch("app.llm.agentic.context._load_contract_async", side_effect=_contract),
            patch("app.llm.agentic.context._load_target_node_metrics_async", side_effect=_node),
            patch("app.llm.agentic.context._load_api_hints_async", side_effect=_api),
            patch("app.llm.agentic.context._load_outbound_hint_async", side_effect=_neighbors),
            patch("app.llm.agentic.context._load_inbound_hint_async", side_effect=_neighbors),
        ):
            rows = await asyncio.gather(*[_run_once(i) for i in range(12)])

        self.assertEqual(len(rows), 12)
        self.assertLessEqual(tracker.max_active, tracker.pool_limit)
        self.assertEqual(len(tracker.per_call_sessions), 12)
        self.assertTrue(all(len(sessions) == 1 for sessions in tracker.per_call_sessions.values()))

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
