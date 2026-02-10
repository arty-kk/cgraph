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


if __name__ == "__main__":
    unittest.main()
