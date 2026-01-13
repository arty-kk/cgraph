import unittest
from pathlib import Path

from .php_indexer import PhpIndexer
from .tree_sitter_utils import parse_tree


class PhpIndexerImportTest(unittest.TestCase):
    def test_use_group_aliases(self) -> None:
        src = """<?php
use Foo\\{Bar as Baz, Qux};
use function Utils\\{str_starts_with as starts_with};
use const Foo\\{BAR as BAR_ALIAS};
"""
        tree, _ = parse_tree("php", src)
        if tree is None:
            self.skipTest("tree-sitter-php not available")
        idx = PhpIndexer()
        imports = idx.parse_imports(Path("example.php"), src)

        def find_import(spec: str, kind: str) -> list:
            return [imp for imp in imports if imp.spec == spec and imp.kind == kind]

        bar_imports = find_import("Foo\\Bar", "import")
        self.assertEqual(len(bar_imports), 1)
        self.assertIn("as Baz", bar_imports[0].raw)

        fn_imports = find_import("Utils\\str_starts_with", "function")
        self.assertEqual(len(fn_imports), 1)
        self.assertIn("as starts_with", fn_imports[0].raw)

        const_imports = find_import("Foo\\BAR", "const")
        self.assertEqual(len(const_imports), 1)
        self.assertIn("as BAR_ALIAS", const_imports[0].raw)

    def test_include_concat_literals(self) -> None:
        src = """<?php
include __DIR__ . '/file.php';
require 'a' . '/b.php';
require_once 'single.php';
"""
        idx = PhpIndexer()
        imports = idx.parse_imports(Path("example.php"), src)

        def has_import(spec: str, kind: str) -> bool:
            return any(imp.spec == spec and imp.kind == kind for imp in imports)

        self.assertTrue(has_import("__DIR__/file.php", "include-conditional"))
        self.assertTrue(has_import("a/b.php", "include-conditional"))
        self.assertTrue(has_import("single.php", "include"))


if __name__ == "__main__":
    unittest.main()
