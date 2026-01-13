from __future__ import annotations

from pathlib import Path
from .base import ImportRef, SymbolDef
from .tree_sitter_utils import iter_nodes, node_text, parse_tree


def _clean_import(raw: str) -> tuple[str, str]:
    s = (raw or "").strip()
    kind = "import"
    if s.startswith("import static"):
        kind = "static_import"
        s = s[len("import static"):].strip()
    elif s.startswith("import"):
        s = s[len("import"):].strip()
    s = s.rstrip(";").strip()
    return s, kind


def _has_public_modifier(node, data: bytes) -> bool:
    modifiers = node.child_by_field_name("modifiers")
    if modifiers is None:
        return False
    for ch in modifiers.children:
        if ch.type == "public":
            return True
    return False


class JavaIndexer:
    def language(self) -> str:
        return "java"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        out: list[ImportRef] = []
        tree, data = parse_tree("java", text)
        if tree is None:
            return out
        seen: set[tuple[str, str]] = set()
        for node in iter_nodes(tree.root_node):
            if node.type != "import_declaration":
                continue
            raw = node_text(node, data).strip()
            spec, kind = _clean_import(raw)
            if not spec:
                continue
            key = (kind, spec)
            if key in seen:
                continue
            seen.add(key)
            out.append(ImportRef(raw=raw, spec=spec, kind=kind))
        return out

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        tree, data = parse_tree("java", text)
        if tree is None:
            return exports
        seen: set[str] = set()
        for node in iter_nodes(tree.root_node):
            if node.type not in (
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "record_declaration",
                "annotation_type_declaration",
            ):
                continue
            if not _has_public_modifier(node, data):
                continue
            name = node_text(node.child_by_field_name("name"), data)
            if name and name not in seen:
                seen.add(name)
                exports.append(name)
        return exports

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        out: list[SymbolDef] = []
        tree, data = parse_tree("java", text)
        if tree is None:
            return out
        lines = text.splitlines()
        seen: set[tuple[str, str, int]] = set()

        def _signature(line_no: int) -> str:
            if 1 <= line_no <= len(lines):
                return lines[line_no - 1].strip()
            return ""

        def _add(name: str, kind: str, line_no: int, end_line: int) -> None:
            if not name:
                return
            key = (kind, name, line_no)
            if key in seen:
                return
            seen.add(key)
            out.append(
                SymbolDef(
                    name=name,
                    kind=kind,
                    signature=_signature(line_no),
                    doc="",
                    start_line=int(line_no),
                    end_line=int(end_line),
                )
            )

        for node in iter_nodes(tree.root_node):
            if node.type not in (
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "record_declaration",
                "annotation_type_declaration",
            ):
                continue
            name = node_text(node.child_by_field_name("name"), data)
            ln = int(node.start_point[0]) + 1
            end_ln = int(node.end_point[0]) + 1
            kind = node.type.replace("_declaration", "").replace("annotation_type", "annotation")
            _add(name, kind, ln, end_ln)
        return out

    def naive_complexity(self, text: str) -> int:
        keywords = ["if(", "if (", "for(", "for (", "while(", "while (", "&&", "||", "catch", "case "]
        c = 1
        low = text.lower()
        for k in keywords:
            c += low.count(k)
        return c
