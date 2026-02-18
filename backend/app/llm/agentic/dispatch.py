from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ...async_db import AsyncSessionLocal
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
    async def _run() -> dict:
        async with AsyncSessionLocal() as session:
            return await _dispatch_tool_async(
                session,
                project_id,
                root,
                meta,
                name,
                args,
                max_file_chars=max_file_chars,
            )

    return asyncio.run(_run())


async def _dispatch_tool_async(
    session: AsyncSession,
    project_id: int,
    root: Path,
    meta: AgenticMeta,
    name: str,
    args: dict,
    *,
    max_file_chars: int,
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

    async def _call_tool(
        name_local: str,
        fn: Callable[..., Any],
        *fn_args: Any,
        **fn_kwargs: Any,
    ) -> dict:
        out = fn(*fn_args, **fn_kwargs)
        if hasattr(out, "__await__"):
            out = await out
        return _validate_tool_result(name_local, out)

    if name == "plan_retrieval":
        required_fields = (
            "goal",
            "hypotheses",
            "search_steps",
            "read_steps",
            "candidate_ranking",
        )
        if not isinstance(args, dict):
            return _validate_tool_result(
                name,
                _tool_error(
                    "bad_args",
                    "Invalid plan_retrieval args: expected object with required fields "
                    f"{', '.join(required_fields)}; got {type(args).__name__}.",
                ),
            )
        missing_fields = [field for field in required_fields if field not in args]
        invalid_fields = [
            field
            for field in required_fields
            if field in args and args.get(field) is None
        ]
        if missing_fields or invalid_fields:
            details: list[str] = []
            if missing_fields:
                details.append(f"missing fields: {', '.join(missing_fields)}")
            if invalid_fields:
                details.append(f"invalid fields: {', '.join(invalid_fields)}")
            return _validate_tool_result(
                name,
                _tool_error(
                    "bad_args",
                    "Invalid plan_retrieval args: " + "; ".join(details) + ".",
                ),
            )
        meta.retrieval_plan = dict(args)
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
        fn = _resolve_tool_func("_tool_get_file_async")
        return await _call_tool(
            name,
            fn,
            project_id,
            root,
            meta,
            args,
            max_file_chars=max_file_chars,
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
        fn = _resolve_tool_func("_tool_get_file_lines_async")
        return await _call_tool(
            name,
            fn,
            project_id,
            root,
            meta,
            args,
            max_file_chars=max_file_chars,
        )

    mapping = {
        "get_contract": ("_tool_get_contract_async", (session, project_id, root, meta, args), {}),
        "get_symbol": ("_tool_get_symbol_async", (session, project_id, root, meta, args), {}),
        "get_node": ("_tool_get_node_async", (session, project_id, root, args), {}),
        "get_neighbors": ("_tool_get_neighbors_async", (session, project_id, root, args), {}),
        "search_paths": ("_tool_search_paths_async", (session, project_id, args), {}),
        "search_tests": ("_tool_search_tests_async", (session, project_id, args), {}),
        "search_symbols": ("_tool_search_symbols_async", (session, project_id, args), {}),
        "get_tree_outline": ("_tool_get_tree_outline_async", (session, project_id, args), {}),
        "project_summary": ("_tool_project_summary_async", (session, project_id, root, args), {}),
        "search_text": (
            "_tool_search_text_async",
            (session, project_id, root, args),
            {"max_file_chars": max_file_chars},
        ),
        "search_semantic": (
            "_tool_search_semantic_async",
            (session, project_id, root, args),
            {"max_file_chars": max_file_chars},
        ),
        "search_routes": ("_tool_search_routes_async", (session, project_id, args), {}),
        "search_api_calls": ("_tool_search_api_calls_async", (session, project_id, args), {}),
        "route_usages": ("_tool_route_usages_async", (session, project_id, args), {}),
        "suggest_endpoint_location": (
            "_tool_suggest_endpoint_location_async",
            (session, project_id, args),
            {},
        ),
        "suggest_frontend_client": (
            "_tool_suggest_frontend_client_async",
            (session, project_id, root, args),
            {},
        ),
        "impact_route_change": ("_tool_impact_route_change_async", (session, project_id, args), {}),
        "api_coverage_summary": ("_tool_api_coverage_summary_async", (session, project_id, args), {}),
        "unmatched_routes": ("_tool_unmatched_routes_async", (session, project_id, args), {}),
        "unmatched_calls": ("_tool_unmatched_calls_async", (session, project_id, args), {}),
        "compare_api_contract": (
            "_tool_compare_api_contract_async",
            (session, project_id, root, args),
            {},
        ),
        "suggest_contract_fix": (
            "_tool_suggest_contract_fix_async",
            (session, project_id, root, meta, args),
            {},
        ),
        "suggest_api_fix": (
            "_tool_suggest_api_fix_async",
            (session, project_id, root, meta, args),
            {},
        ),
    }
    spec = mapping.get(name)
    if spec is None:
        return _validate_tool_result(
            name,
            _tool_error("unknown_tool", f"Unknown tool: {name}"),
        )
    attr, fn_args, fn_kwargs = spec
    fn = _resolve_tool_func(attr)
    return await _call_tool(name, fn, *fn_args, **fn_kwargs)
