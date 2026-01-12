#backend/app/indexers/js_ts_indexer.py
from __future__ import annotations

import re
from pathlib import Path
from .base import ImportRef, SymbolDef

JS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
JS_LINE_COMMENT_RE = re.compile(r"//.*?$", re.MULTILINE)

def _strip_js_comments(text: str) -> str:
    text = JS_BLOCK_COMMENT_RE.sub("", text)
    text = JS_LINE_COMMENT_RE.sub("", text)
    return text

STATIC_FROM_RE = re.compile(
    r"""(?mx)
    ^\s*(?:
      import\s+(?P<import_type>type\s+)?[^;]*?\s+from\s+['"](?P<from1>[^'"]+)['"]\s*;? |
      export\s+(?P<export_type>type\s+)?[^;]*?\s+from\s+['"](?P<from2>[^'"]+)['"]\s*;?
    )
    """
)

SIDE_EFFECT_IMPORT_RE = re.compile(
    r"""(?mx)
    ^\s*import\s+['"](?P<side>[^'"]+)['"]\s*;?
    """
)

IMPORT_EQUALS_RE = re.compile(
    r"""(?mx)
    ^\s*import\s+
    (?P<name>[A-Za-z_$][\w$]*)\s*=\s*require\s*\(\s*['"](?P<req>[^'"]+)['"]\s*\)\s*;?
    """
)

DYNAMIC_IMPORT_RE = re.compile(r"""(?x)(?<![\w$])import\s*\(\s*['"](?P<dyn>[^'"]+)['"]\s*\)""")
REQUIRE_RE = re.compile(r"""(?x)(?<![\w$])require\s*\(\s*['"](?P<req>[^'"]+)['"]\s*\)""")

EXPORT_RE = re.compile(r"""(?x)
    ^\s*export\s+
    (?:
      default\s+(?:async\s+)?function\s+(?P<d_fn>[A-Za-z_$][\w$]*) |
      default\s+class\s+(?P<d_cls>[A-Za-z_$][\w$]*) |
      default\s+ |
      (?:async\s+)?function\s+(?P<fn>[A-Za-z_$][\w$]*) |
      (?:abstract\s+)?class\s+(?P<cls>[A-Za-z_$][\w$]*) |
      interface\s+(?P<intf>[A-Za-z_$][\w$]*) |
      type\s+(?P<type_alias>[A-Za-z_$][\w$]*) |
      enum\s+(?P<enum>[A-Za-z_$][\w$]*) |
      namespace\s+(?P<namespace>[A-Za-z_$][\w$]*) |
      const\s+(?P<const>[A-Za-z_$][\w$]*) |
      let\s+(?P<let>[A-Za-z_$][\w$]*) |
      var\s+(?P<var>[A-Za-z_$][\w$]*) |
      \*\s*as\s+(?P<star_as>[A-Za-z_$][\w$]*) |
      (?:type\s+)?\{\s*(?P<brace>[^}]+)\s*\}
    )
""", re.MULTILINE)

class JsTsIndexer:
    def language(self) -> str:
        return "js_ts"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        out: list[ImportRef] = []
        cleaned = _strip_js_comments(text)
        seen: set[tuple[str, str]] = set()

        for m in STATIC_FROM_RE.finditer(cleaned):
            spec = (m.group("from1") or m.group("from2") or "").strip()
            if not spec:
                continue
            raw = m.group(0).strip()
            is_export = raw.lstrip().startswith("export")
            is_type = bool(m.group("import_type") or m.group("export_type"))
            if is_export:
                kind = "type_reexport" if is_type else "reexport"
            else:
                kind = "type" if is_type else "runtime"
            key = (kind, spec)
            if key in seen:
                continue
            seen.add(key)
            out.append(ImportRef(raw=raw, spec=spec, kind=kind))
 
        for m in SIDE_EFFECT_IMPORT_RE.finditer(cleaned):
            spec = (m.group("side") or "").strip()
            if not spec:
                continue
            key = ("runtime", spec)
            if key in seen:
                continue
            seen.add(key)
            out.append(ImportRef(raw=m.group(0).strip(), spec=spec, kind="runtime"))

        for m in IMPORT_EQUALS_RE.finditer(cleaned):
            spec = (m.group("req") or "").strip()
            if not spec:
                continue
            key = ("runtime", spec)
            if key in seen:
                continue
            seen.add(key)
            out.append(ImportRef(raw=m.group(0).strip(), spec=spec, kind="runtime"))

        for m in DYNAMIC_IMPORT_RE.finditer(cleaned):
            spec = (m.group("dyn") or "").strip()
            if not spec:
                continue
            key = ("runtime", spec)
            if key in seen:
                continue
            seen.add(key)
            out.append(ImportRef(raw=m.group(0).strip(), spec=spec, kind="runtime"))

        for m in REQUIRE_RE.finditer(cleaned):
            spec = (m.group("req") or "").strip()
            if not spec:
                continue
            key = ("runtime", spec)
            if key in seen:
                continue
            seen.add(key)
            out.append(ImportRef(raw=m.group(0).strip(), spec=spec, kind="runtime"))
        return out

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        for m in EXPORT_RE.finditer(text):
            raw = (m.group(0) or "").strip()
            for g in ("d_fn", "d_cls", "fn", "cls", "const", "let", "var"):
                v = m.group(g)
                if v:
                    exports.append(v)
            for g in ("intf", "type_alias", "enum", "namespace", "star_as"):
                v = m.group(g)
                if v:
                    exports.append(v)
            if raw.lstrip().startswith("export default"):
                exports.append("default")
            brace = m.group("brace")
            if brace:
                parts = [p.strip() for p in brace.split(",")]
                for p in parts:
                    if p.startswith("type "):
                        p = p[5:].strip()
                    if p.startswith("typeof "):
                        p = p[7:].strip()
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

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        out: list[SymbolDef] = []
        seen: set[tuple[str, str, int]] = set()

        def _line_no(pos: int) -> int:
            return text.count("\n", 0, max(0, pos)) + 1

        def _line_text(pos: int) -> str:
            s0 = text.rfind("\n", 0, max(0, pos))
            s0 = 0 if s0 < 0 else (s0 + 1)
            e0 = text.find("\n", max(0, pos))
            e0 = len(text) if e0 < 0 else e0
            return text[s0:e0].strip()

        for m in EXPORT_RE.finditer(text):
            ln = _line_no(m.start())
            sig = _line_text(m.start())

            def _add(name: str, kind: str) -> None:
                if not name:
                    return
                key = (kind, name, ln)
                if key in seen:
                    return
                seen.add(key)
                out.append(
                    SymbolDef(
                        name=name,
                        kind=kind,
                        signature=sig,
                        doc="",
                        start_line=int(ln),
                        end_line=int(ln),
                    )
                )

            if m.group("d_fn") or m.group("fn"):
                _add(m.group("d_fn") or m.group("fn") or "", "function")
            if m.group("d_cls") or m.group("cls"):
                _add(m.group("d_cls") or m.group("cls") or "", "class")
            if m.group("const") or m.group("let") or m.group("var"):
                _add(m.group("const") or m.group("let") or m.group("var") or "", "variable")

            if m.group("intf"):
                _add(m.group("intf") or "", "interface")
            if m.group("type_alias"):
                _add(m.group("type_alias") or "", "type")
            if m.group("enum"):
                _add(m.group("enum") or "", "enum")
            if m.group("namespace"):
                _add(m.group("namespace") or "", "namespace")
            if m.group("star_as"):
                _add(m.group("star_as") or "", "reexport_namespace")

            raw = (m.group(0) or "").strip()
            if raw.lstrip().startswith("export default"):
                _add("default", "default")

            brace = m.group("brace")
            if brace:
                parts = [p.strip() for p in brace.split(",")]
                for p in parts:
                    if p.startswith("type "):
                        p = p[5:].strip()
                    if p.startswith("typeof "):
                        p = p[7:].strip()
                    if " as " in p:
                        _add(p.split(" as ")[-1].strip(), "reexport")
                    else:
                        _add(p.split(":")[0].strip(), "reexport")
        return out


    def naive_complexity(self, text: str) -> int:
        keywords = ["if(", "if (", "for(", "for (", "while(", "while (", "&&", "||", "catch", "case "]
        c = 1
        low = text.lower()
        for k in keywords:
            c += low.count(k)
        return c
