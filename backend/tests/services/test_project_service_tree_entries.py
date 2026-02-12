import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.models import FileNode
from app.services import project_service


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeAsyncSession:
    def __init__(self, rows):
        self._rows = rows

    async def get(self, model, project_id):
        return type('P', (), {'id': project_id, 'org_id': 1})()

    async def execute(self, query):
        return _FakeResult(self._rows)


@pytest.mark.anyio
async def test_list_project_tree_entries_exact_limit_without_extra_rows() -> None:
    rows = [
        FileNode(project_id=1, path="a.py", language="python"),
        FileNode(project_id=1, path="b.py", language="python"),
    ]

    result = await project_service.list_project_tree_entries_async(
        _FakeAsyncSession(rows), project_id=1, org_id=1, limit=2
    )

    assert result["meta"]["returned"] == 2
    assert result["meta"]["truncated"] is False
    assert result["meta"]["next_cursor"] is None
