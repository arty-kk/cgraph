from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic


class _FakeExecResult:
    def __init__(self, *, scalar_rows=None, rows=None):
        self._scalar_rows = list(scalar_rows or [])
        self._rows = list(rows or [])

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self):
        self.route_obj = SimpleNamespace(
            method="GET",
            path="/api/items/{item_id}",
            source_path="backend/api/items.py",
            handler_name="get_item",
            lineno=10,
            decorator="router.get",
        )
        self.call_obj = SimpleNamespace(
            method="GET",
            path="/api/items/123",
            source_path="frontend/src/api/items.ts",
            lineno=22,
            client="axios",
            path_skeleton="/api/items/{}",
        )

    async def execute(self, statement, *_args, **_kwargs):
        await asyncio.sleep(0)
        sql = str(statement).lower()
        if "from api_route" in sql and "api_route.source_path" in sql and "api_route.decorator" in sql:
            return _FakeExecResult(
                rows=[
                    (
                        "backend/api/items.py",
                        "router.get",
                        "/api/items/{item_id}",
                    )
                ]
            )
        if "from api_route" in sql:
            return _FakeExecResult(scalar_rows=[self.route_obj], rows=[self.route_obj])
        if "from api_include" in sql:
            return _FakeExecResult(rows=[("backend/api/items.py", "router")])
        if "from api_call" in sql:
            return _FakeExecResult(scalar_rows=[self.call_obj], rows=[self.call_obj])
        return _FakeExecResult()


class TestAgenticLegacyToolsSessionConcurrencyRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_async_wrappers_reuse_passed_session_without_local_factory(self) -> None:
        fake_session = _FakeSession()
        async_session_local_calls = 0

        async def _fake_prefix_map(_project_id: int):
            await asyncio.sleep(0)
            return {}

        def _forbidden_local_session_factory(*_args, **_kwargs):
            nonlocal async_session_local_calls
            async_session_local_calls += 1
            raise AssertionError("AsyncSessionLocal must not be used in legacy async wrappers")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch("app.llm.agentic.tools.AsyncSessionLocal", side_effect=_forbidden_local_session_factory),
                patch("app.llm.agentic.tools._compute_prefix_map", side_effect=_fake_prefix_map),
            ):
                results = await asyncio.gather(
                    *[
                        agentic._tool_route_usages_async(
                            fake_session,
                            1,
                            {
                                "path": "/api/items/{item_id}",
                                "method": "GET",
                                "route_limit": 1,
                                "call_limit": 5,
                            },
                        )
                        for _ in range(6)
                    ],
                    *[
                        agentic._tool_suggest_endpoint_location_async(
                            fake_session,
                            1,
                            {"path": "/api/items/{item_id}", "method": "GET", "limit": 3},
                        )
                        for _ in range(6)
                    ],
                    *[
                        agentic._tool_suggest_frontend_client_async(
                            fake_session,
                            1,
                            root,
                            {"path": "/api/items/{item_id}", "method": "GET", "limit": 3},
                        )
                        for _ in range(6)
                    ],
                    *[
                        agentic._tool_impact_route_change_async(
                            fake_session,
                            1,
                            {
                                "old_path": "/api/items/{item_id}",
                                "new_path": "/api/v2/items/{item_id}",
                                "old_method": "GET",
                                "new_method": "GET",
                                "limit": 20,
                            },
                        )
                        for _ in range(6)
                    ],
                )

        self.assertEqual(async_session_local_calls, 0)
        self.assertEqual(len(results), 24)
        for result in results:
            self.assertTrue(result.get("ok"), result)
            self.assertIsNone(result.get("error"), result)


if __name__ == "__main__":
    unittest.main()
