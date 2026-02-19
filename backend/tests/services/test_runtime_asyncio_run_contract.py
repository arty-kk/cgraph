import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
ALLOWLIST: set[str] = set()


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


def test_runtime_modules_do_not_use_asyncio_run_outside_allowlist() -> None:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        if _contains_asyncio_run(path):
            violations.append(rel)

    assert not violations, (
        "asyncio.run is allowed only in worker adapters: " + ", ".join(violations)
    )
