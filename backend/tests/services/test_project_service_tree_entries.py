import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.models import FileNode
from app.services import project_service


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def exec(self, query):
        return _FakeResult(self._rows)


def test_list_project_tree_entries_exact_limit_without_extra_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        FileNode(project_id=1, path="a.py", language="python"),
        FileNode(project_id=1, path="b.py", language="python"),
    ]

    monkeypatch.setattr(project_service, "get_project", lambda project_id, org_id: object())
    monkeypatch.setattr(project_service, "get_session", lambda: _FakeSession(rows))

    result = project_service.list_project_tree_entries(project_id=1, org_id=1, limit=2)

    assert result["meta"]["returned"] == 2
    assert result["meta"]["truncated"] is False
    assert result["meta"]["next_cursor"] is None
