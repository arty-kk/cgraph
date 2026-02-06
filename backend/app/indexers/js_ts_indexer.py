# backend/app/indexers/js_ts_indexer.py
from __future__ import annotations

import re
from pathlib import Path

from .base import ImportRef, SymbolDef
from .tree_sitter_utils import iter_nodes, node_text, parse_tree

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

DYNAMIC_IMPORT_RE = re.compile(
    r"""(?x)(?<![\w$])import\s*\(\s*(?:'(?P<dyn_sq>[^']+)'|"(?P<dyn_dq>[^"]+)"|`(?P<dyn_tpl>[^`]+)`)\s*\)"""
)
REQUIRE_RE = re.compile(r"""(?x)(?<![\w$])require\s*\(\s*['"](?P<req>[^'"]+)['"]\s*\)""")
DYNAMIC_CALL_RE = re.compile(r"""(?x)(?<![\w$])(?P<fn>import|require)\s*\(\s*(?P<arg>[^)]+)\)""")
DYNAMIC_SPEC_MARKER = "<dynamic>"

EXPORT_RE = re.compile(
    r"""(?x)
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
""",
    re.MULTILINE,
)

VUE_SCRIPT_TAG_RE = re.compile(r"""(?is)<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>""")
VUE_SCRIPT_LANG_RE = re.compile(r"""(?i)\blang\s*=\s*["']?([A-Za-z0-9_-]+)["']?""")
VUE_SCRIPT_SRC_RE = re.compile(r"""(?i)\bsrc\s*=\s*["']([^"']+)["']""")


def _strip_quotes(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"', "`"):
        return s[1:-1]
    return s


def _js_ts_language(path: Path) -> str:
    suf = (path.suffix or "").lower()
    if suf in (".ts", ".mts", ".cts"):
        return "typescript"
    if suf in (".tsx",):
        return "tsx"
    return "javascript"


def _vue_language(attrs: str) -> str | None:
    if not attrs:
        return None
    match = VUE_SCRIPT_LANG_RE.search(attrs)
    if not match:
        return None
    lang = match.group(1).strip().lower()
    if lang == "tsx":
        return "tsx"
    if lang in ("ts", "tsx", "typescript"):
        return "typescript"
    return "javascript"


def _extract_vue_scripts(text: str) -> tuple[str, list[str], str]:
    if not text:
        return "", [], "javascript"
    bodies: list[str] = []
    srcs: list[str] = []
    lang: str = "javascript"
    for match in VUE_SCRIPT_TAG_RE.finditer(text):
        attrs = match.group("attrs") or ""
        src_match = VUE_SCRIPT_SRC_RE.search(attrs)
        if src_match:
            src = src_match.group(1).strip()
            if src:
                srcs.append(src)
        body = match.group("body") or ""
        if body.strip():
            bodies.append(body)
        lang_hint = _vue_language(attrs)
        if lang_hint == "tsx":
            lang = "tsx"
        elif lang_hint == "typescript":
            lang = "typescript"
    return "\n".join(bodies).strip(), srcs, lang


def _prepare_js_source(file_path: Path, text: str) -> tuple[str, str, list[str]]:
    if file_path.suffix.lower() == ".vue":
        script_text, srcs, lang = _extract_vue_scripts(text)
        return lang, script_text, srcs
    return _js_ts_language(file_path), text, []


def _string_literal_value(node_text_raw: str) -> str:
    if not node_text_raw:
        return ""
    if "${" in node_text_raw:
        return ""
    return _strip_quotes(node_text_raw)


def _template_literal_value(node_text_raw: str) -> str:
    if not node_text_raw:
        return ""
    raw = node_text_raw.strip()
    if "${" in raw:
        return ""
    if len(raw) >= 2 and raw[0] == raw[-1] == "`":
        return raw[1:-1]
    return ""


def _all_type_only_specifiers(raw: str) -> bool:
    match = re.search(r"\{([^}]*)\}", raw)
    if not match:
        return False
    specs = [spec.strip() for spec in match.group(1).split(",") if spec.strip()]
    if not specs:
        return False
    for spec in specs:
        spec_norm = " ".join(spec.split())
        if not spec_norm.startswith("type "):
            return False
    return True


def _first_call_string_arg(node, data: bytes, *, allow_template: bool = False) -> str:
    args = None
    for ch in node.children:
        if ch.type in ("arguments", "argument_list"):
            args = ch
            break
    if args is None:
        args = node.child_by_field_name("arguments")
    if args is None:
        return ""
    for ch in args.children:
        if ch.type in ("string", "string_literal"):
            return _string_literal_value(node_text(ch, data))
        if ch.type in ("template_string", "template_literal"):
            if allow_template:
                return _template_literal_value(node_text(ch, data))
            return ""
    return ""


def _first_call_arg(node):
    args = None
    for ch in node.children:
        if ch.type in ("arguments", "argument_list"):
            args = ch
            break
    if args is None:
        args = node.child_by_field_name("arguments")
    if args is None:
        return None
    for ch in args.children:
        if ch.is_named:
            return ch
    return None


def _is_dynamic_call_arg(node, data: bytes, *, allow_template: bool) -> bool:
    first_arg = _first_call_arg(node)
    if first_arg is None:
        return False
    if first_arg.type in ("string", "string_literal"):
        return False
    if first_arg.type in ("template_string", "template_literal"):
        if not allow_template:
            return True
        return _template_literal_value(node_text(first_arg, data)) == ""
    return True


def _first_string_literal(node, data: bytes) -> str:
    if node is None:
        return ""
    for ch in iter_nodes(node):
        if ch.type in ("string", "string_literal", "template_string", "template_literal"):
            return _string_literal_value(node_text(ch, data))
    return ""


class JsTsIndexer:
    def language(self) -> str:
        return "js_ts"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        out: list[ImportRef] = []
        seen: set[tuple[str, str]] = set()
        lang, source_text, vue_srcs = _prepare_js_source(file_path, text)
        tree, data = parse_tree(lang, source_text)

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
                if node.type in ("import_statement", "import_declaration"):
                    raw = node_text(node, data).strip()
                    source = node.child_by_field_name("source")
                    spec = _string_literal_value(node_text(source, data))
                    raw_l = raw.lstrip()
                    is_type_only = raw_l.startswith("import type") or _all_type_only_specifiers(raw)
                    kind = "type" if is_type_only else "runtime"
                    _add(raw, spec, kind)
                    continue
                if node.type in ("export_statement", "export_declaration"):
                    source = node.child_by_field_name("source")
                    if source is not None:
                        raw = node_text(node, data).strip()
                        spec = _string_literal_value(node_text(source, data))
                        raw_l = raw.lstrip()
                        is_type_only = raw_l.startswith("export type") or _all_type_only_specifiers(
                            raw
                        )
                        kind = "type_reexport" if is_type_only else "reexport"
                        _add(raw, spec, kind)
                    continue
                if node.type in ("call_expression", "import_call"):
                    raw = node_text(node, data).strip()
                    func = node.child_by_field_name("function")
                    func_name = node_text(func, data).strip()
                    if node.type == "import_call" or func_name in ("import", "require"):
                        allow_template = node.type == "import_call" or func_name == "import"
                        spec = _first_call_string_arg(node, data, allow_template=allow_template)
                        if spec:
                            _add(raw, spec, "runtime")
                        elif _is_dynamic_call_arg(node, data, allow_template=allow_template):
                            _add(raw, DYNAMIC_SPEC_MARKER, "runtime_dynamic")
                    continue
                if node.type in ("import_assignment", "import_equals_declaration"):
                    raw = node_text(node, data).strip()
                    spec = _first_string_literal(node, data)
                    if spec:
                        _add(raw, spec, "runtime")
                    continue

        if not out:
            cleaned = _strip_js_comments(source_text)
            for m in STATIC_FROM_RE.finditer(cleaned):
                spec = (m.group("from1") or m.group("from2") or "").strip()
                if not spec:
                    continue
                raw = m.group(0).strip()
                is_export = raw.lstrip().startswith("export")
                is_type = bool(
                    m.group("import_type")
                    or m.group("export_type")
                    or _all_type_only_specifiers(raw)
                )
                if is_export:
                    kind = "type_reexport" if is_type else "reexport"
                else:
                    kind = "type" if is_type else "runtime"
                _add(raw, spec, kind)

            for m in SIDE_EFFECT_IMPORT_RE.finditer(cleaned):
                spec = (m.group("side") or "").strip()
                if spec:
                    _add(m.group(0).strip(), spec, "runtime")

            for m in IMPORT_EQUALS_RE.finditer(cleaned):
                spec = (m.group("req") or "").strip()
                if spec:
                    _add(m.group(0).strip(), spec, "runtime")

            for m in DYNAMIC_IMPORT_RE.finditer(cleaned):
                spec = (m.group("dyn_sq") or m.group("dyn_dq") or m.group("dyn_tpl") or "").strip()
                if spec and "${" not in spec:
                    _add(m.group(0).strip(), spec, "runtime")

            for m in REQUIRE_RE.finditer(cleaned):
                spec = (m.group("req") or "").strip()
                if spec:
                    _add(m.group(0).strip(), spec, "runtime")

            for m in DYNAMIC_CALL_RE.finditer(cleaned):
                raw = m.group(0).strip()
                arg = (m.group("arg") or "").strip()
                if not arg:
                    continue
                if arg[0] in ("'", '"') and len(arg) >= 2 and arg[-1] == arg[0]:
                    continue
                if arg[0] == "`" and arg.endswith("`") and "${" not in arg:
                    continue
                _add(raw, DYNAMIC_SPEC_MARKER, "runtime_dynamic")
        for src in vue_srcs:
            _add(f'script src="{src}"', src, "runtime")
        return out

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        lang, source_text, _vue_srcs = _prepare_js_source(file_path, text)
        tree, data = parse_tree(lang, source_text)
        snippets: list[str] = []
        if tree is not None:
            for node in iter_nodes(tree.root_node):
                if node.type in ("export_statement", "export_declaration"):
                    snippets.append(node_text(node, data))
        else:
            snippets = [source_text]

        for snippet in snippets:
            for m in EXPORT_RE.finditer(snippet):
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
        lang, source_text, _vue_srcs = _prepare_js_source(file_path, text)
        lines = source_text.splitlines()
        tree, data = parse_tree(lang, source_text)

        def _line_text(line_no: int) -> str:
            if 1 <= line_no <= len(lines):
                return lines[line_no - 1].strip()
            return ""

        def _add(name: str, kind: str, line_no: int) -> None:
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
                    signature=_line_text(line_no),
                    doc="",
                    start_line=int(line_no),
                    end_line=int(line_no),
                )
            )

        def _extract_binding_names(node) -> list[str]:
            if node is None:
                return []
            names: list[str] = []
            for ch in iter_nodes(node):
                if ch.type in (
                    "identifier",
                    "binding_identifier",
                    "property_identifier",
                    "shorthand_property_identifier",
                    "type_identifier",
                ):
                    name = node_text(ch, data)
                    if name:
                        names.append(name)
            return names

        def _collect_var_names(node) -> list[str]:
            names: list[str] = []
            for ch in node.children:
                if ch.type == "variable_declarator":
                    name_node = ch.child_by_field_name("name")
                    names.extend(_extract_binding_names(name_node))
            return names

        def _collect_top_level(node) -> None:
            if node.type == "function_declaration":
                name = node_text(node.child_by_field_name("name"), data)
                _add(name, "function", int(node.start_point[0]) + 1)
                return
            if node.type == "class_declaration":
                name = node_text(node.child_by_field_name("name"), data)
                _add(name, "class", int(node.start_point[0]) + 1)
                return
            if node.type in ("lexical_declaration", "variable_declaration"):
                line_no = int(node.start_point[0]) + 1
                for name in _collect_var_names(node):
                    _add(name, "variable", line_no)
                return
            if node.type in ("export_statement", "export_declaration"):
                for ch in node.children:
                    _collect_top_level(ch)

        snippets: list[tuple[str, int]] = []
        if tree is not None:
            for node in tree.root_node.children:
                _collect_top_level(node)
            for node in iter_nodes(tree.root_node):
                if node.type in ("export_statement", "export_declaration"):
                    ln = int(node.start_point[0]) + 1
                    snippets.append((node_text(node, data), ln))
        else:
            snippets = [(source_text, 1)]

        for snippet, ln in snippets:
            _line_text(ln)

            for m in EXPORT_RE.finditer(snippet):
                if m.group("d_fn") or m.group("fn"):
                    _add(m.group("d_fn") or m.group("fn") or "", "function", ln)
                if m.group("d_cls") or m.group("cls"):
                    _add(m.group("d_cls") or m.group("cls") or "", "class", ln)
                if m.group("const") or m.group("let") or m.group("var"):
                    _add(m.group("const") or m.group("let") or m.group("var") or "", "variable", ln)

                if m.group("intf"):
                    _add(m.group("intf") or "", "interface", ln)
                if m.group("type_alias"):
                    _add(m.group("type_alias") or "", "type", ln)
                if m.group("enum"):
                    _add(m.group("enum") or "", "enum", ln)
                if m.group("namespace"):
                    _add(m.group("namespace") or "", "namespace", ln)
                if m.group("star_as"):
                    _add(m.group("star_as") or "", "reexport_namespace", ln)

                raw = (m.group(0) or "").strip()
                if raw.lstrip().startswith("export default"):
                    _add("default", "default", ln)

                brace = m.group("brace")
                if brace:
                    parts = [p.strip() for p in brace.split(",")]
                    for p in parts:
                        if p.startswith("type "):
                            p = p[5:].strip()
                        if p.startswith("typeof "):
                            p = p[7:].strip()
                        if " as " in p:
                            _add(p.split(" as ")[-1].strip(), "reexport", ln)
                        else:
                            _add(p.split(":")[0].strip(), "reexport", ln)
        return out

    def naive_complexity(self, text: str) -> int:
        source_text = text
        if isinstance(text, str):
            source_text, _vue_srcs, _lang = _extract_vue_scripts(text)
            if not source_text:
                source_text = text
        keywords = [
            "if(",
            "if (",
            "for(",
            "for (",
            "while(",
            "while (",
            "&&",
            "||",
            "catch",
            "case ",
        ]
        c = 1
        low = source_text.lower()
        for k in keywords:
            c += low.count(k)
        return c
