#backend/app/indexers/go_indexer.py
from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path
from .base import ImportRef, SymbolDef
from .tree_sitter_utils import iter_nodes, node_text, parse_tree
from ..config import settings


def _strip_quotes(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"', "`"):
        return s[1:-1]
    return s


def _extract_identifier_list(node, data: bytes) -> list[str]:
    if node is None:
        return []
    if node.type == "identifier":
        return [node_text(node, data)]
    if node.type == "identifier_list":
        return [node_text(ch, data) for ch in node.children if ch.type == "identifier"]
    return []

_GO_BUILD_TOKEN_RE = re.compile(r"\s*([()!]|&&|\|\||[A-Za-z0-9_\.]+)")


def _split_build_tags(raw: str) -> set[str]:
    if not raw:
        return set()
    return {p for p in re.split(r"[,\s]+", raw) if p}


def _extract_build_constraints(text: str) -> tuple[str | None, list[str]]:
    go_build = None
    plus_build: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("package "):
            break
        if not stripped:
            continue
        if stripped.startswith("//"):
            comment = stripped[2:].strip()
            if comment.startswith("go:build"):
                expr = comment[len("go:build") :].strip()
                if expr:
                    go_build = expr
            elif comment.startswith("+build"):
                expr = comment[len("+build") :].strip()
                if expr:
                    plus_build.append(expr)
            continue
        break
    return go_build, plus_build


def _eval_tag(tag: str, tags: set[str]) -> bool:
    if not tag:
        return False
    negated = tag.startswith("!")
    name = tag[1:] if negated else tag
    if name == "true":
        result = True
    elif name == "false":
        result = False
    else:
        result = name in tags
    return not result if negated else result


def _eval_plus_build(lines: list[str], tags: set[str]) -> bool:
    if not lines:
        return True
    for line in lines:
        clauses = [c for c in line.split() if c]
        if not clauses:
            return False
        line_ok = False
        for clause in clauses:
            parts = [p for p in clause.split(",") if p]
            if parts and all(_eval_tag(p, tags) for p in parts):
                line_ok = True
                break
        if not line_ok:
            return False
    return True


def _eval_go_build(expr: str, tags: set[str]) -> bool:
    tokens = [m.group(1) for m in _GO_BUILD_TOKEN_RE.finditer(expr)]
    idx = 0

    def _peek() -> str | None:
        return tokens[idx] if idx < len(tokens) else None

    def _consume() -> str | None:
        nonlocal idx
        tok = _peek()
        if tok is not None:
            idx += 1
        return tok

    def _parse_primary() -> bool:
        tok = _peek()
        if tok is None:
            return False
        if tok == "(":
            _consume()
            val = _parse_or()
            if _peek() == ")":
                _consume()
            return val
        _consume()
        return _eval_tag(tok, tags)

    def _parse_unary() -> bool:
        tok = _peek()
        if tok == "!":
            _consume()
            return not _parse_unary()
        return _parse_primary()

    def _parse_and() -> bool:
        val = _parse_unary()
        while _peek() == "&&":
            _consume()
            val = val and _parse_unary()
        return val

    def _parse_or() -> bool:
        val = _parse_and()
        while _peek() == "||":
            _consume()
            val = val or _parse_and()
        return val

    return _parse_or()


def _build_context_tags() -> set[str]:
    tags = _split_build_tags(getattr(settings, "go_build_tags", "") or "")
    runtime_defaults = _runtime_go_env()
    for env_key in ("GOOS", "GOARCH"):
        try:
            env_val = os.getenv(env_key, "")
        except Exception:
            env_val = ""
        if env_val:
            tags.add(env_val)
        else:
            fallback = runtime_defaults.get(env_key)
            if fallback:
                tags.add(fallback)
    return tags


def _runtime_go_env() -> dict[str, str]:
    goos = None
    goarch = None

    sys_platform = sys.platform
    if sys_platform.startswith("linux"):
        goos = "linux"
    elif sys_platform == "darwin":
        goos = "darwin"
    elif sys_platform in ("win32", "cygwin", "msys"):
        goos = "windows"
    else:
        system = platform.system().lower()
        if system:
            goos = system

    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "i386": "386",
        "i686": "386",
        "x86": "386",
        "armv6l": "arm",
        "armv7l": "arm",
        "armv6": "arm",
        "armv7": "arm",
    }
    goarch = arch_map.get(machine)
    return {key: val for key, val in {"GOOS": goos, "GOARCH": goarch}.items() if val}


def _is_build_context_active(text: str) -> bool:
    go_build, plus_build = _extract_build_constraints(text)
    if not go_build and not plus_build:
        return True
    tags = _build_context_tags()
    if go_build:
        try:
            return _eval_go_build(go_build, tags)
        except Exception:
            return True
    try:
        return _eval_plus_build(plus_build, tags)
    except Exception:
        return True


class GoIndexer:
    def language(self) -> str:
        return "go"

    def parse_imports(self, file_path: Path, text: str):
        out: list[ImportRef] = []
        tree, data = parse_tree("go", text)
        if tree is None:
            return out
        active = _is_build_context_active(text)
        kind = "import" if active else "import_excluded"
        seen: set[str] = set()
        for node in iter_nodes(tree.root_node):
            if node.type != "import_spec":
                continue
            path_node = node.child_by_field_name("path")
            spec = _strip_quotes(node_text(path_node, data))
            if not spec or spec in seen:
                continue
            seen.add(spec)
            out.append(ImportRef(raw=node_text(node, data).strip(), spec=spec, kind=kind))
        return out

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        if not _is_build_context_active(text):
            return exports
        tree, data = parse_tree("go", text)
        if tree is None:
            return exports
        seen: set[str] = set()
        for node in iter_nodes(tree.root_node):
            kind = None
            name = ""
            if node.type in ("function_declaration", "method_declaration"):
                name_node = node.child_by_field_name("name")
                name = node_text(name_node, data)
                kind = "func"
            elif node.type == "type_spec":
                name_node = node.child_by_field_name("name")
                name = node_text(name_node, data)
                kind = "type"
            elif node.type in ("const_spec", "var_spec"):
                name_node = node.child_by_field_name("name")
                names = _extract_identifier_list(name_node, data)
                for nm in names:
                    if nm and nm[0].isupper() and nm not in seen:
                        seen.add(nm)
                        exports.append(nm)
                continue
            if kind and name and name[0].isupper() and name not in seen:
                seen.add(name)
                exports.append(name)
        return exports

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        out: list[SymbolDef] = []
        if not _is_build_context_active(text):
            return out
        tree, data = parse_tree("go", text)
        if tree is None:
            return out
        lines = text.splitlines()
        seen: set[tuple[str, str, int]] = set()
        include_unexported = bool(getattr(settings, "go_include_unexported_symbols", False))

        def _signature(line_no: int) -> str:
            if 1 <= line_no <= len(lines):
                return lines[line_no - 1].strip()
            return ""

        def _add(name: str, kind: str, line_no: int, end_line: int) -> None:
            if not name:
                return
            if not include_unexported and not name[0].isupper():
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
            if node.type in ("function_declaration", "method_declaration"):
                name = node_text(node.child_by_field_name("name"), data)
                ln = int(node.start_point[0]) + 1
                end_ln = int(node.end_point[0]) + 1
                _add(name, "func", ln, end_ln)
            elif node.type == "type_spec":
                name = node_text(node.child_by_field_name("name"), data)
                ln = int(node.start_point[0]) + 1
                end_ln = int(node.end_point[0]) + 1
                _add(name, "type", ln, end_ln)
            elif node.type in ("const_spec", "var_spec"):
                name_node = node.child_by_field_name("name")
                names = _extract_identifier_list(name_node, data)
                ln = int(node.start_point[0]) + 1
                end_ln = int(node.end_point[0]) + 1
                kind = "const" if node.type == "const_spec" else "var"
                for nm in names:
                    _add(nm, kind, ln, end_ln)
        return out

    def naive_complexity(self, text: str) -> int:
        return max(1, text.count("if ") + text.count("for ") + 1)
