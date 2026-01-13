from __future__ import annotations

import re
from pathlib import Path
from .base import ImportRef, SymbolDef
from .tree_sitter_utils import iter_nodes, node_text, parse_tree


_USE_SPLIT_RE = re.compile(r"\s+as\s+", re.IGNORECASE)
_PHP_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_PHP_LINE_COMMENT_RE = re.compile(r"//.*?$|#.*?$", re.MULTILINE)
_PHP_INCLUDE_RE = re.compile(
    r"""(?x)(?<![\w$])
    (?:include|include_once|require|require_once)\s*
    (?:\(|\s)\s*(?P<path>['"][^'"]+['"])
    """,
    re.IGNORECASE,
)
_PHP_INCLUDE_CONCAT_RE = re.compile(
    r"""(?x)(?<![\w$])
    (?P<kw>include|include_once|require|require_once)\s*
    (?:\(|\s)\s*(?P<expr>
        (?:__DIR__\s*\.\s*)?
        ['"][^'"]*['"]
        (?:\s*\.\s*['"][^'"]*['"])*
    )
    """,
    re.IGNORECASE,
)
_PHP_INCLUDE_CONCAT_EXPR_RE = re.compile(
    r"""(?x)
    \s*
    (?:__DIR__\s*\.\s*)?
    ['"][^'"]*['"]
    (?:\s*\.\s*['"][^'"]*['"])*\s*
    """,
)


def _strip_php_comments(text: str) -> str:
    text = _PHP_BLOCK_COMMENT_RE.sub("", text)
    text = _PHP_LINE_COMMENT_RE.sub("", text)
    return text


def _strip_quotes(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _strip_use_prefix(raw: str) -> tuple[str, str]:
    s = (raw or "").strip().rstrip(";").strip()
    kind = "import"
    lower = s.lower()
    if lower.startswith("use function "):
        kind = "function"
        s = s[len("use function "):]
    elif lower.startswith("use const "):
        kind = "const"
        s = s[len("use const "):]
    elif lower.startswith("use "):
        s = s[len("use "):]
    return s.strip(), kind


def _split_alias(item: str) -> tuple[str, str | None]:
    parts = _USE_SPLIT_RE.split(item, 1)
    if len(parts) == 2:
        base = parts[0].strip()
        alias = parts[1].strip() or None
        return base, alias
    return item.strip(), None


def _parse_use_item(item: str, default_kind: str) -> tuple[str, str, str | None]:
    item = (item or "").strip()
    if not item:
        return "", default_kind, None
    lower = item.lower()
    if lower.startswith("function "):
        base = item[len("function ") :].strip()
        base, alias = _split_alias(base)
        return base, "function", alias
    if lower.startswith("const "):
        base = item[len("const ") :].strip()
        base, alias = _split_alias(base)
        return base, "const", alias
    base, alias = _split_alias(item)
    return base, default_kind, alias


def _split_use_items(spec: str, default_kind: str) -> list[tuple[str, str, str | None]]:
    if "{" not in spec or "}" not in spec:
        parts = [p.strip() for p in spec.split(",") if p.strip()]
        out: list[tuple[str, str, str | None]] = []
        for part in parts:
            item, kind, alias = _parse_use_item(part, default_kind)
            if not item:
                continue
            out.append((item, kind, alias))
        return out
    base, rest = spec.split("{", 1)
    base = base.rstrip("\\").strip()
    inner = rest.split("}", 1)[0]
    parts = [p.strip() for p in inner.split(",") if p.strip()]
    out: list[tuple[str, str, str | None]] = []
    for part in parts:
        item, kind, alias = _parse_use_item(part, default_kind)
        if not item:
            continue
        spec_item = f"{base}\\{item}".strip("\\") if base else item
        out.append((spec_item, kind, alias))
    return out


def _clean_use_item(item: str) -> str:
    item = (item or "").strip()
    if not item:
        return ""
    return item


def _format_use_raw(spec: str, kind: str, alias: str | None) -> str:
    prefix = ""
    if kind == "function":
        prefix = "function "
    elif kind == "const":
        prefix = "const "
    alias_part = f" as {alias}" if alias else ""
    return f"use {prefix}{spec}{alias_part}".strip()


def _parse_include_concat(expr: str) -> str | None:
    expr_clean = (expr or "").strip()
    if not expr_clean:
        return None
    if "." not in expr_clean and "__DIR__" not in expr_clean:
        return None
    if not _PHP_INCLUDE_CONCAT_EXPR_RE.fullmatch(expr_clean):
        return None
    literals = re.findall(r"""['"][^'"]*['"]""", expr_clean)
    if not literals:
        return None
    joined = "".join(_strip_quotes(lit) for lit in literals)
    if "__DIR__" in expr_clean:
        return f"__DIR__{joined}"
    return joined


class PhpIndexer:
    def language(self) -> str:
        return "php"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        out: list[ImportRef] = []
        tree, data = parse_tree("php", text)
        if tree is None:
            tree = None
        seen: set[tuple[str, str]] = set()

        def _add(raw: str, spec: str, kind: str) -> None:
            spec = (spec or "").strip()
            if not spec:
                return
            key = (kind, spec)
            if key in seen:
                return
            seen.add(key)
            out.append(ImportRef(raw=raw, spec=spec, kind=kind))

        if tree is not None:
            for node in iter_nodes(tree.root_node):
                if node.type not in ("namespace_use_declaration", "namespace_use_clause"):
                    continue
                raw = node_text(node, data).strip()
                if not raw.lower().startswith("use "):
                    continue
                spec_raw, kind = _strip_use_prefix(raw)
                for item, item_kind, alias in _split_use_items(spec_raw, kind):
                    spec = _clean_use_item(item)
                    raw_item = _format_use_raw(spec, item_kind, alias)
                    _add(raw_item or raw, spec, item_kind)

        stripped = _strip_php_comments(text or "")
        for match in _PHP_INCLUDE_RE.finditer(stripped):
            raw = match.group(0).strip()
            spec = _strip_quotes(match.group("path"))
            _add(raw, spec, "include")
        for match in _PHP_INCLUDE_CONCAT_RE.finditer(stripped):
            expr = match.group("expr")
            spec = _parse_include_concat(expr)
            if not spec:
                continue
            raw = match.group(0).strip()
            _add(raw, spec, "include-conditional")
        return out

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        tree, data = parse_tree("php", text)
        if tree is None:
            return exports
        seen: set[str] = set()
        for node in iter_nodes(tree.root_node):
            if node.type in (
                "class_declaration",
                "interface_declaration",
                "trait_declaration",
                "enum_declaration",
                "function_definition",
            ):
                name = node_text(node.child_by_field_name("name"), data)
                if name and name not in seen:
                    seen.add(name)
                    exports.append(name)
            if node.type == "const_declaration":
                for ch in node.children:
                    if ch.type == "const_element":
                        nm = node_text(ch.child_by_field_name("name"), data)
                        if nm and nm not in seen:
                            seen.add(nm)
                            exports.append(nm)
        return exports

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        out: list[SymbolDef] = []
        tree, data = parse_tree("php", text)
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
            if node.type in (
                "class_declaration",
                "interface_declaration",
                "trait_declaration",
                "enum_declaration",
            ):
                name = node_text(node.child_by_field_name("name"), data)
                ln = int(node.start_point[0]) + 1
                end_ln = int(node.end_point[0]) + 1
                kind = node.type.replace("_declaration", "")
                _add(name, kind, ln, end_ln)
            elif node.type == "function_definition":
                name = node_text(node.child_by_field_name("name"), data)
                ln = int(node.start_point[0]) + 1
                end_ln = int(node.end_point[0]) + 1
                _add(name, "function", ln, end_ln)
            elif node.type == "const_declaration":
                ln = int(node.start_point[0]) + 1
                end_ln = int(node.end_point[0]) + 1
                for ch in node.children:
                    if ch.type == "const_element":
                        nm = node_text(ch.child_by_field_name("name"), data)
                        _add(nm, "const", ln, end_ln)
        return out

    def naive_complexity(self, text: str) -> int:
        keywords = ["if(", "if (", "for(", "for (", "while(", "while (", "&&", "||", "catch", "case "]
        c = 1
        low = text.lower()
        for k in keywords:
            c += low.count(k)
        return c
