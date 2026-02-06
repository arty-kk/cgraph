from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Callable

from .types import AgenticMeta


def _clamp_int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        x = int(v)
    except Exception:
        x = int(default)
    return max(lo, min(hi, x))


def _clamp_float(v: Any, default: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    if x != x:
        x = float(default)
    return max(lo, min(hi, x))


def _tool_ok(data: dict) -> dict:
    if not isinstance(data, dict):
        raise TypeError("tool data must be a dict")
    return {"ok": True, "data": data, "error": None}


def _tool_error(code: str, message: str, details: dict | None = None) -> dict:
    details_out = details if isinstance(details, dict) and details else None
    return {
        "ok": False,
        "data": None,
        "error": {"code": str(code), "message": str(message), "details": details_out},
    }


def _validate_tool_result(name: str, result: Any) -> dict:
    if not isinstance(result, dict):
        raise RuntimeError(f"Tool {name} returned non-dict result")
    for key in ("ok", "data", "error"):
        if key not in result:
            raise RuntimeError(f"Tool {name} result missing key '{key}'")
    ok = result.get("ok")
    if not isinstance(ok, bool):
        raise RuntimeError(f"Tool {name} result has non-bool ok")
    if ok:
        if not isinstance(result.get("data"), dict):
            raise RuntimeError(f"Tool {name} ok result missing data dict")
        if result.get("error") is not None:
            raise RuntimeError(f"Tool {name} ok result must have error=None")
        return result
    if result.get("data") is not None:
        raise RuntimeError(f"Tool {name} error result must have data=None")
    err = result.get("error")
    if not isinstance(err, dict):
        raise RuntimeError(f"Tool {name} error result missing error dict")
    if not isinstance(err.get("code"), str) or not err.get("code"):
        raise RuntimeError(f"Tool {name} error result missing error.code")
    if not isinstance(err.get("message"), str) or not err.get("message"):
        raise RuntimeError(f"Tool {name} error result missing error.message")
    return result


def _dispatch_tool(
    project_id: int, root: Path, meta: AgenticMeta, name: str, args: dict, *, max_file_chars: int
) -> dict:
    from . import tools

    package_module = sys.modules.get(__package__)

    def _resolve_tool_func(attr: str) -> Callable[..., dict]:
        if package_module is None:
            try:
                pkg = importlib.import_module(__package__)
            except Exception:
                pkg = None
        else:
            pkg = package_module
        if pkg is not None:
            fn = getattr(pkg, attr, None)
            if callable(fn):
                return fn
        return getattr(tools, attr)

    if name == "plan_retrieval":
        meta.retrieval_plan = dict(args) if isinstance(args, dict) else None
        return _validate_tool_result(name, _tool_ok({"stored": True}))
    plan_ready = bool(meta.retrieval_plan) or any(
        entry.get("name") == "plan_retrieval" and entry.get("status") == "ok"
        for entry in meta.tool_trace
        if isinstance(entry, dict)
    )
    if not plan_ready:
        return _validate_tool_result(
            name,
            _tool_error(
                "policy_violation",
                "Перед использованием инструментов нужно вызвать plan_retrieval.",
            ),
        )
    if name == "get_file":
        allowed = any(
            entry.get("name")
            in ("search_paths", "search_symbols", "search_text", "search_semantic")
            and entry.get("status") == "ok"
            for entry in meta.tool_trace
            if isinstance(entry, dict)
        )
        if not allowed:
            return _validate_tool_result(
                name,
                _tool_error(
                    "policy_violation",
                    "Перед get_file нужно выполнить search_paths, search_symbols, search_text "
                    "или search_semantic.",
                ),
            )
        tool_fn = _resolve_tool_func("_tool_get_file")
        return _validate_tool_result(
            name, tool_fn(project_id, root, meta, args, max_file_chars=max_file_chars)
        )
    if name == "get_file_lines":
        allowed = any(
            entry.get("name")
            in ("search_paths", "search_symbols", "search_text", "search_semantic")
            and entry.get("status") == "ok"
            for entry in meta.tool_trace
            if isinstance(entry, dict)
        )
        if not allowed:
            return _validate_tool_result(
                name,
                _tool_error(
                    "policy_violation",
                    "Перед get_file_lines нужно выполнить search_paths, search_symbols, "
                    "search_text или search_semantic.",
                ),
            )
        tool_fn = _resolve_tool_func("_tool_get_file_lines")
        return _validate_tool_result(
            name, tool_fn(project_id, root, meta, args, max_file_chars=max_file_chars)
        )
    if name == "get_contract":
        tool_fn = _resolve_tool_func("_tool_get_contract")
        return _validate_tool_result(name, tool_fn(project_id, root, meta, args))
    if name == "get_symbol":
        tool_fn = _resolve_tool_func("_tool_get_symbol")
        return _validate_tool_result(name, tool_fn(project_id, root, meta, args))
    if name == "get_node":
        tool_fn = _resolve_tool_func("_tool_get_node")
        return _validate_tool_result(name, tool_fn(project_id, root, args))
    if name == "get_neighbors":
        tool_fn = _resolve_tool_func("_tool_get_neighbors")
        return _validate_tool_result(name, tool_fn(project_id, root, args))
    if name == "search_paths":
        tool_fn = _resolve_tool_func("_tool_search_paths")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "search_tests":
        tool_fn = _resolve_tool_func("_tool_search_tests")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "search_symbols":
        tool_fn = _resolve_tool_func("_tool_search_symbols")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "get_tree_outline":
        tool_fn = _resolve_tool_func("_tool_get_tree_outline")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "project_summary":
        tool_fn = _resolve_tool_func("_tool_project_summary")
        return _validate_tool_result(name, tool_fn(project_id, root, args))
    if name == "search_text":
        tool_fn = _resolve_tool_func("_tool_search_text")
        return _validate_tool_result(
            name, tool_fn(project_id, root, args, max_file_chars=max_file_chars)
        )
    if name == "search_semantic":
        tool_fn = _resolve_tool_func("_tool_search_semantic")
        return _validate_tool_result(
            name, tool_fn(project_id, root, args, max_file_chars=max_file_chars)
        )
    if name == "search_routes":
        tool_fn = _resolve_tool_func("_tool_search_routes")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "search_api_calls":
        tool_fn = _resolve_tool_func("_tool_search_api_calls")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "route_usages":
        tool_fn = _resolve_tool_func("_tool_route_usages")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "suggest_endpoint_location":
        tool_fn = _resolve_tool_func("_tool_suggest_endpoint_location")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "suggest_frontend_client":
        tool_fn = _resolve_tool_func("_tool_suggest_frontend_client")
        return _validate_tool_result(name, tool_fn(project_id, root, args))
    if name == "impact_route_change":
        tool_fn = _resolve_tool_func("_tool_impact_route_change")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "api_coverage_summary":
        tool_fn = _resolve_tool_func("_tool_api_coverage_summary")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "unmatched_routes":
        tool_fn = _resolve_tool_func("_tool_unmatched_routes")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "unmatched_calls":
        tool_fn = _resolve_tool_func("_tool_unmatched_calls")
        return _validate_tool_result(name, tool_fn(project_id, args))
    if name == "compare_api_contract":
        tool_fn = _resolve_tool_func("_tool_compare_api_contract")
        return _validate_tool_result(name, tool_fn(project_id, root, args))
    if name == "suggest_contract_fix":
        tool_fn = _resolve_tool_func("_tool_suggest_contract_fix")
        return _validate_tool_result(name, tool_fn(project_id, root, meta, args))
    if name == "suggest_api_fix":
        tool_fn = _resolve_tool_func("_tool_suggest_api_fix")
        return _validate_tool_result(name, tool_fn(project_id, root, meta, args))
    return _validate_tool_result(name, _tool_error("unknown_tool", f"Unknown tool: {name}"))
