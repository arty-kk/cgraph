# backend/app/api_contracts.py
from __future__ import annotations

import ast
import json
import re
from typing import Any

from .api_scaffold import parse_backend_path_params
from .parsing_utils import extract_brace_block

_IGNORED_PARAM_NAMES = {"request", "background_tasks", "response", "s", "session"}


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    unparse = getattr(ast, "unparse", None)
    if callable(unparse):
        try:
            return str(unparse(node))
        except Exception:
            return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _safe_unparse(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


_TYPING_WRAPPERS = {"Optional", "Union", "Annotated"}


def _model_name_from_annotation(node: ast.AST | None, models: dict[str, dict]) -> str:
    if node is None:
        return ""

    if isinstance(node, ast.Name):
        return node.id if node.id in models else ""

    if isinstance(node, ast.Attribute):
        return node.attr if node.attr in models else ""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if node.value in models else ""

    if isinstance(node, ast.Str):
        return str(node.s) if node.s in models else ""

    idx_t = getattr(ast, "Index", None)
    if idx_t is not None and isinstance(node, idx_t):
        return _model_name_from_annotation(getattr(node, "value", None), models)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _model_name_from_annotation(node.left, models)
        if left:
            return left
        return _model_name_from_annotation(node.right, models)

    if isinstance(node, ast.Tuple):
        for e in node.elts or []:
            nm = _model_name_from_annotation(e, models)
            if nm:
                return nm
        return ""

    if isinstance(node, ast.Subscript):
        base_name = ""
        if isinstance(node.value, ast.Name):
            base_name = node.value.id
        elif isinstance(node.value, ast.Attribute):
            base_name = node.value.attr
        if base_name in _TYPING_WRAPPERS:
            return _model_name_from_annotation(node.slice, models)
        return ""

    return ""


def _is_basemodel_base(base: ast.AST) -> bool:
    if isinstance(base, ast.Name) and base.id == "BaseModel":
        return True
    if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
        return True
    return False


def _extract_pydantic_models(tree: ast.Module) -> dict[str, dict]:
    # returns model_name -> {"fields":[{name,type,required}]}
    models: dict[str, dict] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(_is_basemodel_base(b) for b in (node.bases or [])):
            continue
        fields: list[dict] = []
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                name = st.target.id
                typ = _safe_unparse(st.annotation)
                required = False
                if st.value is None:
                    required = True
                else:
                    # Field(...) with first arg "..." or Ellipsis means required
                    if isinstance(st.value, ast.Call):
                        fn = st.value.func
                        fn_name = (
                            fn.id
                            if isinstance(fn, ast.Name)
                            else (fn.attr if isinstance(fn, ast.Attribute) else "")
                        )
                        if fn_name == "Field" and st.value.args:
                            a0 = st.value.args[0]
                            if isinstance(a0, ast.Constant) and a0.value is Ellipsis:
                                required = True
                            elif isinstance(a0, ast.Name) and a0.id == "Ellipsis":
                                required = True
                    if isinstance(st.value, ast.Constant) and st.value.value is Ellipsis:
                        required = True
                fields.append({"name": name, "type": typ, "required": bool(required)})
        models[node.name] = {"name": node.name, "fields": fields}
    return models


def _map_function_defaults(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, ast.AST | None]:
    args = fn.args
    pos = list(args.posonlyargs or []) + list(args.args or [])
    defaults = list(args.defaults or [])
    out: dict[str, ast.AST | None] = {}
    if pos:
        start = len(pos) - len(defaults)
        for i, a in enumerate(pos):
            if i >= start:
                out[a.arg] = defaults[i - start]
            else:
                out[a.arg] = None
    # kwonly
    kw = list(args.kwonlyargs or [])
    kwd = list(args.kw_defaults or [])
    for i, a in enumerate(kw):
        out[a.arg] = kwd[i] if i < len(kwd) else None
    return out


def _literal_default(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _extract_response_shape(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    # very conservative: only capture top-level dict keys from literal dict returns
    keys: set[str] = set()
    kind = "unknown"

    class V(ast.NodeVisitor):
        def visit_Return(self, node: ast.Return) -> Any:
            nonlocal kind
            v = node.value
            if isinstance(v, ast.Dict):
                kind = "dict"
                for k in v.keys or []:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)
                    elif isinstance(k, ast.Str):
                        keys.add(str(k.s))
            self.generic_visit(node)

    V().visit(fn)
    return {"kind": kind, "keys": sorted(keys)}


def _is_primitive_type(typ: str) -> bool:
    t = (typ or "").strip()
    if not t:
        return True
    prim = {
        "str",
        "int",
        "float",
        "bool",
        "dict",
        "list",
        "set",
        "tuple",
        "Any",
        "object",
        "Optional[str]",
        "Optional[int]",
        "Optional[float]",
        "Optional[bool]",
    }
    if t in prim:
        return True
    # Optional[T]
    if t.startswith("Optional[") and t.endswith("]"):
        inner = t[len("Optional[") : -1].strip()
        return inner in {"str", "int", "float", "bool", "dict", "list", "Any", "object"}
    return False


def build_backend_contract_for_route(text: str, route: dict) -> dict:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {"version": 1, "warnings": ["python_syntax_error"], "route": route}

    models = _extract_pydantic_models(tree)
    fn_map: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_map[node.name] = node

    method = str(route.get("method") or "").upper()
    path = str(route.get("path") or "")
    handler_name = str(route.get("handler_name") or "")
    lineno = int(route.get("lineno") or 0)

    path_params = parse_backend_path_params(path)
    path_param_names = {p["name"] for p in path_params if isinstance(p.get("name"), str)}

    warnings: list[str] = []
    fn = fn_map.get(handler_name)
    if fn is None:
        warnings.append("handler_not_found_in_file")
        return {
            "version": 1,
            "method": method,
            "local_path": path,
            "handler": {"name": handler_name, "lineno": lineno},
            "path_params": path_params,
            "query_params": [],
            "body": None,
            "response": {"kind": "unknown", "keys": []},
            "warnings": warnings,
        }

    defaults_map = _map_function_defaults(fn)
    query_params: list[dict] = []
    body_param: dict | None = None

    # positional args (skip self)
    args_all = list(fn.args.posonlyargs or []) + list(fn.args.args or [])
    for a in args_all:
        name = a.arg
        if name == "self":
            continue
        if name in _IGNORED_PARAM_NAMES:
            continue
        if name in path_param_names:
            continue
        ann_node = a.annotation if hasattr(a, "annotation") else None
        ann = _safe_unparse(ann_node)
        default_node = defaults_map.get(name)
        default_val = _literal_default(default_node)
        required = default_node is None

        # body detection
        model_name = _model_name_from_annotation(ann_node, models)
        is_model = bool(model_name)
        if is_model or (name in {"body", "payload", "data"} and not _is_primitive_type(ann)):
            if body_param is None:
                body_param = {
                    "param": name,
                    "type_name": model_name or ann,
                    "model": models.get(model_name) if model_name else None,
                    "required": bool(required),
                }
            else:
                warnings.append("multiple_body_like_params_detected")
            continue

        query_params.append(
            {
                "name": name,
                "type": ann,
                "required": bool(required),
                "default": default_val,
            }
        )

    # kwonly args
    for a in fn.args.kwonlyargs or []:
        name = a.arg
        if name in _IGNORED_PARAM_NAMES or name in path_param_names:
            continue
        ann_node = a.annotation if hasattr(a, "annotation") else None
        ann = _safe_unparse(ann_node)
        default_node = defaults_map.get(name)
        default_val = _literal_default(default_node)
        required = default_node is None

        model_name = _model_name_from_annotation(ann_node, models)
        is_model = bool(model_name)
        if is_model or (name in {"body", "payload", "data"} and not _is_primitive_type(ann)):
            if body_param is None:
                body_param = {
                    "param": name,
                    "type_name": model_name or ann,
                    "model": models.get(model_name) if model_name else None,
                    "required": bool(required),
                }
            else:
                warnings.append("multiple_body_like_params_detected")
            continue

        query_params.append(
            {"name": name, "type": ann, "required": bool(required), "default": default_val}
        )

    response = _extract_response_shape(fn)

    return {
        "version": 1,
        "method": method,
        "local_path": path,
        "handler": {"name": handler_name, "lineno": int(getattr(fn, "lineno", lineno) or lineno)},
        "path_params": path_params,
        "query_params": query_params,
        "body": body_param,
        "response": response,
        "warnings": warnings,
    }


def extract_backend_route_contract_rows(
    project_id: int, source_path: str, text: str, routes_in_file: list[dict]
) -> list[dict]:
    out: list[dict] = []
    for r in routes_in_file:
        method = str(r.get("method") or "").upper()
        local_path = str(r.get("path") or "")
        handler_name = str(r.get("handler_name") or "")
        lineno = int(r.get("lineno") or 0)
        contract = build_backend_contract_for_route(text, r)
        out.append(
            {
                "project_id": int(project_id),
                "method": method,
                "path": local_path,
                "source_path": source_path,
                "handler_name": handler_name,
                "lineno": int(lineno),
                "contract_json": json.dumps(contract, ensure_ascii=False),
            }
        )
    return out


_EXPORT_FN_RE = re.compile(
    r"""(?msx)
    ^\s*export\s+(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*
    \(\s*(?P<params>[^)]*)\)\s*
    (?::\s*(?P<ret>[^{\n]+))?
    """,
)

_PROMISE_RE = re.compile(r"Promise\s*<\s*([^>]+)\s*>")

_TS_FIELD_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_$][\w$]*)\s*(?P<opt>\?)?\s*:\s*(?P<typ>[^;,\n]+)", re.MULTILINE
)


def _split_ts_params(params: str) -> list[str]:
    # split by top-level commas, ignore generics/objects/arrays
    s = params or ""
    out: list[str] = []
    cur: list[str] = []
    depth_par = depth_ang = depth_br = depth_brace = 0
    in_str: str | None = None
    esc = False
    for ch in s:
        if in_str:
            cur.append(ch)
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            cur.append(ch)
            continue
        if ch == "(":
            depth_par += 1
        elif ch == ")":
            depth_par = max(0, depth_par - 1)
        elif ch == "<":
            depth_ang += 1
        elif ch == ">":
            depth_ang = max(0, depth_ang - 1)
        elif ch == "[":
            depth_br += 1
        elif ch == "]":
            depth_br = max(0, depth_br - 1)
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)

        if ch == "," and depth_par == 0 and depth_ang == 0 and depth_br == 0 and depth_brace == 0:
            tok = "".join(cur).strip()
            if tok:
                out.append(tok)
            cur = []
        else:
            cur.append(ch)
    tok = "".join(cur).strip()
    if tok:
        out.append(tok)
    return out


def _parse_ts_param(tok: str) -> dict | None:
    t = (tok or "").strip()
    if not t:
        return None
    # ignore destructuring
    if t.startswith("{") or t.startswith("["):
        return {"name": "<destructured>", "type": "", "optional": True}
    # remove default
    if "=" in t:
        t = t.split("=", 1)[0].strip()
    # name?: type
    if ":" in t:
        left, right = t.split(":", 1)
        left = left.strip()
        right = right.strip()
        optional = left.endswith("?")
        name = left[:-1].strip() if optional else left
        if not name:
            return None
        return {"name": name, "type": right, "optional": bool(optional)}
    # bare name
    return {"name": t, "type": "", "optional": False}


def _find_wrapper_for_line(text: str, lineno: int) -> dict:
    lines = text.splitlines()
    i0 = max(0, min(len(lines), int(lineno) - 1))
    start = max(0, i0 - 220)
    window = "\n".join(lines[start : i0 + 1])
    best = None
    for m in _EXPORT_FN_RE.finditer(window):
        best = m
    if best is None:
        return {"name": "", "params": [], "return_type": "", "response_type": "", "body_type": ""}
    fn_name = (best.group("name") or "").strip()
    params_text = (best.group("params") or "").strip()
    ret = (best.group("ret") or "").strip()
    response_type = ""
    pm = _PROMISE_RE.search(ret or "")
    if pm:
        response_type = (pm.group(1) or "").strip()
    params = []
    body_type = ""
    for tok in _split_ts_params(params_text):
        p = _parse_ts_param(tok)
        if not p:
            continue
        params.append(p)
        nm = p.get("name") or ""
        typ = p.get("type") or ""
        if nm in {"body", "payload", "data"} and not body_type and typ:
            body_type = typ
    return {
        "name": fn_name,
        "params": params,
        "return_type": ret,
        "response_type": response_type,
        "body_type": body_type,
    }


def _extract_call_args(text: str, call_start: int) -> list[str]:
    # best-effort: parse (...) of api.get/post(...) call starting at match.start()
    # of "<client>.<method>("
    s = text
    i = call_start
    # find first "(" after call_start
    p0 = s.find("(", i)
    if p0 < 0:
        return []
    i = p0 + 1
    args: list[str] = []
    cur: list[str] = []
    depth_par = 1
    depth_ang = depth_br = depth_brace = 0
    in_str: str | None = None
    esc = False
    while i < len(s) and depth_par > 0:
        ch = s[i]
        if in_str:
            cur.append(ch)
            if esc:
                esc = False
                i += 1
                continue
            if ch == "\\":
                esc = True
                i += 1
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            cur.append(ch)
            i += 1
            continue
        if ch == "(":
            depth_par += 1
        elif ch == ")":
            depth_par -= 1
            if depth_par == 0:
                break
        elif ch == "<":
            depth_ang += 1
        elif ch == ">":
            depth_ang = max(0, depth_ang - 1)
        elif ch == "[":
            depth_br += 1
        elif ch == "]":
            depth_br = max(0, depth_br - 1)
        elif ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)

        if ch == "," and depth_par == 1 and depth_ang == 0 and depth_br == 0 and depth_brace == 0:
            tok = "".join(cur).strip()
            if tok:
                args.append(tok)
            cur = []
        else:
            cur.append(ch)
        i += 1
    tok = "".join(cur).strip()
    if tok:
        args.append(tok)
    return args


_TS_OBJ_KEY_RE = re.compile(r"""(?mx)
    ^\s*(?:
        (?P<id>[A-Za-z_$][\w$]*)\s*:
        |
        (?P<sh>[A-Za-z_$][\w$]*)\s*(?:,|\})
        |
        ['"](?P<str>[^'"]+)['"]\s*:
    )
+""")


def _extract_obj_literal_keys(expr: str) -> list[str]:
    s = (expr or "").strip()
    if not s.startswith("{"):
        return []
    # strip outer braces roughly
    inner = s[1:]
    keys: list[str] = []
    for m in _TS_OBJ_KEY_RE.finditer(inner):
        k = m.group("id") or m.group("sh") or m.group("str") or ""
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
        if len(keys) >= 200:
            break
    return keys


def extract_frontend_call_meta_rows(
    project_id: int, source_path: str, text: str, calls_in_file: list[dict]
) -> list[dict]:
    out: list[dict] = []
    # for each call, attach wrapper info and body keys
    for c in calls_in_file:
        method = str(c.get("method") or "").upper()
        path = str(c.get("path") or "")
        lineno = int(c.get("lineno") or 0)
        if not method or not path or lineno <= 0:
            continue
        wrapper = _find_wrapper_for_line(text, lineno)

        # best-effort body keys: find call occurrence near this line and parse args
        body_keys: list[str] = []
        try:
            lines = text.splitlines()
            i0 = max(0, min(len(lines), lineno - 1))
            # search small window for the call line containing path literal
            window = "\n".join(lines[max(0, i0 - 3) : min(len(lines), i0 + 4)])
            # find first occurrence of path string (without quotes)
            raw = path
            raw_find = raw
            if raw_find.startswith("`") and raw_find.endswith("`"):
                raw_find = raw_find[1:-1]
            elif raw_find.startswith('"') and raw_find.endswith('"'):
                raw_find = raw_find[1:-1]
            elif raw_find.startswith("'") and raw_find.endswith("'"):
                raw_find = raw_find[1:-1]
            pos = window.find(raw_find)
            if pos != -1:
                # approximate call start as previous ".<method>(" in window
                mpos = window.rfind(f".{method.lower()}(", 0, pos)
                if mpos != -1:
                    args = _extract_call_args(window, mpos)
                    # axios: (path, body?, config?)
                    if method in {"POST", "PUT", "PATCH"} and len(args) >= 2:
                        body_keys = _extract_obj_literal_keys(args[1])
        except Exception:
            body_keys = []

        out.append(
            {
                "project_id": int(project_id),
                "method": method,
                "path": path,
                "source_path": source_path,
                "lineno": int(lineno),
                "wrapper_name": str(wrapper.get("name") or ""),
                "wrapper_response_type": str(wrapper.get("response_type") or ""),
                "wrapper_body_type": str(wrapper.get("body_type") or ""),
                "wrapper_params_json": json.dumps(wrapper.get("params") or [], ensure_ascii=False),
                "body_keys_json": json.dumps(body_keys, ensure_ascii=False),
                "notes": "",
            }
        )
    return out


_TYPE_START_RE = re.compile(
    r"(?m)^\s*export\s+(type|interface)\s+([A-Za-z_$][\w$]*)\s*(?:=)?\s*\{"
)


def extract_ts_type_defs(project_id: int, source_path: str, text: str) -> list[dict]:
    out: list[dict] = []
    for m in _TYPE_START_RE.finditer(text):
        kind = (m.group(1) or "").strip()
        name = (m.group(2) or "").strip()
        brace_pos = text.find("{", m.end() - 1)
        if brace_pos < 0:
            continue
        blk = extract_brace_block(text, brace_pos)
        if not blk:
            continue
        start, end = blk
        block_text = text[start:end]
        fields: list[dict] = []
        for fm in _TS_FIELD_RE.finditer(block_text):
            fn = (fm.group("name") or "").strip()
            opt = bool(fm.group("opt"))
            typ = (fm.group("typ") or "").strip()
            if fn:
                fields.append({"name": fn, "optional": bool(opt), "type": typ})
        out.append(
            {
                "project_id": int(project_id),
                "name": name,
                "kind": kind,
                "source_path": source_path,
                "fields_json": json.dumps(fields, ensure_ascii=False),
            }
        )
    return out
