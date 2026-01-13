import unittest
from pathlib import Path

from .python_indexer import PythonIndexer


class PythonIndexerImportTest(unittest.TestCase):
    def test_dynamic_imports_with_literals(self) -> None:
        src = """
from typing import TYPE_CHECKING
import importlib
import importlib as il
from importlib import import_module as imod

mod = importlib.import_module("pkg.a")
mod2 = il.import_module("pkg.b")
mod3 = imod("pkg.c")
mod4 = __import__("pkg.d")
mod5 = __import__(module_name)

if TYPE_CHECKING:
    tmod = importlib.import_module("typing")
"""
        idx = PythonIndexer()
        imports = idx.parse_imports(Path("example.py"), src)

        def has_import(spec: str, kind: str) -> bool:
            return any(imp.spec == spec and imp.kind == kind for imp in imports)

        self.assertTrue(has_import("pkg.a", "dynamic"))
        self.assertTrue(has_import("pkg.b", "dynamic"))
        self.assertTrue(has_import("pkg.c", "dynamic"))
        self.assertTrue(has_import("pkg.d", "dynamic"))
        self.assertTrue(has_import("typing", "type_dynamic"))
        self.assertFalse(has_import("module_name", "dynamic"))


if __name__ == "__main__":
    unittest.main()
