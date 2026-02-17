import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIRS = (
    BACKEND_ROOT / "app" / "api",
    BACKEND_ROOT / "app" / "services",
    BACKEND_ROOT / "app" / "llm" / "agentic",
)



def _iter_runtime_files() -> list[Path]:
    files: list[Path] = []
    for base in RUNTIME_DIRS:
        files.extend(
            sorted(
                p
                for p in base.rglob("*.py")
                if "offline" not in p.parts and "offline" not in p.name
            )
        )
    return files


def test_runtime_modules_do_not_import_db_get_session() -> None:
    violations: list[str] = []
    for path in _iter_runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                if "get_session" in names and (node.module or "").endswith("db"):
                    violations.append(f"{path}:{node.lineno}")
    assert not violations, "Forbidden get_session import in runtime modules: " + ", ".join(violations)


def test_runtime_modules_do_not_use_sync_session_type() -> None:
    violations: list[str] = []
    for path in _iter_runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {"sqlalchemy.orm", "sqlmodel"}:
                for alias in node.names:
                    if alias.name == "Session":
                        violations.append(f"{path}:{node.lineno}")
    assert not violations, "Forbidden sync Session import in runtime modules: " + ", ".join(violations)
