#backend/app/api_map.py
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Iterable

TOKEN_ANY1 = "{}"
TOKEN_ANYM = "{*}"

_HTTP_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "delete": "DELETE",
    "patch": "PATCH",
    "options": "OPTIONS",
    "head": "HEAD",
    "trace": "TRACE",
}

_ROUTE_DECORATORS = {"api_route", "route"}
_WS_DECORATORS = {"websocket", "websocket_route"}

_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")

# Frontend call patterns (best-effort, no TS AST)
_AXIOS_CALL_RE = re.compile(
    r"""(?mx)
    (?P<client>[A-Za-z_$][\w$]*)\s*\.\s*
    (?P<method>get|post|put|delete|patch|options|head)\s*
    \(\s*
    (?P<arg>
        `[^`]*` |
        "(?:\\.|[^"\\])*" |
        '(?:\\.|[^'\\])*'
    )
    """,
)

_FETCH_CALL_RE = re.compile(
    r"""(?mx)
    (?P<client>\bfetch)\s*
    \(\s*
    (?P<arg>
        `[^`]*` |
        "(?:\\.|[^"\\])*" |
        '(?:\\.|[^'\\])*'
    )
    """,
)


def _strip_quotes(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"', "`"):
        return s[1:-1]
    return s


def _join_paths(prefix: str, path: str) -> str:
    pfx = (prefix or "").strip()
    pth = (path or "").strip()

    if pfx and not pfx.startswith("/"):
        pfx = "/" + pfx
    if pfx.endswith("/") and pfx != "/":
        pfx = pfx.rstrip("/")

    # FastAPI allows "" for path
    if pth and not pth.startswith("/"):
        pth = "/" + pth

    if not pth:
        return pfx or "/"
    if not pfx:
        return pth or "/"
    if pfx == "/":
        return pth
    return pfx + pth


def backend_path_skeleton(path: str) -> str:
    # Convert /api/nodes/{project_id}/{path:path}/node -> /api/nodes/{}/{*}/node
    raw = (path or "").strip()
    if not raw:
        return "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    parts = [p for p in raw.split("/") if p]
    out: list[str] = []
    for seg in parts:
        if seg.startswith("{") and seg.endswith("}"):
            inner = seg[1:-1]
            # starlette path converter: {x:path}
            if ":path" in inner:
                out.append(TOKEN_ANYM)
            else:
                out.append(TOKEN_ANY1)
        else:
            out.append(seg)
    return "/" + "/".join(out) if out else "/"


def frontend_path_skeleton(path_template: str) -> str:
    # Convert /api/nodes/${projectId}/${encodePath(path)}/node -> /api/nodes/{}/{*}/node
    raw = (path_template or "").strip()
    if not raw:
        return "/"
    # allow absolute urls: keep only path part if looks like http(s)://...
    # (best-effort; we intentionally do not parse query/fragment here)
    if raw.startswith("http://") or raw.startswith("https://"):
        # drop scheme+host
        m = re.search(r"^https?://[^/]+(?P<path>/.*)$", raw)
        if m:
            raw = m.group("path")
    if not raw.startswith("/"):
        raw = "/" + raw

    parts = [p for p in raw.split("/") if p]
    out: list[str] = []
    for seg in parts:
        ph = list(_TEMPLATE_PLACEHOLDER_RE.finditer(seg))
        if not ph:
            out.append(seg)
            continue

        # if segment is exactly ${...}
        if len(ph) == 1 and ph[0].start() == 0 and ph[0].end() == len(seg):
            expr = (ph[0].group(1) or "").strip()
            # heuristic: encodePath/path-like placeholders can expand to multiple segments
            if "encodePath" in expr or "path" in expr:
                out.append(TOKEN_ANYM)
            else:
                out.append(TOKEN_ANY1)
        else:
            # mixed literal + placeholder inside one segment -> still one segment wildcard
            out.append(TOKEN_ANY1)
    return "/" + "/".join(out) if out else "/"


def split_skeleton(s: str) -> list[str]:
    raw = (s or "").strip()
    if not raw:
        return []
    if raw.startswith("/"):
        raw = raw[1:]
    return [p for p in raw.split("/") if p]


def _is_static(tok: str) -> bool:
    return tok not in (TOKEN_ANY1, TOKEN_ANYM)


def static_match_score(a: list[str], b: list[str]) -> int:
    # count identical static tokens aligned in order (rough score; not a strict metric)
    score = 0
    for x, y in zip(a, b):
        if _is_static(x) and _is_static(y) and x == y:
            score += 1
    return score


def patterns_compatible(a_tokens: list[str], b_tokens: list[str]) -> bool:
    # Intersection non-empty between two path-pattern token lists with {} and {*}
    # {} = single segment wildcard, {*}=multi-segment wildcard (>=0)
    memo: dict[tuple[int, int], bool] = {}

    def rec(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == len(a_tokens) and j == len(b_tokens):
            memo[key] = True
            return True
        if i == len(a_tokens):
            # remaining in b must be all ANYM to match empty
            ok = all(t == TOKEN_ANYM for t in b_tokens[j:])
            memo[key] = ok
            return ok
        if j == len(b_tokens):
            ok = all(t == TOKEN_ANYM for t in a_tokens[i:])
            memo[key] = ok
            return ok

        ta = a_tokens[i]
        tb = b_tokens[j]

        # ANYM expansion
        if ta == TOKEN_ANYM:
            # match zero
            if rec(i + 1, j):
                memo[key] = True
                return True
            # match one token from b
            if rec(i, j + 1):
                memo[key] = True
                return True
            memo[key] = False
            return False
        if tb == TOKEN_ANYM:
            if rec(i, j + 1):
                memo[key] = True
                return True
            if rec(i + 1, j):
                memo[key] = True
                return True
            memo[key] = False
            return False

        # both non-ANYM: either static or ANY1
        if _is_static(ta) and _is_static(tb):
            ok = (ta == tb) and rec(i + 1, j + 1)
            memo[key] = ok
            return ok

        # if one is ANY1, they can align
        ok = rec(i + 1, j + 1)
        memo[key] = ok
        return ok

    return rec(0, 0)


def _eval_str_expr(node: ast.AST | None, consts: dict[str, str]) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Str):
        return node.s
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        l = _eval_str_expr(node.left, consts)
        r = _eval_str_expr(node.right, consts)
        if l is not None and r is not None:
            return l + r
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.Str):
                parts.append(v.s)
            elif isinstance(v, ast.FormattedValue):
                parts.append(TOKEN_ANY1)
            else:
                parts.append(TOKEN_ANY1)
        return "".join(parts)
    return None

def _expr_repr(node: ast.AST) -> str:
    unparse = getattr(ast, "unparse", None)
    if callable(unparse):
        try:
            return str(unparse(node))
        except Exception:
            pass
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _expr_repr(node.value)
        return f"{base}.{node.attr}"
    return "<expr>"

def _collect_python_import_aliases(tree: ast.Module, consts: dict[str, str]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:

    module_aliases: dict[str, str] = {}
    symbol_imports: dict[str, tuple[str, str]] = {}

    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            for a in stmt.names or []:
                mod = (a.name or "").strip()
                if not mod:
                    continue
                bound = (a.asname or "").strip()
                if not bound:
                    bound = mod.split(".", 1)[0]
                module_aliases[bound] = mod
        elif isinstance(stmt, ast.ImportFrom):
            module = (stmt.module or "").strip()
            level = int(stmt.level or 0)
            prefix = "." * level
            mod_spec = prefix + module if module else (prefix or "")
            for a in stmt.names or []:
                name = (a.name or "").strip()
                if not name or name == "*":
                    continue
                bound = (a.asname or "").strip() or name
                symbol_imports[bound] = (mod_spec, name)
                if mod_spec:
                    module_aliases[bound] = (mod_spec + "." + name).strip(".")
    return module_aliases, symbol_imports

def _collect_module_const_strings(tree: ast.Module) -> dict[str, str]:
    consts: dict[str, str] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1:
                continue
            t = stmt.targets[0]
            if isinstance(t, ast.Name):
                v = _eval_str_expr(stmt.value, consts)
                if isinstance(v, str):
                    consts[t.id] = v
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.value is not None:
                v = _eval_str_expr(stmt.value, consts)
                if isinstance(v, str):
                    consts[stmt.target.id] = v
    return consts


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _extract_methods_kw(node: ast.Call, consts: dict[str, str]) -> list[str]:
    for kw in node.keywords or []:
        if kw.arg != "methods":
            continue
        try:
            v = ast.literal_eval(kw.value)
        except Exception:
            v = None
        if isinstance(v, (list, tuple)):
            out = []
            for x in v:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip().upper())
            return out
    return []


def _extract_path_arg(node: ast.Call, consts: dict[str, str]) -> str | None:
    if node.args:
        v = _eval_str_expr(node.args[0], consts)
        if isinstance(v, str):
            return v
    for kw in node.keywords or []:
        if kw.arg == "path":
            v = _eval_str_expr(kw.value, consts)
            if isinstance(v, str):
                return v
    return None


def extract_fastapi_routes(source_path: str, text: str) -> list[dict]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    consts = _collect_module_const_strings(tree)

    instances: dict[str, dict[str, Any]] = {}

    def register_instance(name: str, kind: str, prefix: str) -> None:
        instances[name] = {"kind": kind, "prefix": prefix}

    for stmt in tree.body:
        target_name = None
        call = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target_name = stmt.targets[0].id
            call = stmt.value if isinstance(stmt.value, ast.Call) else None
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and isinstance(stmt.value, ast.Call):
            target_name = stmt.target.id
            call = stmt.value
        if not target_name or not isinstance(call, ast.Call):
            continue
        cname = _call_name(call.func)
        if cname == "APIRouter":
            prefix = ""
            for kw in call.keywords or []:
                if kw.arg == "prefix":
                    v = _eval_str_expr(kw.value, consts)
                    if isinstance(v, str):
                        prefix = v
            if not prefix and call.args:
                v = _eval_str_expr(call.args[0], consts)
                if isinstance(v, str):
                    prefix = v
            register_instance(target_name, "router", prefix)
        elif cname == "FastAPI":
            register_instance(target_name, "app", "")

    routes: list[dict] = []

    def emit(methods: list[str], full_path: str, router_prefix: str, handler: str, lineno: int, decorator: str) -> None:
        for m in methods:
            mm = (m or "").strip().upper()
            if not mm:
                continue
            routes.append(
                {
                    "method": mm,
                    "path": full_path,
                    "path_skeleton": backend_path_skeleton(full_path),
                    "router_prefix": router_prefix,
                    "source_path": source_path,
                    "handler_name": handler,
                    "lineno": int(lineno or 0),
                    "decorator": decorator,
                }
            )

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        handler = node.name
        for dec in node.decorator_list or []:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not isinstance(func, ast.Attribute):
                continue
            base = func.value
            if not isinstance(base, ast.Name):
                continue
            inst_name = base.id
            attr = (func.attr or "").strip()
            if not attr:
                continue
            prefix = ""
            if inst_name in instances:
                prefix = str(instances[inst_name].get("prefix") or "")
            path_part = _extract_path_arg(dec, consts)
            if path_part is None:
                continue
            full = _join_paths(prefix, path_part)
            ln = int(getattr(dec, "lineno", getattr(node, "lineno", 0)) or 0)

            if attr in _HTTP_DECORATORS:
                emit([_HTTP_DECORATORS[attr]], full, prefix, handler, ln, f"{inst_name}.{attr}")
            elif attr in _WS_DECORATORS:
                emit(["WEBSOCKET"], full, prefix, handler, ln, f"{inst_name}.{attr}")
            elif attr in _ROUTE_DECORATORS:
                methods = _extract_methods_kw(dec, consts)
                if not methods:
                    methods = ["GET"]
                emit(methods, full, prefix, handler, ln, f"{inst_name}.{attr}")

    for stmt in tree.body:
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            continue
        call = stmt.value
        func = call.func
        if not isinstance(func, ast.Attribute):
            continue
        if (func.attr or "") != "add_api_route":
            continue
        if not isinstance(func.value, ast.Name):
            continue
        inst_name = func.value.id
        prefix = ""
        if inst_name in instances:
            prefix = str(instances[inst_name].get("prefix") or "")
        path_part = _extract_path_arg(call, consts)
        if path_part is None:
            continue
        full = _join_paths(prefix, path_part)
        methods = _extract_methods_kw(call, consts) or ["GET"]
        handler = ""
        for kw in call.keywords or []:
            if kw.arg == "endpoint":
                if isinstance(kw.value, ast.Name):
                    handler = kw.value.id
        ln = int(getattr(stmt, "lineno", 0) or 0)
        emit(methods, full, prefix, handler, ln, f"{inst_name}.add_api_route")

    return routes

def extract_fastapi_includes(source_path: str, text: str) -> list[dict]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    consts = _collect_module_const_strings(tree)
    module_aliases, symbol_imports = _collect_python_import_aliases(tree, consts)

    instances: dict[str, dict[str, Any]] = {}

    def register_instance(name: str, kind: str, prefix: str) -> None:
        instances[name] = {"kind": kind, "prefix": prefix}

    for stmt in tree.body:
        target_name = None
        call = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target_name = stmt.targets[0].id
            call = stmt.value if isinstance(stmt.value, ast.Call) else None
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and isinstance(stmt.value, ast.Call):
            target_name = stmt.target.id
            call = stmt.value
        if not target_name or not isinstance(call, ast.Call):
            continue
        cname = _call_name(call.func)
        if cname == "APIRouter":
            prefix = ""
            for kw in call.keywords or []:
                if kw.arg == "prefix":
                    v = _eval_str_expr(kw.value, consts)
                    if isinstance(v, str):
                        prefix = v
            register_instance(target_name, "router", prefix)
        elif cname == "FastAPI":
            register_instance(target_name, "app", "")

    includes: list[dict] = []

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> Any:
            func = node.func
            if isinstance(func, ast.Attribute) and (func.attr or "") == "include_router":
                base = func.value
                parent_instance = base.id if isinstance(base, ast.Name) else ""

                router_expr: ast.AST | None = None
                if node.args:
                    router_expr = node.args[0]
                for kw in node.keywords or []:
                    if kw.arg == "router":
                        router_expr = kw.value

                prefix = ""
                for kw in node.keywords or []:
                    if kw.arg == "prefix":
                        v = _eval_str_expr(kw.value, consts)
                        if isinstance(v, str):
                            prefix = v

                child_ref = _expr_repr(router_expr) if router_expr is not None else ""
                child_module_spec = ""
                child_instance = ""

                if isinstance(router_expr, ast.Name):
                    nm = router_expr.id
                    if nm in instances:
                        child_module_spec = ""
                        child_instance = nm
                    elif nm in symbol_imports:
                        mod_spec, sym = symbol_imports[nm]
                        child_module_spec = mod_spec
                        child_instance = sym
                    elif nm in module_aliases:
                        child_module_spec = module_aliases[nm]
                        child_instance = ""
                elif isinstance(router_expr, ast.Attribute) and isinstance(router_expr.value, ast.Name):
                    base_alias = router_expr.value.id
                    attr = (router_expr.attr or "").strip()
                    if base_alias in module_aliases:
                        child_module_spec = module_aliases[base_alias]
                        child_instance = attr
                    elif base_alias in symbol_imports:
                        mod_spec, sym = symbol_imports[base_alias]
                        child_module_spec = mod_spec
                        child_instance = attr or sym

                lineno = int(getattr(node, "lineno", 0) or 0)

                includes.append(
                    {
                        "parent_source_path": source_path,
                        "parent_instance": parent_instance,
                        "child_ref": child_ref,
                        "child_module_spec": child_module_spec,
                        "child_instance": child_instance,
                        "prefix": prefix,
                        "lineno": lineno,
                    }
                )

            self.generic_visit(node)

    Visitor().visit(tree)
    return includes

def extract_frontend_api_calls(source_path: str, text: str) -> list[dict]:
    # Best-effort extraction of HTTP calls in JS/TS sources.
    out: list[dict] = []

    def emit(client: str, method: str, path_raw: str, lineno: int) -> None:
        p = (path_raw or "").strip()
        if not p:
            return
        if not (p.startswith("/") or p.startswith("http://") or p.startswith("https://")):
            return
        m = (method or "").strip().upper()
        if not m:
            return
        out.append(
            {
                "method": m,
                "path": p,
                "path_skeleton": frontend_path_skeleton(p),
                "source_path": source_path,
                "lineno": int(lineno or 0),
                "client": client,
            }
        )

    for m in _AXIOS_CALL_RE.finditer(text):
        client = (m.group("client") or "").strip()
        method = (m.group("method") or "").strip()
        arg = _strip_quotes(m.group("arg") or "")
        ln = text.count("\n", 0, m.start()) + 1
        emit(client, method, arg, ln)

    for m in _FETCH_CALL_RE.finditer(text):
        client = "fetch"
        arg = _strip_quotes(m.group("arg") or "")
        ln = text.count("\n", 0, m.start()) + 1
        # default GET for fetch (unless options parsed; omitted here)
        emit(client, "GET", arg, ln)

    return out