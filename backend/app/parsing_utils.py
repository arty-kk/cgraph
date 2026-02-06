# backend/app/parsing_utils.py
"""Utility helpers for extracting brace blocks from code-like text."""
from __future__ import annotations


def extract_brace_block(text: str, brace_pos: int) -> tuple[int, int] | None:
    """Return (start, end) indices for a {...} block starting at brace_pos."""
    if not isinstance(text, str):
        return None
    if brace_pos < 0 or brace_pos >= len(text) or text[brace_pos] != "{":
        return None

    i = brace_pos
    depth = 0
    in_str: str | None = None
    esc = False
    in_line_comment = False
    in_block_comment = False

    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        if ch in ("'", '"', "`"):
            in_str = ch
            i += 1
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return (brace_pos, i + 1)
        i += 1

    return None
