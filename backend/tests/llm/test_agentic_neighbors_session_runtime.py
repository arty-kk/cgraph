from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _SessionOk:
    def __init__(self):
        self.execute_calls = 0

    async def execute(self, _query):
        self.execute_calls += 1
        return _Rows([("deps/a.py",), ("deps/b.py",)])


class _SessionError:
    def __init__(self):
        self.execute_calls = 0

    async def execute(self, _query):
        self.execute_calls += 1
        raise RuntimeError("db failed")


class _ManagedFailingSession(_SessionError):
    def __init__(self):
        super().__init__()
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *_exc):
        self.exited = True
        return False


class _ConcurrencySession:
    def __init__(self):
        self.execute_calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = asyncio.Lock()

    async def execute(self, _query):
        async with self._lock:
            self.execute_calls += 1
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        async with self._lock:
            self.in_flight -= 1
        return _Rows([("deps/c.py",)])


class TestAgenticNeighborsSessionRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_get_neighbors_uses_external_session_without_local_factory(self) -> None:
        meta = agentic.AgenticMeta(tool_trace=[{"name": "plan_retrieval", "status": "ok"}])
        session = _SessionOk()
        local_factory_calls = 0

        def _forbidden_local_session_factory(*_args, **_kwargs):
            nonlocal local_factory_calls
            local_factory_calls += 1
            raise AssertionError("AsyncSessionLocal must not be used on get_neighbors hot-path")

        with patch("app.llm.agentic.tools.AsyncSessionLocal", side_effect=_forbidden_local_session_factory):
            result = await agentic._dispatch_tool_async(
                session,
                1,
                Path("."),
                meta,
                "get_neighbors",
                {"path": "backend/app", "direction": "out", "depth": 1, "limit": 10},
                max_file_chars=200,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["neighbors"], ["deps/a.py", "deps/b.py"])
        self.assertEqual(local_factory_calls, 0)
        self.assertEqual(session.execute_calls, 1)

    async def test_dispatch_get_neighbors_error_keeps_external_session_cleanup(self) -> None:
        meta = agentic.AgenticMeta(tool_trace=[{"name": "plan_retrieval", "status": "ok"}])

        def _forbidden_local_session_factory(*_args, **_kwargs):
            raise AssertionError("AsyncSessionLocal fallback must not be used with external session")

        managed = _ManagedFailingSession()
        with patch("app.llm.agentic.tools.AsyncSessionLocal", side_effect=_forbidden_local_session_factory):
            with self.assertRaisesRegex(RuntimeError, "db failed"):
                async with managed as session:
                    await agentic._dispatch_tool_async(
                        session,
                        1,
                        Path("."),
                        meta,
                        "get_neighbors",
                        {"path": "backend/app", "direction": "in", "depth": 1, "limit": 10},
                        max_file_chars=200,
                    )

        self.assertTrue(managed.entered)
        self.assertTrue(managed.exited)
        self.assertEqual(managed.execute_calls, 1)

    async def test_dispatch_get_neighbors_high_concurrency_does_not_create_extra_sessions(self) -> None:
        local_factory_calls = 0

        def _counting_local_session_factory(*_args, **_kwargs):
            nonlocal local_factory_calls
            local_factory_calls += 1
            raise AssertionError("AsyncSessionLocal must not be used in concurrent get_neighbors path")

        session = _ConcurrencySession()

        async def _run_once() -> None:
            meta = agentic.AgenticMeta(tool_trace=[{"name": "plan_retrieval", "status": "ok"}])
            out = await agentic._dispatch_tool_async(
                session,
                1,
                Path("."),
                meta,
                "get_neighbors",
                {"path": "backend/app", "direction": "out", "depth": 1, "limit": 10},
                max_file_chars=200,
            )
            self.assertTrue(out["ok"])

        with patch("app.llm.agentic.tools.AsyncSessionLocal", side_effect=_counting_local_session_factory):
            await asyncio.gather(*[_run_once() for _ in range(25)])

        self.assertEqual(local_factory_calls, 0)
        self.assertEqual(session.execute_calls, 25)
        self.assertGreaterEqual(session.max_in_flight, 2)


if __name__ == "__main__":
    unittest.main()
