from __future__ import annotations

import ast
from pathlib import Path


def test_tests_do_not_import_app_db_or_get_session() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.db":
                names = {alias.name for alias in node.names}
                if "get_session" in names or names:
                    offenders.append(f"{path.relative_to(root.parent)}:{node.lineno} from app.db import ...")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.db":
                        offenders.append(f"{path.relative_to(root.parent)}:{node.lineno} import app.db")

    assert not offenders, "Forbidden app.db imports found:\n" + "\n".join(offenders)
