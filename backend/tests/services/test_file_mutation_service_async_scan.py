import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import file_mutation_service


@pytest.mark.anyio
async def test_run_mutation_indexing_async_uses_async_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scan_files_async(project_id, org_id, root, rel_paths):
        assert project_id == 1
        assert org_id == 2
        assert root == Path("/repo")
        assert rel_paths == ["a.py"]
        return {"aborted": False, "removed_edge_neighbors": ["x.py"]}

    async def _fake_update_graph_metrics_incremental_async(
        session, project_id, rel_paths, removed_edge_neighbors=None
    ):
        assert session == "session"
        assert project_id == 1
        assert rel_paths == ["a.py"]
        assert removed_edge_neighbors == ["x.py"]
        return True

    monkeypatch.setattr(file_mutation_service, "scan_files_async", _fake_scan_files_async)
    monkeypatch.setattr(
        file_mutation_service,
        "update_graph_metrics_incremental_async",
        _fake_update_graph_metrics_incremental_async,
    )

    result = await file_mutation_service.run_mutation_indexing_async(
        "session",
        project_id=1,
        org_id=2,
        root=Path("/repo"),
        rel_paths=["a.py"],
    )

    assert result["ok"] is True
    assert result["metrics_pending"] is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scan_reindexed", "expected_removed_neighbors"),
    [
        ({"aborted": False, "removed_edge_neighbors": "x.py"}, None),
        ({"aborted": False, "removed_edge_neighbors": {"path": "x.py"}}, None),
        (
            {"aborted": False, "removed_edge_neighbors": ["ok.py", "", 123, None]},
            ["ok.py"],
        ),
    ],
)
async def test_run_mutation_indexing_async_normalizes_removed_neighbors(
    monkeypatch: pytest.MonkeyPatch,
    scan_reindexed: dict,
    expected_removed_neighbors: list[str] | None,
) -> None:
    async def _fake_scan_files_async(project_id, org_id, root, rel_paths):
        _ = (project_id, org_id, root, rel_paths)
        return scan_reindexed

    async def _fake_update_graph_metrics_incremental_async(
        session, project_id, rel_paths, removed_edge_neighbors=None
    ):
        assert session == "session"
        assert project_id == 1
        assert rel_paths == ["a.py"]
        assert removed_edge_neighbors == expected_removed_neighbors
        return False

    monkeypatch.setattr(file_mutation_service, "scan_files_async", _fake_scan_files_async)
    monkeypatch.setattr(
        file_mutation_service,
        "update_graph_metrics_incremental_async",
        _fake_update_graph_metrics_incremental_async,
    )

    result = await file_mutation_service.run_mutation_indexing_async(
        "session",
        project_id=1,
        org_id=2,
        root=Path("/repo"),
        rel_paths=["a.py"],
    )

    assert result["ok"] is True
