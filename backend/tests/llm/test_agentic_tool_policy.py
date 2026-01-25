import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402


class TestAgenticToolPolicy(unittest.TestCase):
    def test_get_file_requires_search_beforehand(self) -> None:
        meta = agentic.AgenticMeta()
        result = agentic._dispatch_tool(1, Path("."), meta, "get_file", {}, max_file_chars=200)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "policy_violation")
        self.assertEqual(
            result["error"]["message"],
            "Перед get_file нужно выполнить search_symbols или search_text.",
        )

    def test_get_file_allowed_after_search(self) -> None:
        meta = agentic.AgenticMeta()
        meta.tool_trace.append({"name": "search_text", "status": "ok"})
        with patch.object(agentic, "_tool_get_file", return_value=agentic._tool_ok({"note": "ok"})) as mocked:
            result = agentic._dispatch_tool(1, Path("."), meta, "get_file", {}, max_file_chars=200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["note"], "ok")
        mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
