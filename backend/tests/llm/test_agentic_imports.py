import importlib
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))


class TestAgenticImports(unittest.TestCase):
    def test_agentic_package_reexports_async_runtime_only(self) -> None:
        agentic = importlib.import_module("app.llm.agentic")

        self.assertTrue(callable(agentic.analyze_agentic_async))
        self.assertTrue(callable(agentic.evolve_agentic_async))
        self.assertTrue(callable(agentic.fix_agentic_async))
        self.assertTrue(callable(agentic._dispatch_tool_async))
        self.assertTrue(callable(agentic._seed_context_async))
        self.assertTrue(callable(agentic._agentic_json_call_async))
        self.assertTrue(callable(agentic._tool_get_file_async))
        self.assertTrue(callable(agentic._tool_get_file_lines_async))
        self.assertTrue(callable(agentic._tool_get_neighbors_async))
        self.assertTrue(callable(agentic._tool_search_paths_async))
        self.assertTrue(callable(agentic._tool_search_semantic_async))
        self.assertTrue(callable(agentic._tool_api_coverage_summary_async))
        self.assertTrue(callable(agentic._tool_unmatched_routes_async))
        self.assertTrue(callable(agentic._tool_unmatched_calls_async))
        self.assertTrue(callable(agentic._tool_definitions))
        self.assertTrue(hasattr(agentic, "AgenticMeta"))

    def test_sync_runtime_symbols_not_available(self) -> None:
        agentic = importlib.import_module("app.llm.agentic")

        for symbol in (
            "analyze_agentic",
            "evolve_agentic",
            "fix_agentic",
            "_dispatch_tool",
            "_seed_context",
            "_agentic_json_call",
            "_tool_get_file",
            "_tool_get_file_lines",
            "_tool_get_neighbors",
            "_tool_search_paths",
            "_tool_search_semantic",
            "_tool_api_coverage_summary",
            "_tool_unmatched_routes",
            "_tool_unmatched_calls",
        ):
            with self.subTest(symbol=symbol):
                self.assertFalse(hasattr(agentic, symbol))
                with self.assertRaises(AttributeError):
                    getattr(agentic, symbol)


if __name__ == "__main__":
    unittest.main()
