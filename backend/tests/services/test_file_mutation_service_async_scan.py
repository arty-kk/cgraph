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

    def _fake_update_graph_metrics_incremental(project_id, rel_paths, removed_edge_neighbors=None):
        assert project_id == 1
        assert rel_paths == ["a.py"]
        assert removed_edge_neighbors == ["x.py"]
        return True

    monkeypatch.setattr(file_mutation_service, "scan_files_async", _fake_scan_files_async)
    monkeypatch.setattr(
        file_mutation_service,
        "update_graph_metrics_incremental",
        _fake_update_graph_metrics_incremental,
    )

    result = await file_mutation_service.run_mutation_indexing_async(
        project_id=1,
        org_id=2,
        root=Path("/repo"),
        rel_paths=["a.py"],
    )

    assert result["ok"] is True
    assert result["metrics_pending"] is True
