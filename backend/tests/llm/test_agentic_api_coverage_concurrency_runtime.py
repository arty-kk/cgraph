from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm.agentic import tools as agentic_tools


def _make_call(call_id: int, method: str, path: str, skeleton: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        method=method,
        path=path,
        path_skeleton=skeleton,
        source_path=f"frontend/call_{call_id}.ts",
        lineno=call_id,
        client="fetch",
    )


def _make_route(route_id: int, method: str, path: str, decorator: str = "app.get") -> SimpleNamespace:
    return SimpleNamespace(
        id=route_id,
        method=method,
        path=path,
        source_path=f"backend/route_{route_id}.py",
        lineno=route_id,
        handler_name=f"handler_{route_id}",
        decorator=decorator,
    )


def _legacy_match(calls, call_index, routes, patterns_by_route, pattern_index):
    matched_call_ids: set[int] = set()
    for c in calls:
        cid = int(getattr(c, "id", 0) or 0)
        m = str(c.method or "").upper()
        pnorm = agentic_tools._normalize_http_path(str(c.path or ""))
        ctoks = agentic_tools.split_skeleton(str(c.path_skeleton or ""))
        if not ctoks or not m or not pnorm:
            continue
        keys = agentic_tools._candidate_keys_from_path(pnorm) or [""]
        candidates = []
        for k in keys:
            candidates.extend(pattern_index.get(m, {}).get(k, []))
        if candidates and agentic_tools._call_matches_any_pattern(ctoks, candidates):
            matched_call_ids.add(cid)

    matched_route_ids: set[int] = set()
    for r in routes:
        rid = int(getattr(r, "id", 0) or 0)
        variants = patterns_by_route.get(rid) or []
        ok = False
        for v in variants:
            method = str(v.get("method") or "")
            vtoks = v.get("tokens") or []
            if not method or not isinstance(vtoks, list) or not vtoks:
                continue
            candidates_calls = []
            for k in v.get("static_keys") or [""]:
                candidates_calls.extend(call_index.get(method, {}).get(k, []))
            if not candidates_calls:
                candidates_calls = call_index.get(method, {}).get("", [])
            if candidates_calls and agentic_tools._pattern_matches_any_call(vtoks, candidates_calls):
                ok = True
                break
        if ok:
            matched_route_ids.add(rid)
    return matched_route_ids, matched_call_ids


class TestAgenticApiCoverageConcurrencyRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_coverage_cpu_does_not_block_event_loop(self) -> None:
        calls = [
            _make_call(i, "GET", f"/api/items/{i}", "/api/items/{}")
            for i in range(1, 250)
        ]
        routes = [_make_route(i, "GET", "/items/{item_id}") for i in range(1, 250)]
        includes = [
            SimpleNamespace(
                parent_source_path="main.py",
                parent_instance="app",
                child_source_path=r.source_path,
                child_instance="app",
                prefix="/api",
            )
            for r in routes
        ]
        limits = {
            "max_calls": 50_000,
            "max_routes": 50_000,
            "calls_selected": len(calls),
            "routes_selected": len(routes),
            "calls_truncated": False,
            "routes_truncated": False,
            "degraded": False,
            "degraded_reasons": [],
        }

        async def _fake_load(*_args, **_kwargs):
            return calls, routes, includes, limits

        original = agentic_tools.patterns_compatible

        def _slow_compatible(a, b):
            time.sleep(0.0005)
            return original(a, b)

        stop = asyncio.Event()
        ticks = 0

        async def _heartbeat() -> None:
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.005)

        with patch("app.llm.agentic.tools._load_api_coverage_inputs_async", new=_fake_load), patch(
            "app.llm.agentic.tools.patterns_compatible", new=_slow_compatible
        ):
            hb = asyncio.create_task(_heartbeat())
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(
                        *[
                            agentic_tools._tool_api_coverage_summary_async(None, 1, {})
                            for _ in range(4)
                        ]
                    ),
                    timeout=10,
                )
            finally:
                stop.set()
                await hb

        self.assertGreater(ticks, 10)
        for result in results:
            self.assertTrue(result["ok"])
            self.assertFalse(result["data"]["analysis_meta"]["degraded"])

    async def test_matching_regression_equivalent_to_legacy(self) -> None:
        calls = [
            _make_call(1, "GET", "/api/items/1", "/api/items/{}"),
            _make_call(2, "POST", "/api/items", "/api/items"),
            _make_call(3, "GET", "/api/unknown/1", "/api/unknown/{}"),
        ]
        routes = [
            _make_route(10, "GET", "/items/{item_id}"),
            _make_route(11, "POST", "/items"),
            _make_route(12, "DELETE", "/items/{item_id}"),
        ]
        includes = [
            SimpleNamespace(
                parent_source_path="main.py",
                parent_instance="app",
                child_source_path=r.source_path,
                child_instance="app",
                prefix="/api",
            )
            for r in routes
        ]

        calls_f, call_index, routes_f, patterns_by_route, pattern_index = (
            agentic_tools._build_api_coverage_indexes_cpu(
                calls_raw=calls,
                routes_raw=routes,
                includes=includes,
                prefix="/api",
            )
        )
        expected_routes, expected_calls = _legacy_match(
            calls_f,
            call_index,
            routes_f,
            patterns_by_route,
            pattern_index,
        )
        actual_routes, actual_calls = agentic_tools._match_api_coverage_cpu(
            calls=calls_f,
            call_index=call_index,
            routes=routes_f,
            patterns_by_route=patterns_by_route,
            pattern_index=pattern_index,
        )

        self.assertEqual(actual_routes, expected_routes)
        self.assertEqual(actual_calls, expected_calls)

    async def test_parallel_coverage_tools_are_stable(self) -> None:
        calls = [_make_call(i, "GET", f"/api/orders/{i}", "/api/orders/{}") for i in range(1, 60)]
        routes = [_make_route(i, "GET", "/orders/{order_id}") for i in range(1, 60)]
        includes = [
            SimpleNamespace(
                parent_source_path="main.py",
                parent_instance="app",
                child_source_path=r.source_path,
                child_instance="app",
                prefix="/api",
            )
            for r in routes
        ]
        limits = {
            "max_calls": 50_000,
            "max_routes": 50_000,
            "calls_selected": len(calls),
            "routes_selected": len(routes),
            "calls_truncated": False,
            "routes_truncated": False,
            "degraded": False,
            "degraded_reasons": [],
        }

        async def _fake_load(*_args, **_kwargs):
            return calls, routes, includes, limits

        with patch("app.llm.agentic.tools._load_api_coverage_inputs_async", new=_fake_load):
            summary_results = await asyncio.gather(
                *[agentic_tools._tool_api_coverage_summary_async(None, 1, {}) for _ in range(8)]
            )
            route_results = await asyncio.gather(
                *[agentic_tools._tool_unmatched_routes_async(None, 1, {}) for _ in range(8)]
            )
            call_results = await asyncio.gather(
                *[agentic_tools._tool_unmatched_calls_async(None, 1, {}) for _ in range(8)]
            )

        summary_counts = {r["data"]["counts"]["calls_unmatched"] for r in summary_results}
        self.assertEqual(summary_counts, {0})
        self.assertTrue(all(not r["data"]["analysis_meta"]["degraded"] for r in summary_results))
        self.assertEqual({r["data"]["count"] for r in route_results}, {0})
        self.assertEqual({r["data"]["count"] for r in call_results}, {0})


if __name__ == "__main__":
    unittest.main()
