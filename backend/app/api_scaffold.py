#backend/app/api_scaffold.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PATH_PARAM_RE = re.compile(r"\{([^}]+)\}")


def snake_to_camel(name: str, *, lower_first: bool = True) -> str:
    s = (name or "").strip()
    if not s:
        return ""
    parts = [p for p in re.split(r"[_\-\s]+", s) if p]
    if not parts:
        return ""
    head = parts[0].lower() if lower_first else parts[0][:1].upper() + parts[0][1:]
    tail = "".join([p[:1].upper() + p[1:] for p in parts[1:]])
    return head + tail


def guess_ts_type(param_name: str) -> str:
    n = (param_name or "").strip().lower()
    if not n:
        return "string"
    if n == "id" or n.endswith("_id") or n.endswith("id"):
        return "number"
    return "string"


def parse_backend_path_params(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in PATH_PARAM_RE.finditer(path or ""):
        inner = (m.group(1) or "").strip()
        if not inner:
            continue
        name = inner
        multi = False
        if ":" in inner:
            nm, conv = inner.split(":", 1)
            name = (nm or "").strip()
            conv = (conv or "").strip().lower()
            if conv == "path":
                multi = True
        if not name:
            continue
        out.append({"name": name, "multi": bool(multi)})
    # dedupe by name
    seen = set()
    uniq: list[dict[str, Any]] = []
    for p in out:
        nm = str(p.get("name") or "")
        if nm and nm not in seen:
            seen.add(nm)
            uniq.append(p)
    return uniq


def build_ts_path_template(backend_path: str) -> tuple[str, list[dict[str, Any]]]:
    params = parse_backend_path_params(backend_path)
    param_map: dict[str, dict[str, Any]] = {str(p["name"]): p for p in params}

    def repl(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        if not inner:
            return "${param}"
        name = inner
        multi = False
        if ":" in inner:
            nm, conv = inner.split(":", 1)
            name = (nm or "").strip()
            conv = (conv or "").strip().lower()
            if conv == "path":
                multi = True
        if not name:
            name = "param"
        ts_name = snake_to_camel(name, lower_first=True) or name
        if bool(param_map.get(name, {}).get("multi")) or multi:
            return "${encodePath(" + ts_name + ")}"
        return "${" + ts_name + "}"

    tpl = PATH_PARAM_RE.sub(repl, backend_path or "")
    if not tpl.startswith("/"):
        tpl = "/" + tpl
    return ("`" + tpl + "`", params)


def suggest_frontend_module_file(backend_path: str) -> str:
    # prefer /api/<module>/... -> frontend/src/api/<module>.ts
    p = (backend_path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    parts = [x for x in p.split("/") if x]
    if len(parts) >= 2 and parts[0] == "api":
        mod = parts[1]
        if mod:
            return f"frontend/src/api/{mod}.ts"
    return "frontend/src/api/api.ts"


def suggest_function_name(method: str, backend_path: str, handler_name: str | None = None) -> str:
    hn = (handler_name or "").strip()
    if hn:
        return snake_to_camel(hn, lower_first=True) or hn

    m = (method or "").strip().upper()
    # take last static segment
    p = (backend_path or "").strip()
    parts = [x for x in p.split("/") if x]
    last_static = ""
    for seg in reversed(parts):
        if seg.startswith("{") and seg.endswith("}"):
            continue
        last_static = seg
        break
    base = snake_to_camel(last_static, lower_first=False) if last_static else "Call"
    if m == "GET":
        return "get" + base
    if m == "POST":
        return "post" + base
    if m == "PUT":
        return "put" + base
    if m == "PATCH":
        return "patch" + base
    if m == "DELETE":
        return "delete" + base
    return snake_to_camel(m.lower() + "_" + (last_static or "call"), lower_first=True)

def build_frontend_snippet(method: str, backend_path: str, handler_name: str | None = None) -> dict[str, Any]:
    m = (method or "").strip().upper() or "GET"
    fn = suggest_function_name(m, backend_path, handler_name=handler_name)
    tpl, params = build_ts_path_template(backend_path)

    ts_params: list[str] = []
    uses_encode = "encodePath(" in tpl
    for p in params:
        nm = str(p.get("name") or "")
        if not nm:
            continue
        ts_name = snake_to_camel(nm, lower_first=True) or nm
        ts_type = guess_ts_type(nm)
        ts_params.append(f"{ts_name}: {ts_type}")

    # query params are common; keep as optional "params"
    ts_params.append("params?: Record<string, any>")

    call_line = ""
    if m in ("POST", "PUT", "PATCH"):
        ts_params.insert(len(params), "body?: unknown")
        call_line = f"  const r = await api.{m.lower()}({tpl}, body ?? null, {{ params }})"
    else:
        call_line = f"  const r = await api.{m.lower()}({tpl}, {{ params }})"

    imports = ["import { api } from './client'"]
    if uses_encode:
        imports.append("import { encodePath } from './utils'")

    snippet = "\n".join(imports) + "\n\n" + (
        f"export async function {fn}({', '.join(ts_params)}): Promise<unknown> {{\n"
        f"{call_line}\n"
        f"  return r.data\n"
        f"}}\n"
    )

    return {
        "function_name": fn,
        "path_template": tpl,
        "uses_encodePath": bool(uses_encode),
        "path_params": params,
        "snippet": snippet,
    }