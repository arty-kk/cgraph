import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.search import _fts_query_from_substring  # noqa: E402


class TestSearchLayer(unittest.TestCase):
    def test_fts_query_tokens(self) -> None:
        query = 'hello "world" test'
        expected = "hello:* & world:* & test:*"
        self.assertEqual(_fts_query_from_substring(query), expected)

    def test_fts_query_empty(self) -> None:
        self.assertIsNone(_fts_query_from_substring("   "))


if __name__ == "__main__":
    unittest.main()
