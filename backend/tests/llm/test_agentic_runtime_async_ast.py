from __future__ import annotations

import ast
from pathlib import Path


TOOLS_PATH = Path("backend/app/llm/agentic/tools.py")
DISPATCH_PATH = Path("backend/app/llm/agentic/dispatch.py")

RUNTIME_ASYNC_FUNCS = {
    "_tool_search_text_async",
    "_tool_route_usages_async",
    "_tool_suggest_endpoint_location_async",
    "_tool_suggest_frontend_client_async",
    "_tool_impact_route_change_async",
    "_tool_compare_api_contract_async",
    "_tool_suggest_contract_fix_async",
    "_tool_suggest_api_fix_async",
}


def _load_ast(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_runtime_async_tool_path_has_no_sync_session_helpers() -> None:
    module = _load_ast(TOOLS_PATH)
    fn_nodes = {
        node.name: node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    for fn_name in RUNTIME_ASYNC_FUNCS:
        fn = fn_nodes[fn_name]
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            name = ""
            if isinstance(call.func, ast.Name):
                name = call.func.id
            elif isinstance(call.func, ast.Attribute):
                name = call.func.attr
            assert name not in {"_offline_get_session", "get_session"}, (
                f"{fn_name} uses sync DB helper call: {name}"
            )


def test_async_functions_do_not_call_sync_search_text_paths() -> None:
    module = _load_ast(TOOLS_PATH)
    for fn in [n for n in module.body if isinstance(n, ast.AsyncFunctionDef)]:
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            if isinstance(call.func, ast.Name) and call.func.id == "search_text_paths":
                raise AssertionError(
                    f"async function {fn.name} calls sync search_text_paths()"
                )


def test_dispatch_passes_session_to_search_text_async() -> None:
    module = _load_ast(DISPATCH_PATH)
    src = DISPATCH_PATH.read_text(encoding="utf-8")
    assert '"search_text": (' in src
    assert '(session, project_id, root, args)' in src
