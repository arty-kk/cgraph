import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _calls_send_task(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "send_task":
                return True
    return False


def _contains_background_query(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.arg == "background":
            return True
    return False


def test_task_queue_has_no_sync_send_task_fallback() -> None:
    task_queue_path = BACKEND_ROOT / "app" / "services" / "task_queue.py"
    assert not _calls_send_task(task_queue_path)


def test_queue_api_endpoints_have_no_background_compat_arg() -> None:
    projects_path = BACKEND_ROOT / "app" / "api" / "projects.py"
    tasks_path = BACKEND_ROOT / "app" / "api" / "tasks.py"
    assert not _contains_background_query(projects_path)
    assert not _contains_background_query(tasks_path)
