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
        cursor = None
        for criterion in getattr(query, "_where_criteria", ()):
            left = getattr(criterion, "left", None)
            if getattr(left, "name", None) != "path":
                continue
            if getattr(getattr(criterion, "operator", None), "__name__", "") != "gt":
                continue
            cursor = getattr(getattr(criterion, "right", None), "value", None)

        rows = self._rows
        if isinstance(cursor, str) and cursor:
            rows = [row for row in rows if isinstance(row.path, str) and row.path > cursor]

        limit_clause = getattr(query, "_limit_clause", None)
        if limit_clause is not None:
            limit_value = getattr(limit_clause, "value", None)
            if isinstance(limit_value, int):
                rows = rows[:limit_value]

        return _FakeResult(rows)


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


@pytest.mark.anyio
async def test_list_project_tree_entries_cursor_progresses_by_returned_entries() -> None:
    rows = [
        FileNode(project_id=1, path="a/x.py", language="python"),
        FileNode(project_id=1, path="a/y.py", language="python"),
        FileNode(project_id=1, path="b/z.py", language="python"),
    ]

    page_1 = await project_service.list_project_tree_entries_async(
        _FakeAsyncSession(rows), project_id=1, org_id=1, limit=1
    )

    assert page_1["entries"] == [
        {
            "type": "dir",
            "path": "a",
            "name": "a",
            "has_children": True,
        }
    ]
    assert page_1["meta"]["truncated"] is True
    assert page_1["meta"]["next_cursor"] == "a/y.py"

    page_2 = await project_service.list_project_tree_entries_async(
        _FakeAsyncSession(rows),
        project_id=1,
        org_id=1,
        limit=1,
        cursor=page_1["meta"]["next_cursor"],
    )

    assert page_2["entries"] == [
        {
            "type": "dir",
            "path": "b",
            "name": "b",
            "has_children": True,
        }
    ]
    assert page_2["meta"]["cursor"] == "a/y.py"
    assert page_2["meta"]["truncated"] is False
    assert page_2["meta"]["next_cursor"] is None
