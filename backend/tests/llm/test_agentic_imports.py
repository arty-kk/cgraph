import importlib
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))


class TestAgenticImports(unittest.TestCase):
    def test_agentic_package_reexports(self) -> None:
        agentic = importlib.import_module("app.llm.agentic")

        self.assertTrue(callable(agentic.analyze_agentic))
        self.assertTrue(callable(agentic.evolve_agentic))
        self.assertTrue(callable(agentic.fix_agentic))
        self.assertTrue(hasattr(agentic, "AgenticMeta"))

        self.assertTrue(callable(agentic._dispatch_tool))
        self.assertTrue(callable(agentic._tool_get_file))
        self.assertTrue(callable(agentic._tool_get_file_lines))
        self.assertTrue(callable(agentic._tool_definitions))
        self.assertTrue(callable(agentic._tool_ok))
        self.assertTrue(callable(agentic._clamp_int))
        self.assertTrue(hasattr(agentic, "_FTS_TOKEN_RE"))


if __name__ == "__main__":
    unittest.main()
