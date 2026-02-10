import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm import agentic  # noqa: E402


class TestAgenticSearchSemantic(unittest.TestCase):
    def test_search_semantic_returns_error_for_invalid_response(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            args = {"query": "find auth flow"}

            with patch("app.llm.agentic.tools.search_semantic", return_value=None):
                result = agentic._tool_search_semantic(1, root, args, max_file_chars=1000)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "semantic_failed")


if __name__ == "__main__":
    unittest.main()
