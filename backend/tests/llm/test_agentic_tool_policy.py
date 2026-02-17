import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402


class TestAgenticToolPolicy(unittest.TestCase):
    def test_empty_plan_retrieval_is_not_accepted_for_followup_tools(self) -> None:
        meta = agentic.AgenticMeta()
        meta.retrieval_plan = None

        plan_result = agentic._dispatch_tool(
            1,
            Path("."),
            meta,
            "plan_retrieval",
            {},
            max_file_chars=200,
        )

        self.assertFalse(plan_result["ok"])
        self.assertEqual(plan_result["error"]["code"], "bad_args")
        self.assertIsNone(meta.retrieval_plan)

        contract_result = agentic._dispatch_tool(
            1,
            Path("."),
            meta,
            "get_contract",
            {},
            max_file_chars=200,
        )

        self.assertFalse(contract_result["ok"])
        self.assertEqual(contract_result["error"]["code"], "policy_violation")

    def test_get_file_requires_search_beforehand(self) -> None:
        meta = agentic.AgenticMeta()
        meta.tool_trace.append({"name": "plan_retrieval", "status": "ok"})
        result = agentic._dispatch_tool(1, Path("."), meta, "get_file", {}, max_file_chars=200)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "policy_violation")
        self.assertEqual(
            result["error"]["message"],
            "Перед get_file нужно выполнить search_paths, search_symbols, search_text "
            "или search_semantic.",
        )

    def test_get_file_allowed_after_search(self) -> None:
        for tool_name in ("search_text", "search_symbols", "search_semantic", "search_paths"):
            with self.subTest(tool_name=tool_name):
                meta = agentic.AgenticMeta()
                meta.tool_trace.append({"name": "plan_retrieval", "status": "ok"})
                meta.tool_trace.append({"name": tool_name, "status": "ok"})
                with patch.object(
                    agentic,
                    "_tool_get_file",
                    return_value=agentic._tool_ok({"note": "ok"}),
                ) as mocked:
                    result = agentic._dispatch_tool(
                        1,
                        Path("."),
                        meta,
                        "get_file",
                        {},
                        max_file_chars=200,
                    )
                self.assertTrue(result["ok"])
                self.assertEqual(result["data"]["note"], "ok")
                mocked.assert_called_once()


class TestAgenticToolPolicyAsync(unittest.IsolatedAsyncioTestCase):
    async def test_async_dispatch_blocks_without_plan(self) -> None:
        meta = agentic.AgenticMeta()
        result = await agentic._dispatch_tool_async(
            1,
            Path("."),
            meta,
            "get_contract",
            {},
            max_file_chars=200,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "policy_violation")

    async def test_async_get_file_permission_gate(self) -> None:
        meta = agentic.AgenticMeta()
        meta.tool_trace.append({"name": "plan_retrieval", "status": "ok"})
        denied = await agentic._dispatch_tool_async(
            1,
            Path("."),
            meta,
            "get_file",
            {},
            max_file_chars=200,
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["code"], "policy_violation")

        meta_allowed = agentic.AgenticMeta()
        meta_allowed.tool_trace.append({"name": "plan_retrieval", "status": "ok"})
        meta_allowed.tool_trace.append({"name": "search_text", "status": "ok"})

        async def _fake_get_file(*_a, **_kw):
            return agentic._tool_ok({"note": "ok"})

        with patch.object(agentic, "_tool_get_file_async", side_effect=_fake_get_file):
            allowed = await agentic._dispatch_tool_async(
                1,
                Path("."),
                meta_allowed,
                "get_file",
                {},
                max_file_chars=200,
            )
        self.assertTrue(allowed["ok"])


if __name__ == "__main__":
    unittest.main()


class TestAgenticAsyncMapping(unittest.IsolatedAsyncioTestCase):
    async def test_async_dispatch_mapping_does_not_call_sync_tools(self) -> None:
        meta = agentic.AgenticMeta()
        meta.tool_trace.append({"name": "plan_retrieval", "status": "ok"})

        sync_attrs = [
            "_tool_get_contract",
            "_tool_get_symbol",
            "_tool_search_tests",
            "_tool_get_tree_outline",
            "_tool_project_summary",
            "_tool_search_text",
            "_tool_route_usages",
            "_tool_suggest_endpoint_location",
            "_tool_suggest_frontend_client",
            "_tool_impact_route_change",
            "_tool_compare_api_contract",
            "_tool_suggest_contract_fix",
            "_tool_suggest_api_fix",
        ]
        async_mapping = {
            "get_contract": "_tool_get_contract_async",
            "get_symbol": "_tool_get_symbol_async",
            "search_tests": "_tool_search_tests_async",
            "get_tree_outline": "_tool_get_tree_outline_async",
            "project_summary": "_tool_project_summary_async",
            "search_text": "_tool_search_text_async",
            "route_usages": "_tool_route_usages_async",
            "suggest_endpoint_location": "_tool_suggest_endpoint_location_async",
            "suggest_frontend_client": "_tool_suggest_frontend_client_async",
            "impact_route_change": "_tool_impact_route_change_async",
            "compare_api_contract": "_tool_compare_api_contract_async",
            "suggest_contract_fix": "_tool_suggest_contract_fix_async",
            "suggest_api_fix": "_tool_suggest_api_fix_async",
        }

        patchers = []
        for attr in sync_attrs:
            p_sync = patch.object(
                agentic,
                attr,
                side_effect=AssertionError(f"sync tool called: {attr}"),
            )
            p_sync.start()
            patchers.append(p_sync)

        async def _fake_async_tool(*_args, **_kwargs):
            return agentic._tool_ok({"tool": "ok"})

        for attr in async_mapping.values():
            p_async = patch.object(agentic, attr, side_effect=_fake_async_tool)
            p_async.start()
            patchers.append(p_async)

        try:
            for tool_name in async_mapping:
                with self.subTest(tool_name=tool_name):
                    result = await agentic._dispatch_tool_async(
                        1,
                        Path("."),
                        meta,
                        tool_name,
                        {"path": "/api/test", "query": "q", "name": "n"},
                        max_file_chars=200,
                    )
                    self.assertTrue(result["ok"])
        finally:
            for patcher in reversed(patchers):
                patcher.stop()
