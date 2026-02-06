import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.parsing_utils import extract_brace_block  # noqa: E402


class TestParsingUtils(unittest.TestCase):
    def test_nested_blocks(self) -> None:
        text = "const x = {a: {b: 1}, c: 2};"
        start = text.index("{")
        block = extract_brace_block(text, start)
        self.assertIsNotNone(block)
        s, e = block or (0, 0)
        self.assertEqual(text[s:e], "{a: {b: 1}, c: 2}")

    def test_strings_with_braces(self) -> None:
        text = "const x = {a: '{b}', b: \"{c}\", c: `d{e}`};"
        start = text.index("{")
        block = extract_brace_block(text, start)
        self.assertIsNotNone(block)
        s, e = block or (0, 0)
        self.assertEqual(text[s:e], "{a: '{b}', b: \"{c}\", c: `d{e}`}")

    def test_line_comment_ignores_braces(self) -> None:
        text = "const x = {a: 1, // { ignored\n b: 2};"
        start = text.index("{")
        block = extract_brace_block(text, start)
        self.assertIsNotNone(block)
        s, e = block or (0, 0)
        self.assertEqual(text[s:e], "{a: 1, // { ignored\n b: 2}")

    def test_block_comment_ignores_braces(self) -> None:
        text = "const x = {a: 1, /* { ignored } */ b: 2};"
        start = text.index("{")
        block = extract_brace_block(text, start)
        self.assertIsNotNone(block)
        s, e = block or (0, 0)
        self.assertEqual(text[s:e], "{a: 1, /* { ignored } */ b: 2}")

    def test_combined_nested_string_comment(self) -> None:
        text = "const x = {a: {b: 1}, c: '{d}', /* } */ d: 3};"
        start = text.index("{")
        block = extract_brace_block(text, start)
        self.assertIsNotNone(block)
        s, e = block or (0, 0)
        self.assertEqual(text[s:e], "{a: {b: 1}, c: '{d}', /* } */ d: 3}")


if __name__ == "__main__":
    unittest.main()
