#backend/app/indexers/go_indexer.py
from __future__ import annotations

import re
from pathlib import Path
from .generic_indexer import GenericIndexer, GO_BLOCK_COMMENT_RE, GO_LINE_COMMENT_RE
from .base import SymbolDef


class GoIndexer(GenericIndexer):
    def language(self) -> str:
        return "go"

    def parse_imports(self, file_path: Path, text: str):
        return super().parse_imports(file_path, text)

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        cleaned = GO_BLOCK_COMMENT_RE.sub("", text)
        cleaned = GO_LINE_COMMENT_RE.sub("", cleaned)
        pattern = re.compile(
            r"""(?mx)
            ^\s*(?:
                func\s+(?:\([^)]*\)\s+)?
                |type\s+
                |const\s+
                |var\s+
            )
            (?P<name>[A-Z][A-Za-z0-9_]*)
            """
        )

        exports: list[str] = []
        seen: set[str] = set()
        for m in pattern.finditer(cleaned):
            name = (m.group("name") or "").strip()
            if name and name not in seen:
                seen.add(name)
                exports.append(name)
        return exports

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        cleaned = GO_BLOCK_COMMENT_RE.sub("", text)
        cleaned = GO_LINE_COMMENT_RE.sub("", cleaned)
        pattern = re.compile(
            r"""(?mx)
            ^\s*(?P<kind>func|type|const|var)\s+
            (?:\([^)]*\)\s+)?
            (?P<name>[A-Z][A-Za-z0-9_]*)
            """
        )
        out: list[SymbolDef] = []
        seen: set[tuple[str, str]] = set()
        for m in pattern.finditer(cleaned):
            kind = (m.group("kind") or "").strip()
            name = (m.group("name") or "").strip()
            if not kind or not name:
                continue
            key = (kind, name)
            if key in seen:
                continue
            seen.add(key)
            start = cleaned.count("\n", 0, m.start()) + 1
            line_start = cleaned.rfind("\n", 0, m.start())
            line_start = 0 if line_start < 0 else (line_start + 1)
            line_end = cleaned.find("\n", m.start())
            line_end = len(cleaned) if line_end < 0 else line_end
            sig = cleaned[line_start:line_end].strip()
            out.append(
                SymbolDef(
                    name=name,
                    kind=kind,
                    signature=sig,
                    doc="",
                    start_line=int(start),
                    end_line=int(start),
                )
            )
        return out

    def naive_complexity(self, text: str) -> int:
        return max(1, text.count("if ") + text.count("for ") + 1)

