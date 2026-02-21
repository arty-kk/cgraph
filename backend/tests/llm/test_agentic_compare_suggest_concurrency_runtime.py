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


class _FakeExecResult:
    def __init__(self, row=None):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def first(self):
        return self._row

    def scalars(self):
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self, row=None):
        self._row = row

    async def execute(self, *_args, **_kwargs):
        return _FakeExecResult(self._row)


class _FakeSessionFactory:
    def __init__(self, row=None):
        self._row = row

    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeSession(self._row)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestAgenticCompareSuggestConcurrencyRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_compare_contract_runtime_remains_responsive(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend_route.py").write_text(
                "def handler():\n    return {'ok': True}\n",
                encoding="utf-8",
            )

            async def _fake_route_usages(_project_id: int, _args: dict) -> dict:
                await asyncio.sleep(0.01)
                return agentic._tool_ok(
                    {
                        "routes": [
                            {
                                "route": {
                                    "method": "GET",
                                    "path": "/api/test",
                                    "source_path": "backend_route.py",
                                    "handler_name": "handler",
                                    "lineno": 1,
                                },
                                "matches": [],
                                "resolved_full_paths": ["/api/test"],
                            }
                        ]
                    }
                )

            stop = asyncio.Event()
            ticks = 0

            async def _heartbeat() -> None:
                nonlocal ticks
                while not stop.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)


            async def _fake_load_type_defs(
                _session, _project_id: int, _type_names: list[str], cache=None
            ) -> dict[str, dict]:
                _ = cache
                await asyncio.sleep(0)
                return {}

            async def _run_compare() -> dict:
                return await agentic._tool_compare_api_contract_async(
                    _FakeSession(),
                    1,
                    root,
                    {"path": "/api/test", "method": "GET", "route_limit": 1, "call_limit": 1},
                )

            with (
                patch("app.llm.agentic.tools._tool_route_usages", side_effect=_fake_route_usages),
                patch("app.llm.agentic.tools.AsyncSessionLocal", new=_FakeSessionFactory()),
                patch("app.llm.agentic.tools._load_ts_typedefs_by_name", side_effect=_fake_load_type_defs),
            ):
                hb_task = asyncio.create_task(_heartbeat())
                started = time.perf_counter()
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*[_run_compare() for _ in range(40)]), timeout=10
                    )
                finally:
                    stop.set()
                    await hb_task
                elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 10)
        self.assertGreater(ticks, 2, "event loop heartbeat must progress during compare load")
        self.assertEqual(len(results), 40)
        for item in results:
            self.assertTrue(item["ok"])
            self.assertIsNone(item["error"])

    async def test_suggest_tools_runtime_remain_responsive(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "frontend.ts").write_text(
                "export const getItem = (itemId: number) => apiGet('/api/items/{item_id}')\n",
                encoding="utf-8",
            )
            (root / "types.ts").write_text("export type Resp = { id: number }\n", encoding="utf-8")

            compare_report = {
                "routes": [
                    {
                        "route": {
                            "method": "GET",
                            "path": "/api/items/{item_id}",
                            "source_path": "backend_route.py",
                            "handler_name": "handler",
                            "lineno": 1,
                        },
                        "resolved_full_paths": ["/api/items/{item_id}"],
                        "frontend_calls": [
                            {
                                "call": {
                                    "method": "GET",
                                    "path": "/api/items/{item_id}",
                                    "source_path": "frontend.ts",
                                    "lineno": 1,
                                },
                                "meta": {
                                    "wrapper_name": "getItem",
                                    "wrapper_body_type": "",
                                    "wrapper_response_type": "Resp",
                                },
                                "comparison": {
                                    "path_params_missing_in_wrapper": [],
                                    "body": {
                                        "missing_in_frontend": [],
                                        "backend_fields": [],
                                    },
                                    "response": {
                                        "missing_in_frontend": ["name"],
                                        "extra_in_frontend": [],
                                    },
                                },
                            }
                        ],
                    }
                ]
            }

            class _FakeTsTypeDef:
                source_path = "types.ts"
                fields_json = '[{"name": "id", "type": "number"}]'

            async def _fake_compare(_session, _project_id: int, _root: Path, _args: dict, *, meta=None) -> dict:
                await asyncio.sleep(0.01)
                return agentic._tool_ok(compare_report)

            async def _fake_load_type_defs(
                _session, _project_id: int, _type_names: list[str], cache=None
            ) -> dict[str, dict]:
                _ = cache
                await asyncio.sleep(0)
                return {}

            stop = asyncio.Event()
            ticks = 0

            async def _heartbeat() -> None:
                nonlocal ticks
                while not stop.is_set():
                    ticks += 1
                    await asyncio.sleep(0.005)

            async def _run_suggest_contract(meta: agentic.AgenticMeta) -> dict:
                return await agentic._tool_suggest_contract_fix_async(
                    _FakeSession(_FakeTsTypeDef()),
                    1,
                    root,
                    meta,
                    {"path": "/api/items/{item_id}", "method": "GET"},
                )

            async def _run_suggest_api(meta: agentic.AgenticMeta) -> dict:
                return await agentic._tool_suggest_api_fix_async(
                    _FakeSession(_FakeTsTypeDef()),
                    1,
                    root,
                    meta,
                    {"path": "/api/items/{item_id}", "method": "GET"},
                )

            with (
                patch("app.llm.agentic.tools._tool_compare_api_contract", side_effect=_fake_compare),
                patch("app.llm.agentic.tools.AsyncSessionLocal", new=_FakeSessionFactory(_FakeTsTypeDef())),
                patch("app.llm.agentic.tools._load_ts_typedefs_by_name", side_effect=_fake_load_type_defs),
                patch("app.llm.agentic.tools.ts_add_fields_to_typedef", return_value=("", False, "ok")),
                patch("app.llm.agentic.tools.ts_patch_wrapper_function", return_value=("", False, [])),
                patch("app.llm.agentic.tools.py_add_keys_to_function_return_dicts", return_value=("", False, [])),
            ):
                hb_task = asyncio.create_task(_heartbeat())
                started = time.perf_counter()
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(
                            *[
                                _run_suggest_contract(agentic.AgenticMeta())
                                for _ in range(20)
                            ],
                            *[_run_suggest_api(agentic.AgenticMeta()) for _ in range(20)],
                        ),
                        timeout=10,
                    )
                finally:
                    stop.set()
                    await hb_task
                elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 10)
        self.assertGreater(ticks, 2, "event loop heartbeat must progress during suggest load")
        self.assertEqual(len(results), 40)
        for item in results:
            self.assertTrue(item["ok"])
            self.assertIsNone(item["error"])


if __name__ == "__main__":
    unittest.main()
