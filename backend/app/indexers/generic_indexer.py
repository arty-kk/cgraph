# backend/app/indexers/generic_indexer.py
from __future__ import annotations

import re
from pathlib import Path

from .base import ImportRef, SymbolDef

GEN_IMPORT_RE = re.compile(
    r"""(?x)
^\s*(?:
    import\s+.+?from\s+['"](?P<js>[^'"]+)['"] |
    from\s+(?P<py>[\w\.\/]+)\s+import\s+ |
    # C/C++ includes
    \#include\s+[<"](?P<inc>[^>"]+)[>"] |
    # Java/Kotlin
    import\s+(?P<java>[\w\.]+)\s*;?
)
""",
    re.MULTILINE,
)

GO_IMPORT_BLOCK_RE = re.compile(
    r"""(?msx)
    ^\s*import\s*\(\s*
    (?P<body>.*?)
    ^\s*\)\s*
    """,
)

GO_IMPORT_SINGLE_RE = re.compile(
    r"""(?mx)
    ^\s*import\s+
    (?!\()
    (?:(?:[A-Za-z_]\w*|_|\.)\s+)?
    ["`](?P<pkg>[^"`]+)["`]
    """,
)

GO_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
GO_LINE_COMMENT_RE = re.compile(r"//.*?$", re.MULTILINE)


class GenericIndexer:
    def language(self) -> str:
        return "unknown"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        out: list[ImportRef] = []
        seen: set[tuple[str, str]] = set()

        def _add(raw: str, spec: str, kind: str = "import") -> None:
            spec_n = (spec or "").strip()
            if not spec_n:
                return
            key = (kind, spec_n)
            if key in seen:
                return
            seen.add(key)
            out.append(ImportRef(raw=raw, spec=spec_n, kind=kind))

        def _strip_go_comments(s: str) -> str:
            s = GO_BLOCK_COMMENT_RE.sub("", s)
            s = GO_LINE_COMMENT_RE.sub("", s)
            return s

        is_go = (file_path.suffix or "").lower() == ".go"
        if is_go:
            for bm in GO_IMPORT_BLOCK_RE.finditer(text):
                raw = "import (...)"
                body = bm.group("body") or ""
                body = _strip_go_comments(body)
                pkgs = re.findall(r"""["`]([^"`]+)["`]""", body)
                for pkg in pkgs:
                    _add(raw=raw, spec=pkg, kind="import")

            text_wo_blocks = GO_IMPORT_BLOCK_RE.sub("\n", text)

            for sm in GO_IMPORT_SINGLE_RE.finditer(text_wo_blocks):
                pkg = (sm.group("pkg") or "").strip()
                if pkg:
                    _add(raw=sm.group(0).strip(), spec=pkg, kind="import")
        else:
            text_wo_blocks = text

        for m in GEN_IMPORT_RE.finditer(text_wo_blocks):
            raw = m.group(0).strip()
            spec = m.group("js") or m.group("py") or m.group("inc") or m.group("java") or ""
            if spec:
                _add(raw=raw, spec=spec, kind="import")

        return out

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        return []

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        return []

    def naive_complexity(self, text: str) -> int:
        return 1
