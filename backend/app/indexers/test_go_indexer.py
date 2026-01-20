import os
import unittest
from unittest import mock
from pathlib import Path

from ..config import settings
from .go_indexer import GoIndexer, _build_context_tags, _is_build_context_active, _runtime_go_env
from .tree_sitter_utils import parse_tree


class GoIndexerBuildTagTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_build_tags = settings.go_build_tags
        self._old_include_unexported = settings.go_include_unexported_symbols
        self._has_go_parser = parse_tree("go", "package main")[0] is not None

    def tearDown(self) -> None:
        settings.go_build_tags = self._old_build_tags
        settings.go_include_unexported_symbols = self._old_include_unexported

    def test_build_tags_exclude_imports(self) -> None:
        settings.go_build_tags = "dev"
        src = """//go:build prod
// +build prod

package main

import "fmt"
"""
        if not self._has_go_parser:
            self.skipTest("go parser unavailable")
        idx = GoIndexer()
        imports = idx.parse_imports(Path("main.go"), src)
        self.assertTrue(any(imp.kind == "import_excluded" for imp in imports))

    def test_build_tags_inactive_context(self) -> None:
        settings.go_build_tags = "dev"
        src = """//go:build prod
package main
"""
        self.assertFalse(_is_build_context_active(src))

    def test_build_tags_allow_exports(self) -> None:
        settings.go_build_tags = "prod"
        src = """//go:build prod
package main

type Widget struct{}
"""
        self.assertTrue(_is_build_context_active(src))
        if not self._has_go_parser:
            self.skipTest("go parser unavailable")
        idx = GoIndexer()
        exports = idx.parse_exports(Path("main.go"), src)
        self.assertIn("Widget", exports)

    def test_invalid_build_expr_falls_back_to_active(self) -> None:
        settings.go_build_tags = "linux"
        src = """//go:build linux &&
package main
"""
        self.assertTrue(_is_build_context_active(src))

    def test_invalid_go_build_falls_back_to_plus_build(self) -> None:
        settings.go_build_tags = "prod"
        src = """//go:build linux &&
// +build prod

package main
"""
        self.assertTrue(_is_build_context_active(src))

    def test_go_build_mismatch_plus_build_falls_back_to_active(self) -> None:
        settings.go_build_tags = "prod"
        src = """//go:build prod
// +build dev

package main
"""
        self.assertTrue(_is_build_context_active(src))

    def test_build_tags_use_runtime_defaults(self) -> None:
        settings.go_build_tags = ""
        runtime = _runtime_go_env()
        with mock.patch.dict(os.environ, {}, clear=True):
            tags = _build_context_tags()
        for value in runtime.values():
            self.assertIn(value, tags)

    def test_include_unexported_symbols(self) -> None:
        settings.go_build_tags = ""
        settings.go_include_unexported_symbols = True
        src = """package main

func doWork() {}
"""
        if not self._has_go_parser:
            self.skipTest("go parser unavailable")
        idx = GoIndexer()
        symbols = idx.parse_symbols(Path("main.go"), src)
        self.assertTrue(any(sym.name == "doWork" for sym in symbols))
