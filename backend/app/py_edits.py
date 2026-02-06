# backend/app/py_edits.py
from __future__ import annotations

import ast
from typing import Any


def _line_offsets(lines: list[str]) -> list[int]:
    off = [0]
    s = 0
    for ln in lines:
        s += len(ln)
        off.append(s)
    return off


def _abs_pos(offsets: list[int], lineno: int, col: int) -> int:
    # lineno is 1-based
    li = max(1, int(lineno)) - 1
    if li < 0:
        li = 0
    if li >= len(offsets):
        li = len(offsets) - 1
    return int(offsets[li] + int(col or 0))


def _safe_existing_keys(d: ast.Dict) -> set[str]:
    keys: set[str] = set()
    for k in d.keys or []:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
        elif isinstance(k, ast.Str):
            keys.add(str(k.s))
    return keys


def _infer_element_indent(lines: list[str], start_line: int, end_line: int, close_col: int) -> str:
    # best-effort: use indentation of first key line; fallback to close-indent + 4 spaces
    s0 = max(1, int(start_line))
    e0 = max(s0, int(end_line))
    close_ln = lines[e0 - 1] if 1 <= e0 <= len(lines) else ""
    close_prefix = close_ln[: max(0, int(close_col) - 1)]
    close_indent = close_prefix[: len(close_prefix) - len(close_prefix.lstrip(" \t"))]

    for i in range(s0, min(e0, len(lines)) + 1):
        ln = lines[i - 1]
        if ":" in ln and ("'" in ln or '"' in ln):
            ind = ln[: len(ln) - len(ln.lstrip(" \t"))]
            if ind:
                return ind
    return close_indent + "    "


def _find_close_brace_pos(text: str, start_abs: int, end_abs: int) -> int:
    # end_abs is expected to be right after dict literal; we want index of '}'
    i = max(0, min(len(text), end_abs - 1))
    if 0 <= i < len(text) and text[i] == "}":
        return i
    # search backwards in the slice (best-effort)
    sub = text[start_abs:end_abs]
    j = sub.rfind("}")
    if j >= 0:
        return start_abs + j
    return max(0, min(len(text), end_abs - 1))


def py_add_keys_to_function_return_dicts(
    text: str,
    *,
    function_name: str,
    keys_to_add: dict[str, str],
) -> tuple[str, bool, list[str]]:
    if not isinstance(text, str) or not text:
        return (text, False, ["empty_text"])
    fn_name = (function_name or "").strip()
    if not fn_name:
        return (text, False, ["empty_function_name"])
    if not isinstance(keys_to_add, dict) or not keys_to_add:
        return (text, False, ["no_keys_to_add"])

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return (text, False, ["python_syntax_error"])

    fn_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            fn_node = node
            break
    if fn_node is None:
        return (text, False, ["function_not_found"])

    lines = text.splitlines(keepends=True)
    offsets = _line_offsets(lines)

    inserts: list[tuple[int, str]] = []
    warnings: list[str] = []

    class V(ast.NodeVisitor):
        def visit_Return(self, node: ast.Return) -> Any:
            v = node.value
            if isinstance(v, ast.Dict):
                existing = _safe_existing_keys(v)
                missing = [k for k in keys_to_add.keys() if k not in existing]
                if not missing:
                    return
                # need end positions
                end_ln = getattr(v, "end_lineno", None)
                end_col = getattr(v, "end_col_offset", None)
                start_ln = getattr(v, "lineno", None)
                start_col = getattr(v, "col_offset", None)
                if not (
                    isinstance(end_ln, int)
                    and isinstance(end_col, int)
                    and isinstance(start_ln, int)
                    and isinstance(start_col, int)
                ):
                    warnings.append("dict_missing_end_positions")
                    return

                start_abs = _abs_pos(offsets, start_ln, start_col)
                end_abs = _abs_pos(offsets, end_ln, end_col)
                close_abs = _find_close_brace_pos(text, start_abs, end_abs)

                # single-line vs multi-line
                if int(start_ln) == int(end_ln):
                    # inline insert before }
                    inner = text[start_abs:close_abs]
                    inner_has_items = ":" in inner
                    parts = []
                    for k in missing:
                        lit = keys_to_add.get(k, "None")
                        parts.append(f'"{k}": {lit}')
                    if not parts:
                        return
                    if inner_has_items:
                        ins = ", " + ", ".join(parts)
                    else:
                        ins = ", ".join(parts)
                    inserts.append((close_abs, ins))
                else:
                    # multiline: insert new lines before closing brace
                    elem_indent = _infer_element_indent(
                        lines, int(start_ln), int(end_ln), int(end_col)
                    )
                    add_lines = []
                    for k in missing:
                        lit = keys_to_add.get(k, "None")
                        add_lines.append(f'\n{elem_indent}"{k}": {lit},')
                    ins = "".join(add_lines)
                    inserts.append((close_abs, ins))
            # do not descend into nested functions
            return

    V().visit(fn_node)

    if not inserts:
        return (text, False, warnings or ["no_return_dicts_found"])

    # apply inserts from right to left
    inserts.sort(key=lambda x: x[0], reverse=True)
    new_text = text
    for pos, ins in inserts:
        p = max(0, min(len(new_text), int(pos)))
        new_text = new_text[:p] + ins + new_text[p:]

    changed = new_text != text
    return (new_text, changed, warnings)
