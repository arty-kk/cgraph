#backend/app/indexers/python_indexer.py
from __future__ import annotations

import ast
from typing import List
from pathlib import Path
from .base import ImportRef

class PythonIndexer:
    def language(self) -> str:
        return "python"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        imports: list[ImportRef] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(ImportRef(raw=f"import {alias.name}", spec=alias.name, kind="runtime"))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                level = node.level or 0
                prefix = "." * level
                if module:
                    spec = prefix + module
                    imports.append(ImportRef(raw=f"from {spec} import ...", spec=spec, kind="runtime"))
                else:
                    for alias in getattr(node, "names", []) or []:
                        name = getattr(alias, "name", "") or ""
                        if not name:
                            continue
                        if name == "*":
                            spec = prefix or "."
                            imports.append(ImportRef(raw=f"from {spec} import *", spec=spec, kind="runtime"))
                        else:
                            spec = prefix + name
                            raw_prefix = (prefix or ".")
                            imports.append(ImportRef(raw=f"from {raw_prefix} import {name}", spec=spec, kind="runtime"))
        return imports

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return exports

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                exports.append(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        exports.append(t.id)
        seen = set()
        out: list[str] = []
        for e in exports:
            if e not in seen and not e.startswith("_"):
                seen.add(e)
                out.append(e)
        return out

    def naive_complexity(self, text: str) -> int:
        keywords = ["if ", "for ", "while ", " and ", " or ", "elif ", "except ", "case "]
        c = 1
        low = text.lower()
        for k in keywords:
            c += low.count(k)
        return c
