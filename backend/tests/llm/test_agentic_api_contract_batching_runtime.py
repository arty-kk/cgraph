from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic
from app.llm.agentic import tools as agentic_tools


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _build_route_usages_payload(route_count: int, calls_per_route: int) -> dict:
    routes = []
    for ridx in range(route_count):
        method = "GET"
        path = f"/api/items/{ridx}"
        route = {
            "method": method,
            "path": path,
            "source_path": f"backend/app/api/routes_{ridx}.py",
            "handler_name": f"handler_{ridx}",
            "lineno": ridx + 1,
        }
        matches = []
        for cidx in range(calls_per_route):
            matches.append(
                {
                    "method": method,
                    "path": path,
                    "source_path": f"frontend/src/api/client_{ridx}_{cidx}.ts",
                    "lineno": cidx + 10,
                    "client": "fetch",
                }
            )
        routes.append({"route": route, "matches": matches, "resolved_full_paths": [path]})
    return {"ok": True, "data": {"routes": routes}}


class _BatchSession:
    def __init__(self, route_payload: dict, sleep_s: float = 0.0, include_typedefs: bool = True):
        self.route_payload = route_payload
        self.sleep_s = sleep_s
        self.query_counts = {"route_contract": 0, "call_meta": 0, "typedef": 0}

        self._route_rows = []
        self._meta_rows = []
        for item in route_payload["data"]["routes"]:
            route = item["route"]
            contract = {
                "path_params": [],
                "body": {"type_name": "ReqDto", "model": {"fields": [{"name": "name"}]}},
                "response": {"keys": ["id", "name"]},
            }
            self._route_rows.append(
                SimpleNamespace(
                    project_id=1,
                    method=route["method"],
                    path=route["path"],
                    source_path=route["source_path"],
                    handler_name=route["handler_name"],
                    lineno=route["lineno"],
                    contract_json=json.dumps(contract),
                )
            )
            for match in item["matches"]:
                self._meta_rows.append(
                    SimpleNamespace(
                        project_id=1,
                        method=match["method"],
                        path=match["path"],
                        source_path=match["source_path"],
                        lineno=match["lineno"],
                        wrapper_name="apiCall",
                        wrapper_response_type="RespDto",
                        wrapper_body_type="ReqDto",
                        wrapper_params_json="[]",
                        body_keys_json='["name"]',
                    )
                )

        self._typedef_rows = []
        if include_typedefs:
            self._typedef_rows = [
                SimpleNamespace(
                    project_id=1,
                    name="ReqDto",
                    kind="type",
                    source_path="frontend/src/types.ts",
                    fields_json='[{"name":"name","type":"string"}]',
                ),
                SimpleNamespace(
                    project_id=1,
                    name="RespDto",
                    kind="type",
                    source_path="frontend/src/types.ts",
                    fields_json='[{"name":"id","type":"number"},{"name":"name","type":"string"}]',
                ),
            ]

    async def execute(self, query):
        if self.sleep_s:
            await asyncio.sleep(self.sleep_s)
        sql = str(query)
        if "FROM apiroutecontract" in sql:
            self.query_counts["route_contract"] += 1
            return _ScalarRows(self._route_rows)
        if "FROM apicallmeta" in sql:
            self.query_counts["call_meta"] += 1
            return _ScalarRows(self._meta_rows)
        if "FROM tstypedef" in sql:
            self.query_counts["typedef"] += 1
            return _ScalarRows(self._typedef_rows)
        raise AssertionError(f"Unexpected query: {sql}")


class TestAgenticApiContractBatchingRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_compare_api_contract_uses_batch_queries(self) -> None:
        payload = _build_route_usages_payload(route_count=30, calls_per_route=15)
        session = _BatchSession(payload)

        with patch("app.llm.agentic.tools._tool_route_usages_async", return_value=payload):
            result = await agentic_tools._tool_compare_api_contract_async(
                session,
                1,
                Path("."),
                {"path": "/api/items", "method": "GET", "route_limit": 30, "call_limit": 15},
                meta=agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(4)),
            )

        self.assertTrue(result["ok"])
        expected_call_batches = (30 * 15 + 299) // 300
        self.assertEqual(session.query_counts["route_contract"], 1)
        self.assertEqual(session.query_counts["call_meta"], expected_call_batches)
        self.assertEqual(session.query_counts["typedef"], 1)


    async def test_compare_api_contract_caches_missing_typedef_lookups(self) -> None:
        payload = _build_route_usages_payload(route_count=10, calls_per_route=5)
        session = _BatchSession(payload, include_typedefs=False)

        with patch("app.llm.agentic.tools._tool_route_usages_async", return_value=payload):
            result = await agentic_tools._tool_compare_api_contract_async(
                session,
                1,
                Path("."),
                {"path": "/api/items", "method": "GET", "route_limit": 10, "call_limit": 5},
                meta=agentic.AgenticMeta(fs_ops_semaphore=asyncio.Semaphore(4)),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(session.query_counts["typedef"], 1)

    async def test_suggest_tools_do_not_add_per_item_queries(self) -> None:
        payload = _build_route_usages_payload(route_count=20, calls_per_route=10)

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "frontend/src").mkdir(parents=True, exist_ok=True)
            (root / "frontend/src/types.ts").write_text("export type X = {}\n", encoding="utf-8")

            session_api = _BatchSession(payload)
            meta_api = agentic.AgenticMeta(tool_trace=[{"name": "plan_retrieval", "status": "ok"}], fs_ops_semaphore=asyncio.Semaphore(4))
            with patch("app.llm.agentic.tools._tool_route_usages_async", return_value=payload):
                out_api = await agentic_tools._tool_suggest_api_fix_async(
                    session_api,
                    1,
                    root,
                    meta_api,
                    {
                        "path": "/api/items",
                        "method": "GET",
                        "route_limit": 20,
                        "call_limit": 10,
                        "include_backend_response": False,
                    },
                )
            self.assertTrue(out_api["ok"])
            self.assertEqual(sum(session_api.query_counts.values()), 4)

            session_contract = _BatchSession(payload)
            meta_contract = agentic.AgenticMeta(tool_trace=[{"name": "plan_retrieval", "status": "ok"}], fs_ops_semaphore=asyncio.Semaphore(4))
            with patch("app.llm.agentic.tools._tool_route_usages_async", return_value=payload):
                out_contract = await agentic_tools._tool_suggest_contract_fix_async(
                    session_contract,
                    1,
                    root,
                    meta_contract,
                    {
                        "path": "/api/items",
                        "method": "GET",
                        "route_limit": 20,
                        "call_limit": 10,
                    },
                )
            self.assertTrue(out_contract["ok"])
            self.assertEqual(sum(session_contract.query_counts.values()), 4)

    async def test_compare_api_contract_large_runtime_threshold(self) -> None:
        payload = _build_route_usages_payload(route_count=120, calls_per_route=25)
        session = _BatchSession(payload, sleep_s=0.005)
        meta = agentic.AgenticMeta(tool_trace=[{"name": "plan_retrieval", "status": "ok"}])

        started = time.perf_counter()
        with patch("app.llm.agentic.tools._tool_route_usages_async", return_value=payload):
            result = await agentic._dispatch_tool_async(
                session,
                1,
                Path("."),
                meta,
                "compare_api_contract",
                {"path": "/api/items", "method": "GET", "route_limit": 120, "call_limit": 25},
                max_file_chars=2000,
            )
        elapsed = time.perf_counter() - started

        self.assertTrue(result["ok"])
        self.assertLess(elapsed, 1.5)
        self.assertEqual(sum(session.query_counts.values()), 12)

    async def test_suggest_tools_use_single_typedef_batch_query_for_many_mismatches(self) -> None:
        report = {
            "ok": True,
            "data": {
                "routes": [
                    {
                        "route": {
                            "method": "POST",
                            "path": "/api/items",
                            "source_path": "backend/app/api/items.py",
                            "handler_name": "create_item",
                            "lineno": 11,
                        },
                        "frontend_calls": [
                            {
                                "call": {
                                    "source_path": "frontend/src/api/client_1.ts",
                                    "lineno": 10,
                                    "method": "POST",
                                    "path": "/api/items",
                                },
                                "meta": {
                                    "wrapper_name": "callApi",
                                    "wrapper_body_type": "MissingReqDto",
                                    "wrapper_response_type": "MissingRespDto",
                                },
                                "comparison": {
                                    "body": {
                                        "missing_in_frontend": ["name", "qty"],
                                        "backend_fields": [{"name": "name"}, {"name": "qty"}],
                                    },
                                    "response": {
                                        "missing_in_frontend": ["id", "status"],
                                    },
                                },
                            },
                            {
                                "call": {
                                    "source_path": "frontend/src/api/client_2.ts",
                                    "lineno": 20,
                                    "method": "POST",
                                    "path": "/api/items",
                                },
                                "meta": {
                                    "wrapper_name": "callApi",
                                    "wrapper_body_type": "MissingReqDto",
                                    "wrapper_response_type": "MissingRespDto",
                                },
                                "comparison": {
                                    "body": {
                                        "missing_in_frontend": ["price"],
                                        "backend_fields": [{"name": "price"}],
                                    },
                                    "response": {
                                        "missing_in_frontend": ["createdAt"],
                                    },
                                },
                            },
                        ],
                    }
                ]
            },
        }

        class _TypedefOnlySession:
            def __init__(self) -> None:
                self.typedef_queries = 0

            async def execute(self, query):
                sql = str(query)
                if "FROM tstypedef" not in sql:
                    raise AssertionError(f"Unexpected query: {sql}")
                self.typedef_queries += 1
                return _ScalarRows([])

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "frontend/src/api").mkdir(parents=True, exist_ok=True)
            (root / "frontend/src/api/client_1.ts").write_text("export const a = 1\n", encoding="utf-8")
            (root / "frontend/src/api/client_2.ts").write_text("export const b = 2\n", encoding="utf-8")

            for suggest_tool in (
                agentic_tools._tool_suggest_api_fix_async,
                agentic_tools._tool_suggest_contract_fix_async,
            ):
                session = _TypedefOnlySession()
                meta = agentic.AgenticMeta(tool_trace=[{"name": "plan_retrieval", "status": "ok"}])
                with patch("app.llm.agentic.tools._tool_compare_api_contract_async", return_value=report):
                    result = await suggest_tool(
                        session,
                        1,
                        root,
                        meta,
                        {
                            "path": "/api/items",
                            "method": "POST",
                            "route_limit": 3,
                            "call_limit": 5,
                            "include_backend_response": False,
                        },
                    )

                self.assertTrue(result["ok"])
                notes = result["data"].get("notes") or []
                self.assertGreaterEqual(
                    notes.count("typedef_not_found_for_body_type:MissingReqDto"),
                    2,
                )
                self.assertGreaterEqual(
                    notes.count("typedef_not_found_for_response_type:MissingRespDto"),
                    2,
                )
                self.assertEqual(session.typedef_queries, 1)


if __name__ == "__main__":
    unittest.main()
