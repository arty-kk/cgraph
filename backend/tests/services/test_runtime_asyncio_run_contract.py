import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
ASYNCIO_RUN_ALLOWLIST: set[str] = set()
THREADING_LOCK_ALLOWLIST: set[str] = set()
ASYNC_RUNTIME_LOCK_MODULES = {
    "app/infra/redis_client.py",
    "app/services/task_queue.py",
    "app/infra/async_worker_runtime.py",
}
FORBIDDEN_WORKER_GLOBALS = {"_worker_loop", "_worker_loop_thread", "_worker_loop_ready"}
WORKER_RUNTIME_MODULES = {
    "app/celery_tasks.py",
    "app/infra/async_worker_runtime.py",
    "app/services/task_queue.py",
}
FORBIDDEN_SYNC_BRIDGES = {"run", "run_until_complete", "run_coroutine_threadsafe"}
FORBIDDEN_OWNERS = {"asyncio", "Runner"}


def _contains_asyncio_run(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "run":
            continue
        owner = func.value
        if isinstance(owner, ast.Name) and owner.id == "asyncio":
            return True
    return False


def _contains_forbidden_calls(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "run_coroutine_threadsafe":
            return True
    return False


def _contains_threading_lock_usage(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    threading_aliases = {"threading"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "threading":
                    threading_aliases.add(alias.asname or alias.name)
        if isinstance(node, ast.ImportFrom) and node.module == "threading":
            for alias in node.names:
                if alias.name == "Lock":
                    return True
        if isinstance(node, ast.Attribute):
            if (
                node.attr == "Lock"
                and isinstance(node.value, ast.Name)
                and node.value.id in threading_aliases
            ):
                return True
    return False


def _contains_forbidden_globals(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in FORBIDDEN_WORKER_GLOBALS:
                return True
    return False


def _collect_sync_bridge_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_SYNC_BRIDGES:
            if isinstance(func.value, ast.Name) and func.value.id in FORBIDDEN_OWNERS:
                violations.append(f"{path.relative_to(BACKEND_ROOT).as_posix()}:{node.lineno}")
            if func.attr == "run_until_complete":
                violations.append(f"{path.relative_to(BACKEND_ROOT).as_posix()}:{node.lineno}")
    return violations


def test_runtime_modules_do_not_use_asyncio_run_outside_allowlist() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if rel in ASYNCIO_RUN_ALLOWLIST:
            continue
        if _contains_asyncio_run(path):
            violations.append(rel)

    assert not violations, "asyncio.run is forbidden in runtime modules: " + ", ".join(violations)


def test_runtime_modules_do_not_use_run_coroutine_threadsafe() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if _contains_forbidden_calls(path):
            violations.append(rel)
    assert not violations, (
        "run_coroutine_threadsafe is forbidden in runtime modules: " + ", ".join(violations)
    )


def test_worker_runtime_modules_forbid_sync_asyncio_bridges() -> None:
    violations: list[str] = []
    for rel in sorted(WORKER_RUNTIME_MODULES):
        violations.extend(_collect_sync_bridge_calls(BACKEND_ROOT / rel))
    assert not violations, "Sync asyncio bridges are forbidden in worker runtime modules: " + ", ".join(violations)


def test_worker_task_dispatch_module_has_no_loop_thread_globals() -> None:
    worker_tasks = APP_ROOT / "celery_tasks.py"
    assert not _contains_forbidden_globals(worker_tasks)


def test_scan_runtime_does_not_use_call_soon_threadsafe() -> None:
    scan_module = (APP_ROOT / "scan.py").read_text(encoding="utf-8")
    assert "call_soon_threadsafe" not in scan_module


def test_async_runtime_modules_do_not_use_threading_lock() -> None:
    violations: list[str] = []
    for rel in sorted(ASYNC_RUNTIME_LOCK_MODULES):
        if rel in THREADING_LOCK_ALLOWLIST:
            continue
        path = BACKEND_ROOT / rel
        if _contains_threading_lock_usage(path):
            violations.append(rel)

    assert not violations, (
        "threading.Lock is forbidden in async runtime modules: " + ", ".join(violations)
    )
