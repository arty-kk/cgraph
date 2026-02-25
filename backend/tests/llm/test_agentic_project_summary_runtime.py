from __future__ import annotations

import asyncio
import ast
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic
from app.llm.agentic import tools as agentic_tools
from app.infra import cpu_runtime


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _SummarySession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _Rows(self._rows)


def _slow_summary_facts(nodes):
    time.sleep(0.04)
    return {
        "counts": {"files": len(nodes), "loc": 10},
        "hotspots": [{"path": "a.py", "risk": 1.0}],
        "hubs_by_fan_in": [{"path": "a.py", "fan_in": 2}],
        "module_map": [{"module": "a", "files": 1, "loc": 10}],
        "hotspots_truncated": False,
        "hubs_by_fan_in_truncated": False,
        "module_map_truncated": False,
    }


class TestAgenticProjectSummaryRuntime(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await cpu_runtime.close_cpu_runtime()

    async def test_project_summary_uses_cpu_runtime_without_asyncio_to_thread(self) -> None:
        rows = [("a.py", "py", 10, 3, 2, 1, "ok")]
        session = _SummarySession(rows)

        expected_summary = {
            "counts": {"files": 1, "loc": 10},
            "hotspots": [{"path": "a.py", "risk": 1.0}],
            "hubs_by_fan_in": [{"path": "a.py", "fan_in": 2}],
            "module_map": [{"module": "a", "files": 1, "loc": 10}],
            "hotspots_truncated": False,
            "hubs_by_fan_in_truncated": True,
            "module_map_truncated": False,
        }

        async def _fake_cpu_runtime(fn, *args, operation=None, **kwargs):
            self.assertIs(fn, agentic_tools._compute_project_summary_facts)
            self.assertEqual(operation, "agentic.project_summary.compute_facts")
            self.assertEqual(kwargs, {})
            self.assertEqual(args[0], rows)
            return expected_summary

        async def _forbid_to_thread(*_args, **_kwargs):
            raise AssertionError("_tool_project_summary_async must not use asyncio.to_thread")

        with (
            patch("app.llm.agentic.tools.run_cpu_io_async", side_effect=_fake_cpu_runtime),
            patch("app.llm.agentic.tools.asyncio.to_thread", side_effect=_forbid_to_thread),
        ):
            result = await agentic._tool_project_summary_async(session, 1, Path("."), {})

        self.assertTrue(result["ok"])
        payload = result["data"]
        self.assertEqual(
            sorted(payload.keys()),
            ["counts", "hotspots", "hubs_by_fan_in", "module_map", "truncation"],
        )
        self.assertEqual(payload["counts"], expected_summary["counts"])
        self.assertEqual(payload["hotspots"], expected_summary["hotspots"])
        self.assertEqual(payload["hubs_by_fan_in"], expected_summary["hubs_by_fan_in"])
        self.assertEqual(payload["module_map"], expected_summary["module_map"])
        self.assertEqual(
            payload["truncation"],
            {
                "hotspots": False,
                "hubs_by_fan_in": True,
                "module_map": False,
            },
        )

    async def test_project_summary_parallel_calls_respect_cpu_runtime_concurrency(self) -> None:
        rows = [("a.py", "py", 10, 3, 2, 1, "ok")]
        session = _SummarySession(rows)

        with (
            patch.object(agentic_tools, "_compute_project_summary_facts", _slow_summary_facts),
            patch.object(cpu_runtime.settings, "cpu_runtime_max_workers", 2),
            patch.object(cpu_runtime.settings, "cpu_runtime_max_concurrency", 2),
        ):
            await cpu_runtime.close_cpu_runtime()
            results = await asyncio.gather(
                *[
                    agentic._tool_project_summary_async(session, 1, Path("."), {})
                    for _ in range(10)
                ]
            )
            runtime = await cpu_runtime._get_cpu_runtime()

        self.assertTrue(all(item["ok"] for item in results))
        self.assertLessEqual(runtime.peak_in_flight, 2)
        self.assertGreaterEqual(runtime.peak_in_flight, 1)
        self.assertGreater(runtime.peak_queue_depth, 0)

    async def test_project_summary_burst_stays_bounded_and_has_no_to_thread_path(self) -> None:
        rows = [("a.py", "py", 10, 3, 2, 1, "ok")]
        session = _SummarySession(rows)

        tools_src = (Path(__file__).resolve().parents[2] / "app/llm/agentic/tools.py").read_text(
            encoding="utf-8"
        )
        module = ast.parse(tools_src)
        fn = next(
            node for node in module.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_tool_project_summary_async"
        )
        for call in [node for node in ast.walk(fn) if isinstance(node, ast.Call)]:
            if (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "asyncio"
                and call.func.attr == "to_thread"
            ):
                self.fail("_tool_project_summary_async contains asyncio.to_thread")

        with (
            patch.object(agentic_tools, "_compute_project_summary_facts", _slow_summary_facts),
            patch.object(cpu_runtime.settings, "cpu_runtime_max_workers", 3),
            patch.object(cpu_runtime.settings, "cpu_runtime_max_concurrency", 3),
        ):
            await cpu_runtime.close_cpu_runtime()
            start = time.perf_counter()
            results = await asyncio.wait_for(
                asyncio.gather(
                    *[
                        agentic._tool_project_summary_async(session, 1, Path("."), {})
                        for _ in range(30)
                    ]
                ),
                timeout=20,
            )
            elapsed = time.perf_counter() - start
            runtime = await cpu_runtime._get_cpu_runtime()

        self.assertLess(elapsed, 20)
        self.assertEqual(len(results), 30)
        self.assertTrue(all(item["ok"] for item in results))
        self.assertLessEqual(runtime.peak_in_flight, 3)
        self.assertGreater(runtime.peak_queue_depth, 0)


if __name__ == "__main__":
    unittest.main()
