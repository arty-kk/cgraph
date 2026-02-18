import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIRS = (
    BACKEND_ROOT / "app" / "api",
    BACKEND_ROOT / "app" / "services",
    BACKEND_ROOT / "app" / "llm" / "agentic",
)
CRITICAL_RUNTIME_FILES = (
    BACKEND_ROOT / "app" / "graph.py",
    BACKEND_ROOT / "app" / "scan.py",
    BACKEND_ROOT / "app" / "search.py",
    BACKEND_ROOT / "app" / "utils.py",
)
# Explicit whitelist for runtime-only exceptions that are acceptable in offline/dev flows.
# Keep empty by default: runtime contract requires AsyncSession/AsyncSessionLocal everywhere.
OFFLINE_DEV_ONLY_ALLOWLIST: dict[tuple[str, str], str] = {}
MIXED_RUNTIME_FILES = {
    BACKEND_ROOT / "app" / "graph.py",
    BACKEND_ROOT / "app" / "scan.py",
    BACKEND_ROOT / "app" / "search.py",
}
FORBIDDEN_SYNC_DB_CALLS = {
    "get_session",
    "compute_graph_metrics",
    "search_semantic",
}


def _iter_runtime_files() -> list[Path]:
    files: set[Path] = set()
    for base in RUNTIME_DIRS:
        files.update(sorted(base.rglob("*.py")))
    files.update(CRITICAL_RUNTIME_FILES)
    return sorted(files)


def _allowlisted(path: Path, symbol: str) -> bool:
    rel_path = path.relative_to(BACKEND_ROOT).as_posix()
    return (rel_path, symbol) in OFFLINE_DEV_ONLY_ALLOWLIST


def _find_local_sync_db_helpers(tree: ast.AST) -> set[str]:
    sync_helpers: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id == "get_session":
                sync_helpers.add(node.name)
                break
    return sync_helpers


def _collect_async_sync_db_violations(path: Path, tree: ast.AST) -> list[str]:
    forbidden_calls = set(FORBIDDEN_SYNC_DB_CALLS)
    violations: list[str] = []

    for async_fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)):
        for node in ast.walk(async_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in forbidden_calls and not _allowlisted(path, node.func.id):
                    violations.append(
                        f"{path}:{node.lineno}:{async_fn.name} -> sync call `{node.func.id}`"
                    )
            if isinstance(node, ast.Name) and node.id == "Session":
                if not _allowlisted(path, "Session"):
                    violations.append(
                        f"{path}:{node.lineno}:{async_fn.name} -> sync type `Session`"
                    )

    return violations


def test_runtime_modules_do_not_import_sync_db_session_primitives() -> None:
    violations: list[str] = []
    for path in _iter_runtime_files():
        if path in MIXED_RUNTIME_FILES:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                if "get_session" in names and (node.module or "").endswith("db"):
                    if not _allowlisted(path, "get_session"):
                        violations.append(f"{path}:{node.lineno}:get_session")
                if node.module in {"sqlalchemy.orm", "sqlmodel"} and "Session" in names:
                    if not _allowlisted(path, "Session"):
                        violations.append(f"{path}:{node.lineno}:Session")

    assert not violations, (
        "Runtime modules must use AsyncSession/AsyncSessionLocal instead of sync DB primitives: "
        + ", ".join(violations)
    )


def test_mixed_runtime_modules_do_not_use_sync_db_primitives_inside_async_functions() -> None:
    violations: list[str] = []
    for path in sorted(MIXED_RUNTIME_FILES):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations.extend(_collect_async_sync_db_violations(path, tree))

    assert not violations, (
        "Async runtime paths must perform DB I/O only via AsyncSession/AsyncSessionLocal; "
        "sync DB primitives are forbidden inside async def: "
        + ", ".join(violations)
    )


def test_mixed_runtime_async_functions_do_not_call_local_sync_db_helpers() -> None:
    violations: list[str] = []
    for path in sorted(MIXED_RUNTIME_FILES):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        local_sync_helpers = _find_local_sync_db_helpers(tree)
        if not local_sync_helpers:
            continue

        for async_fn in (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)):
            for node in ast.walk(async_fn):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id in local_sync_helpers and not _allowlisted(path, node.func.id):
                    violations.append(
                        f"{path}:{node.lineno}:{async_fn.name} -> local sync helper `{node.func.id}`"
                    )

    assert not violations, (
        "Async runtime paths must not call local sync DB helpers; use AsyncSession/AsyncSessionLocal: "
        + ", ".join(violations)
    )




def test_runtime_async_functions_do_not_call_sync_search_semantic() -> None:
    violations: list[str] = []
    for path in _iter_runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                if isinstance(call.func, ast.Name) and call.func.id == "search_semantic":
                    if not _allowlisted(path, "search_semantic"):
                        violations.append(f"{path}:{call.lineno}:{node.name}")

    assert not violations, (
        "Async runtime paths must not call sync search_semantic(); use search_semantic_async with AsyncSession: "
        + ", ".join(violations)
    )


def test_agentic_async_tools_do_not_call_sync_search_semantic_or_get_session() -> None:
    path = BACKEND_ROOT / "app" / "llm" / "agentic" / "tools.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or not node.name.startswith("_tool_"):
            continue
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            if isinstance(call.func, ast.Name) and call.func.id in {"search_semantic", "get_session"}:
                violations.append(f"{path}:{call.lineno}:{node.name} -> {call.func.id}")

    assert not violations, (
        "Async agentic tools must not call sync search_semantic()/get_session(): "
        + ", ".join(violations)
    )

def test_runtime_async_functions_do_not_call_sync_cache_or_celery_directly() -> None:
    forbidden_cache_calls = {
        "cache_get_json",
        "cache_set_json",
        "cache_invalidate_prefix",
    }
    cache_violations: list[str] = []
    celery_violations: list[str] = []

    for path in _iter_runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                func = call.func
                if isinstance(func, ast.Name) and func.id in forbidden_cache_calls:
                    cache_violations.append(f"{path}:{call.lineno}")
                if isinstance(func, ast.Attribute) and func.attr == "apply_async":
                    celery_violations.append(f"{path}:{call.lineno}")

    assert not cache_violations, (
        "Forbidden sync cache calls in async runtime functions: "
        + ", ".join(cache_violations)
    )
    assert not celery_violations, (
        "Forbidden direct Celery apply_async in async runtime functions: "
        + ", ".join(celery_violations)
    )
