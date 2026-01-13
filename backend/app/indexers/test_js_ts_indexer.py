import unittest
from pathlib import Path

from .js_ts_indexer import JsTsIndexer, _vue_language


class JsTsIndexerImportTest(unittest.TestCase):
    def test_template_literal_imports_skip_interpolation(self) -> None:
        src = """
const staticMod = import(`./static`);
const dynamicMod = import(`./${name}`);
"""
        idx = JsTsIndexer()
        imports = idx.parse_imports(Path("example.ts"), src)

        def has_import(spec: str) -> bool:
            return any(imp.spec == spec for imp in imports)

        self.assertTrue(has_import("./static"))
        self.assertFalse(has_import("./${name}"))

    def test_type_only_brace_imports(self) -> None:
        src = """
import { type Foo, type Bar } from "lib";
import { type Baz, Qux } from "lib2";
export { type Alpha } from "lib3";
"""
        idx = JsTsIndexer()
        imports = idx.parse_imports(Path("example.ts"), src)

        def has_import(spec: str, kind: str) -> bool:
            return any(imp.spec == spec and imp.kind == kind for imp in imports)

        self.assertTrue(has_import("lib", "type"))
        self.assertTrue(has_import("lib2", "runtime"))
        self.assertTrue(has_import("lib3", "type_reexport"))


class JsTsIndexerVueLangTest(unittest.TestCase):
    def test_vue_lang_tsx(self) -> None:
        self.assertEqual(_vue_language(' lang="tsx"'), "tsx")


if __name__ == "__main__":
    unittest.main()
