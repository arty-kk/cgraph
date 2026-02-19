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

RUNTIME_SEARCH_ASYNC_FUNCS = {
    "_tool_search_text_async",
    "_tool_search_semantic_async",
    "_tool_search_tests_async",
    "_tool_search_symbols_async",
    "_tool_search_routes_async",
    "_tool_search_api_calls_async",
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


def test_dispatch_passes_session_to_runtime_async_tools() -> None:
    _ = _load_ast(DISPATCH_PATH)
    src = DISPATCH_PATH.read_text(encoding="utf-8")
    assert '"get_node": ("_tool_get_node_async", (session, project_id, root, args), {})' in src
    assert (
        '"get_neighbors": ("_tool_get_neighbors_async", (session, project_id, root, args), {})'
        in src
    )
    assert '"search_paths": ("_tool_search_paths_async", (session, project_id, args), {})' in src
    assert '"search_tests": ("_tool_search_tests_async", (session, project_id, args), {})' in src
    assert '"search_symbols": ("_tool_search_symbols_async", (session, project_id, args), {})' in src
    assert '"get_tree_outline": ("_tool_get_tree_outline_async", (session, project_id, args), {})' in src
    assert (
        '"project_summary": ("_tool_project_summary_async", (session, project_id, root, args), {})'
        in src
    )
    assert '"search_text": (' in src
    assert '"search_semantic": (' in src
    assert '"search_routes": ("_tool_search_routes_async", (session, project_id, args), {})' in src
    assert '"search_api_calls": ("_tool_search_api_calls_async", (session, project_id, args), {})' in src
    assert '"route_usages": ("_tool_route_usages_async", (session, project_id, args), {})' in src
    assert (
        '"suggest_endpoint_location": (\n            "_tool_suggest_endpoint_location_async",\n            (session, project_id, args),\n            {},\n        ),'
        in src
    )
    assert (
        '"suggest_frontend_client": (\n            "_tool_suggest_frontend_client_async",\n            (session, project_id, root, args),\n            {},\n        ),'
        in src
    )
    assert (
        '"impact_route_change": ("_tool_impact_route_change_async", (session, project_id, args), {})'
        in src
    )
    assert (
        '"api_coverage_summary": ("_tool_api_coverage_summary_async", (session, project_id, args), {})'
        in src
    )
    assert '"unmatched_routes": ("_tool_unmatched_routes_async", (session, project_id, args), {})' in src
    assert '"unmatched_calls": ("_tool_unmatched_calls_async", (session, project_id, args), {})' in src
    assert (
        '"compare_api_contract": (\n            "_tool_compare_api_contract_async",\n            (session, project_id, root, args),\n            {},\n        ),'
        in src
    )
    assert (
        '"suggest_contract_fix": (\n            "_tool_suggest_contract_fix_async",\n            (session, project_id, root, meta, args),\n            {},\n        ),'
        in src
    )
    assert (
        '"suggest_api_fix": (\n            "_tool_suggest_api_fix_async",\n            (session, project_id, root, meta, args),\n            {},\n        ),'
        in src
    )
    assert src.count("(session, project_id, root, args)") >= 2


def test_runtime_search_async_functions_avoid_direct_file_io_calls() -> None:
    module = _load_ast(TOOLS_PATH)
    fn_nodes = {
        node.name: node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef)
    }

    def _iter_calls_outside_nested_defs(node: ast.AST):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Call):
                yield child
            yield from _iter_calls_outside_nested_defs(child)

    banned_attrs = {"open", "read", "read_text", "read_bytes"}
    for fn_name in RUNTIME_SEARCH_ASYNC_FUNCS:
        fn = fn_nodes[fn_name]
        for call in _iter_calls_outside_nested_defs(fn):
            if isinstance(call.func, ast.Name) and call.func.id == "open":
                raise AssertionError(f"{fn_name} has direct open() call in async runtime path")
            if isinstance(call.func, ast.Attribute) and call.func.attr in banned_attrs:
                raise AssertionError(
                    f"{fn_name} has direct .{call.func.attr}() call in async runtime path"
                )
