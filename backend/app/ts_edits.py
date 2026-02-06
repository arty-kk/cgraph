# backend/app/ts_edits.py
import difflib
import re
from typing import Any


def unified_diff(rel_path: str, old_text: str, new_text: str) -> str:
    if old_text == new_text:
        return ""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    a = f"a/{rel_path}"
    b = f"b/{rel_path}"
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=a, tofile=b)
    return "".join(diff)


_TYPE_START_RE = re.compile(
    r"(?m)^\s*export\s+(?P<kind>type|interface)\s+(?P<name>[A-Za-z_$][\w$]*)\b[^{=]*?(?:=)?\s*\{"
)

_TS_FIELD_RE = re.compile(
    r"(?m)^\s*(?P<name>[A-Za-z_$][\w$]*)\s*(?P<opt>\?)?\s*:\s*(?P<typ>[^;,\n]+)"
)


def _extract_brace_block(text: str, brace_pos: int) -> tuple[int, int] | None:
    # returns (start, end) indices of '{...}' inclusive braces
    s = text
    if brace_pos < 0 or brace_pos >= len(s) or s[brace_pos] != "{":
        return None
    i = brace_pos
    depth = 0
    in_str: str | None = None
    esc = False
    while i < len(s):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
            i += 1
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


def _infer_indent(block: str) -> str:
    # find indentation from existing field lines; default 2 spaces
    for line in block.splitlines():
        m = re.match(r"^(\s+)[A-Za-z_$][\w$]*\s*\??\s*:", line)
        if m:
            return m.group(1)
    return "  "


def _py_type_to_ts(py: str) -> str:
    t = (py or "").strip()
    if not t:
        return "any"
    base = t
    # Optional[T]
    if base.startswith("Optional[") and base.endswith("]"):
        base = base[len("Optional[") : -1].strip()
    mapping = {
        "str": "string",
        "int": "number",
        "float": "number",
        "bool": "boolean",
        "dict": "Record<string, any>",
        "list": "any[]",
        "Any": "any",
        "object": "any",
    }
    if base in mapping:
        return mapping[base]
    # list[T]
    if base.startswith("list[") and base.endswith("]"):
        return "any[]"
    if base.startswith("List[") and base.endswith("]"):
        return "any[]"
    return "any"


def ts_add_fields_to_typedef(
    text: str,
    type_name: str,
    fields_to_add: list[dict[str, Any]],
    *,
    optional: bool,
) -> tuple[str, bool, str]:
    if not type_name or not isinstance(type_name, str):
        return (text, False, "bad_type_name")

    # find the target definition
    m_target = None
    for m in _TYPE_START_RE.finditer(text):
        if (m.group("name") or "") == type_name:
            m_target = m
            break
    if m_target is None:
        return (text, False, "type_not_found")

    brace_pos = text.find("{", m_target.end() - 1)
    if brace_pos < 0:
        return (text, False, "brace_not_found")
    blk = _extract_brace_block(text, brace_pos)
    if not blk:
        return (text, False, "brace_block_not_found")
    s0, e0 = blk
    block = text[s0:e0]

    existing: set[str] = set()
    for fm in _TS_FIELD_RE.finditer(block):
        nm = (fm.group("name") or "").strip()
        if nm:
            existing.add(nm)

    additions: list[tuple[str, str]] = []
    for f in fields_to_add or []:
        if not isinstance(f, dict):
            continue
        nm = str(f.get("name") or "").strip()
        if not nm or nm in existing:
            continue
        typ_raw = str(f.get("type") or "").strip()
        ts_typ = _py_type_to_ts(typ_raw)
        additions.append((nm, ts_typ))

    if not additions:
        return (text, False, "no_new_fields")

    indent = _infer_indent(block)

    # insert before closing brace
    insert_lines: list[str] = []
    for nm, ts_typ in additions:
        opt = "?" if optional else ""
        insert_lines.append(f"{indent}{nm}{opt}: {ts_typ}\n")

    # ensure block ends with newline before "}"
    # find position of last "}" in block
    close_i = block.rfind("}")
    before = block[:close_i]
    after = block[close_i:]
    if before and not before.endswith("\n"):
        before += "\n"
    new_block = before + "".join(insert_lines) + after

    new_text = text[:s0] + new_block + text[e0:]
    return (new_text, True, "ok")


_IMPORT_RE = re.compile(r"(?m)^\s*import\s+.*?;\s*$")
_ENCODE_IMPORT_RE = re.compile(
    r"(?m)^\s*import\s+\{\s*([^}]+)\s*\}\s*from\s*['\"]\./utils['\"]\s*;"
)
_FN_RE = re.compile(
    r"(?ms)^\s*export\s+(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^)]*)\)\s*:\s*(?P<ret>[^ {;\n]+)?\s*\{"
)
_FN_RE2 = re.compile(
    r"(?ms)^\s*export\s+(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^)]*)\)\s*\{"
)


def _find_function_block(text: str, fn_name: str) -> tuple[int, int, int, int] | None:
    # returns (sig_start, params_start, params_end, block_end)
    m = None
    for rx in (_FN_RE, _FN_RE2):
        for mm in rx.finditer(text):
            if (mm.group("name") or "") == fn_name:
                m = mm
                break
        if m:
            break
    if not m:
        return None
    # params span
    params_start = m.start("params")
    params_end = m.end("params")
    # find block start "{"
    brace_pos = text.find("{", m.end() - 1)
    if brace_pos < 0:
        return None
    blk = _extract_brace_block(text, brace_pos)
    if not blk:
        return None
    b0, b1 = blk
    return (m.start(), params_start, params_end, b1)


def _param_names_from_paramlist(params: str) -> set[str]:
    names: set[str] = set()
    for part in (params or "").split(","):
        s = part.strip()
        if not s or s.startswith("{") or s.startswith("["):
            continue
        # strip default
        if "=" in s:
            s = s.split("=", 1)[0].strip()
        # name?: type
        if ":" in s:
            left = s.split(":", 1)[0].strip()
        else:
            left = s
        if left.endswith("?"):
            left = left[:-1].strip()
        if left:
            names.add(left)
    return names


def _ensure_encodepath_import(text: str) -> tuple[str, bool]:
    # If encodePath is already imported, do nothing.
    if "encodePath" in text and _ENCODE_IMPORT_RE.search(text):
        # Might still not include encodePath in destructured import; check.
        m = _ENCODE_IMPORT_RE.search(text)
        if m:
            items = [x.strip() for x in (m.group(1) or "").split(",") if x.strip()]
            if "encodePath" in items:
                return (text, False)
            # add to existing import list
            new_items = items + ["encodePath"]
            repl = f"import {{ {', '.join(new_items)} }} from './utils';"
            new_text = text[: m.start()] + repl + text[m.end() :]
            return (new_text, True)
    # If there is a utils import but not encodePath, add it.
    m = _ENCODE_IMPORT_RE.search(text)
    if m:
        items = [x.strip() for x in (m.group(1) or "").split(",") if x.strip()]
        if "encodePath" in items:
            return (text, False)
        new_items = items + ["encodePath"]
        repl = f"import {{ {', '.join(new_items)} }} from './utils';"
        new_text = text[: m.start()] + repl + text[m.end() :]
        return (new_text, True)

    # else insert new import after last import line
    imports = list(_IMPORT_RE.finditer(text))
    ins_line = "import { encodePath } from './utils';\n"
    if imports:
        last = imports[-1]
        pos = last.end()
        new_text = text[:pos] + "\n" + ins_line + text[pos:]
        return (new_text, True)
    # no imports, add at top
    return (ins_line + "\n" + text, True)


def _replace_first_api_call_path(
    block: str, method: str, new_path_literal: str
) -> tuple[str, bool, str]:
    m = (method or "").strip().lower()
    if not m:
        return (block, False, "no_method")
    # find api.<m>(  with whitespace
    rx = re.compile(rf"api\s*\.\s*{re.escape(m)}\s*\(\s*", re.MULTILINE)
    mm = rx.search(block)
    if not mm:
        return (block, False, "api_call_not_found")
    i = mm.end()
    if i >= len(block):
        return (block, False, "bad_call_pos")
    ch = block[i]
    if ch not in ("'", '"', "`"):
        return (block, False, "first_arg_not_string_literal")
    quote = ch
    j = i + 1
    esc = False
    while j < len(block):
        c = block[j]
        if quote != "`":
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                break
        else:
            # backtick: allow \` escape
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == "`":
                break
        j += 1
    if j >= len(block):
        return (block, False, "unterminated_string")
    block[i : j + 1]
    new_block = block[:i] + new_path_literal + block[j + 1 :]
    return (new_block, True, "ok")


def ts_patch_wrapper_function(
    text: str,
    *,
    fn_name: str,
    http_method: str,
    new_path_literal: str,
    add_params: list[dict[str, Any]],
) -> tuple[str, bool, list[str]]:
    """
    - Ensure signature contains missing params (insert before trailing params?: ... if exists).
    - Replace first api.<method>(<path-literal>...) with new path literal.
    - Ensure encodePath import if needed by new_path_literal.
    """
    warnings: list[str] = []
    loc = _find_function_block(text, fn_name)
    if not loc:
        return (text, False, ["function_not_found"])
    sig_start, ps0, ps1, block_end = loc
    params_str = text[ps0:ps1]
    existing = _param_names_from_paramlist(params_str)

    # Build missing param strings
    inserts: list[str] = []
    for p in add_params or []:
        if not isinstance(p, dict):
            continue
        nm = str(p.get("name") or "").strip()
        if not nm:
            continue
        ts_type = str(p.get("type") or "string").strip() or "string"
        if nm in existing:
            continue
        inserts.append(f"{nm}: {ts_type}")

    new_params_str = params_str
    if inserts:
        # keep params?: ... last if present
        # naive: split by commas, but preserve original formatting; we inject before "params?"
        # token if present
        if "params?:" in params_str or "params ?:" in params_str:
            idx = params_str.find("params")
            head = params_str[:idx].rstrip()
            tail = params_str[idx:].lstrip()
            if head and not head.rstrip().endswith(","):
                head = head.rstrip() + ", "
            head = head + ", ".join(inserts) + ", "
            new_params_str = head + tail
        else:
            if params_str.strip():
                new_params_str = params_str.rstrip()
                if not new_params_str.rstrip().endswith(","):
                    new_params_str = new_params_str.rstrip() + ", "
                new_params_str = new_params_str + ", ".join(inserts)
            else:
                new_params_str = ", ".join(inserts)

    # Replace in whole text
    new_text = text[:ps0] + new_params_str + text[ps1:]

    # Now replace path literal inside the function block (use updated text)
    loc2 = _find_function_block(new_text, fn_name)
    if not loc2:
        return (new_text, True, ["function_loc_changed_unexpectedly"])
    _sig_start2, _ps0b, _ps1b, block_end2 = loc2
    # extract function block substring
    brace_pos = new_text.find("{", _ps1b)
    if brace_pos < 0:
        return (new_text, True, ["brace_not_found"])
    blk = _extract_brace_block(new_text, brace_pos)
    if not blk:
        return (new_text, True, ["brace_block_not_found"])
    b0, b1 = blk
    block = new_text[b0:b1]
    patched_block, ok, reason = _replace_first_api_call_path(block, http_method, new_path_literal)
    if not ok:
        warnings.append(reason)
    else:
        new_text = new_text[:b0] + patched_block + new_text[b1:]

    # Ensure encodePath import if needed
    if "encodePath(" in new_path_literal:
        new_text, changed = _ensure_encodepath_import(new_text)
        if changed:
            warnings.append("added_encodePath_import")

    changed_any = new_text != text
    return (new_text, changed_any, warnings)
