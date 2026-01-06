#backend/app/indexers/js_ts_indexer.py
from __future__ import annotations

import re
from pathlib import Path
from .base import ImportRef

IMPORT_RE = re.compile(
    r"""(?x)
    ^\s*
    (?:
      import\s+(?:type\s+)?[^;]*?\s+from\s+['"](?P<from1>[^'"]+)['"]\s*;? |
      import\s*\(\s*['"](?P<dyn>[^'"]+)['"]\s*\) |
      require\(\s*['"](?P<req>[^'"]+)['"]\s*\)
    )
    """,
    re.MULTILINE,
)

EXPORT_RE = re.compile(r"""(?x)
    ^\s*export\s+
    (?:
      default\s+ |
      (?:async\s+)?function\s+(?P<fn>[A-Za-z_$][\w$]*) |
      class\s+(?P<cls>[A-Za-z_$][\w$]*) |
      const\s+(?P<const>[A-Za-z_$][\w$]*) |
      let\s+(?P<let>[A-Za-z_$][\w$]*) |
      var\s+(?P<var>[A-Za-z_$][\w$]*) |
      \{\s*(?P<brace>[^}]+)\s*\}
    )
""", re.MULTILINE)

class JsTsIndexer:
    def language(self) -> str:
        return "js_ts"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        out: list[ImportRef] = []
        for m in IMPORT_RE.finditer(text):
            spec = m.group("from1") or m.group("dyn") or m.group("req")
            if not spec:
                continue
            out.append(ImportRef(raw=m.group(0).strip(), spec=spec, kind="runtime"))
        return out

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        for m in EXPORT_RE.finditer(text):
            for g in ("fn", "cls", "const", "let", "var"):
                v = m.group(g)
                if v:
                    exports.append(v)
            brace = m.group("brace")
            if brace:
                parts = [p.strip() for p in brace.split(",")]
                for p in parts:
                    if " as " in p:
                        exports.append(p.split(" as ")[-1].strip())
                    else:
                        exports.append(p.split(":")[0].strip())
        seen = set()
        out: list[str] = []
        for e in exports:
            if e and e not in seen:
                seen.add(e)
                out.append(e)
        return out

    def naive_complexity(self, text: str) -> int:
        keywords = ["if(", "if (", "for(", "for (", "while(", "while (", "&&", "||", "catch", "case "]
        c = 1
        low = text.lower()
        for k in keywords:
            c += low.count(k)
        return c
