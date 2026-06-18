import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.infra import cpu_runtime, fs_runtime
from app.services import project_service


@pytest.mark.anyio
async def test_read_text_if_file_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        called["func"] = func
        called["args"] = args
        called["kwargs"] = kwargs
        return "payload"

    monkeypatch.setattr(project_service, "run_fs_io_async", _fake_cpu_runtime)

    result = await project_service._read_text_if_file_async(Path("/tmp/test.txt"), 123)

    assert result == "payload"
    assert called["func"] is project_service._read_text_if_file
    assert called["args"] == (Path("/tmp/test.txt"), 123)
    assert called["kwargs"] == {"operation": "project.read_text_if_file", "lane": "interactive"}


@pytest.mark.anyio
async def test_resolve_under_root_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        called["func"] = func
        called["args"] = args
        called["kwargs"] = kwargs
        return (Path("/repo/a.py"), "a.py")

    monkeypatch.setattr(project_service, "run_fs_io_async", _fake_cpu_runtime)

    result = await project_service._resolve_under_root_async(
        Path("/repo"),
        "a.py",
        max_length=120,
    )

    assert result == (Path("/repo/a.py"), "a.py")
    assert called["func"] is project_service.resolve_under_root
    assert called["args"] == (Path("/repo"), "a.py")
    assert called["kwargs"] == {"max_length": 120, "operation": "project.resolve_under_root", "lane": "interactive"}


@pytest.mark.anyio
async def test_read_project_files_async_collects_and_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int, int]] = []

    async def _fake_resolve_and_read_text_under_root_async(
        root,
        rel_path,
        *,
        max_rel_path_length,
        max_chars,
    ):
        calls.append((rel_path, max_rel_path_length, max_chars))
        if rel_path == "bad":
            return None
        if rel_path == "missing.py":
            return None
        return rel_path, f"txt:{Path(rel_path).name}"

    monkeypatch.setattr(
        project_service,
        "_resolve_and_read_text_under_root_async",
        _fake_resolve_and_read_text_under_root_async,
    )

    result = await project_service._read_project_files_async(
        Path("/repo"),
        ["a.py", "bad", "missing.py", "a.py"],
        max_chars=77,
        max_parallel=2,
    )

    assert result == {"a.py": "txt:a.py"}
    assert sorted(calls, key=lambda x: x[0]) == [
        ("a.py", project_service.settings.max_rel_path_chars, 77),
        ("a.py", project_service.settings.max_rel_path_chars, 77),
        ("bad", project_service.settings.max_rel_path_chars, 77),
        ("missing.py", project_service.settings.max_rel_path_chars, 77),
    ]


@pytest.mark.anyio
async def test_resolve_and_read_text_under_root_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ("a.py", "payload")

    monkeypatch.setattr(project_service, "run_fs_io_async", _fake_cpu_runtime)

    result = await project_service._resolve_and_read_text_under_root_async(
        Path("/repo"),
        "a.py",
        max_rel_path_length=111,
        max_chars=222,
    )

    assert result == ("a.py", "payload")
    assert calls["func"] is project_service._resolve_and_read_text_under_root
    assert calls["args"] == (Path("/repo"), "a.py")
    assert calls["kwargs"] == {
        "max_rel_path_length": 111,
        "max_chars": 222,
        "operation": "project.resolve_and_read",
        "lane": "interactive",
    }


@pytest.mark.anyio
async def test_score_semantic_rows_async_uses_cpu_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return 1, [{"path": "a.py", "score": 1.0}]

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    result = await project_service._score_semantic_rows_async(
        [("a.py", 0, "[0.1, 0.2]", "sym", 1, 1)],
        query_embedding=[0.1, 0.2],
        file_cache={"a.py": "line1\nline2"},
        chunk_size=100,
        step=80,
    )

    assert result == (1, [{"path": "a.py", "score": 1.0}])
    assert calls["func"] is project_service._score_semantic_rows
    assert calls["args"] == ([("a.py", 0, "[0.1, 0.2]", "sym", 1, 1)],)
    assert calls["kwargs"] == {
        "query_embedding": [0.1, 0.2],
        "file_cache": {"a.py": "line1\nline2"},
        "chunk_size": 100,
        "step": 80,
        "operation": "project.score_semantic_rows",
    }


@pytest.mark.anyio
async def test_find_text_matches_in_payload_async_uses_cpu_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"line": 1, "col": 1, "snippet": "abc", "truncated_file": False}], True)

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    result = await project_service._find_text_matches_in_payload_async(
        "abc",
        needle="a",
        needle_cmp="a",
        case_sensitive=False,
        context_chars=100,
        limit_matches=10,
        start_count=0,
        truncated_flag=False,
    )

    assert result == ([{"line": 1, "col": 1, "snippet": "abc", "truncated_file": False}], True)
    assert calls["func"] is project_service._find_text_matches_in_payload
    assert calls["args"] == ("abc",)
    assert calls["kwargs"] == {
        "needle": "a",
        "needle_cmp": "a",
        "case_sensitive": False,
        "context_chars": 100,
        "limit_matches": 10,
        "start_count": 0,
        "truncated_flag": False,
        "operation": "project.find_text_matches",
    }


@pytest.mark.anyio
async def test_score_semantic_rows_async_passes_pickle_safe_rows_to_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return 0, []

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    rows = [("a.py", 0, "[0.1]", None, None, None)]
    await project_service._score_semantic_rows_async(
        rows,
        query_embedding=[0.1],
        file_cache={"a.py": "a"},
        chunk_size=10,
        step=8,
    )

    assert captured["func"] is project_service._score_semantic_rows
    assert isinstance(captured["args"][0], list)
    assert isinstance(captured["args"][0][0], tuple)


@pytest.mark.anyio
async def test_build_graph_node_payload_async_uses_cpu_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"id": "a.py"}], ["a.py"])

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    node_row = object()
    result = await project_service._build_graph_node_payload_async([node_row])

    assert result == ([{"id": "a.py"}], ["a.py"])
    assert calls["func"] is project_service._build_graph_node_payload
    assert calls["args"] == ([node_row],)
    assert calls["kwargs"] == {"operation": "project.build_graph_nodes"}


@pytest.mark.anyio
async def test_build_graph_edge_payload_async_uses_cpu_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return [{"source": "a.py", "target": "b.py", "kind": "import"}]

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    edge_row = object()
    result = await project_service._build_graph_edge_payload_async(
        [edge_row],
        effective_limit=10,
        node_set={"a.py", "b.py"},
    )

    assert result == [{"source": "a.py", "target": "b.py", "kind": "import"}]
    assert calls["func"] is project_service._build_graph_edge_payload
    assert calls["args"] == ([edge_row],)
    assert calls["kwargs"] == {"effective_limit": 10, "node_set": {"a.py", "b.py"}, "operation": "project.build_graph_edges"}


@pytest.mark.anyio
async def test_build_local_graph_payload_async_uses_cpu_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"id": "center.py"}], [{"source": "a.py", "target": "b.py", "kind": "import"}])

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    node_rows = [object()]
    edge_set = {("a.py", "b.py", "import")}
    nodes_set = {"a.py", "b.py"}
    result = await project_service._build_local_graph_payload_async(node_rows, edge_set, nodes_set)

    assert result == ([{"id": "center.py"}], [{"source": "a.py", "target": "b.py", "kind": "import"}])
    assert calls["func"] is project_service._build_local_graph_payload
    assert calls["args"] == (node_rows, edge_set, nodes_set)
    assert calls["kwargs"] == {"operation": "project.build_local_graph"}


@pytest.mark.anyio
async def test_prepare_project_from_snapshot_uses_async_snapshot_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    async def _fake_prepare_project_snapshot_root_async(meta):
        calls.append(meta)
        return Path("/tmp/repo")

    monkeypatch.setattr(
        project_service,
        "prepare_project_snapshot_root_async",
        _fake_prepare_project_snapshot_root_async,
    )

    meta = object()
    result = await project_service.prepare_project_snapshot_root_async(meta)

    assert result == Path("/tmp/repo")
    assert calls == [meta]


@pytest.mark.anyio
async def test_delete_snapshot_related_async_helpers_use_async_snapshot_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_delete_project_snapshot_root_async(path):
        calls.append(f"project:{path}")

    async def _fake_delete_snapshot_async(meta):
        calls.append(f"snapshot:{meta}")

    monkeypatch.setattr(
        project_service,
        "delete_project_snapshot_root_async",
        _fake_delete_project_snapshot_root_async,
    )
    monkeypatch.setattr(project_service, "delete_snapshot_async", _fake_delete_snapshot_async)

    await project_service.delete_project_snapshot_root_async("/tmp/repo")
    await project_service._delete_patch_blob_for_sha_async("sha")
    await project_service.delete_snapshot_async("meta")

    assert calls == ["project:/tmp/repo", "snapshot:meta"]


@pytest.mark.anyio
async def test_delete_patch_blobs_async_collects_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_delete_patch_blob_for_sha_async(sha: str) -> None:
        if sha == "bad":
            raise RuntimeError("boom")

    monkeypatch.setattr(
        project_service,
        "_delete_patch_blob_for_sha_async",
        _fake_delete_patch_blob_for_sha_async,
    )

    errors = await project_service._delete_patch_blobs_async({"ok", "bad"}, max_parallel=2)

    assert len(errors) == 1
    assert errors[0][0] == "bad"
    assert isinstance(errors[0][1], RuntimeError)


@pytest.mark.anyio
async def test_delete_snapshots_async_collects_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Snap:
        def __init__(self, content_sha256: str):
            self.content_sha256 = content_sha256
            self.archive_name = "repo.zip"

    async def _fake_delete_snapshot_async(meta) -> None:
        if getattr(meta, "sha256", "") == "bad":
            raise RuntimeError("boom")

    monkeypatch.setattr(project_service, "delete_snapshot_async", _fake_delete_snapshot_async)

    payload_ok = {
        "storage": "local",
        "sha256": "ok",
        "archive_name": "repo.zip",
        "archive_ext": ".zip",
        "size": 1,
        "file": "f",
        "root_dir": "r",
    }
    payload_bad = dict(payload_ok)
    payload_bad["sha256"] = "bad"

    errors = await project_service._delete_snapshots_async(
        [("ok", "repo.zip", payload_ok), ("bad", "repo.zip", payload_bad)],
        max_parallel=2,
    )

    assert len(errors) == 1
    assert errors[0][0] == "bad"
    assert errors[0][2]["sha256"] == "bad"
    assert isinstance(errors[0][3], RuntimeError)


@pytest.mark.anyio
async def test_build_project_files_payload_async_uses_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"path": "a.py"}], True, "a.py")

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    rows = [object()]
    result = await project_service._build_project_files_payload_async(rows, limit=100)

    assert result == ([{"path": "a.py"}], True, "a.py")
    assert calls["func"] is project_service._build_project_files_payload
    assert calls["args"] == (rows,)
    assert calls["kwargs"] == {"limit": 100, "operation": "project.build_project_files"}


@pytest.mark.anyio
async def test_build_project_tree_payload_async_uses_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"type": "dir", "path": "src", "name": "src", "has_children": True}], "src", True)

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    rows = [object()]
    result = await project_service._build_project_tree_payload_async(
        rows,
        prefix_norm=None,
        limit=200,
        scan_limit=400,
        has_more_rows=True,
    )

    assert result == ([{"type": "dir", "path": "src", "name": "src", "has_children": True}], "src", True)
    assert calls["func"] is project_service._build_project_tree_payload
    assert calls["args"] == (rows,)
    assert calls["kwargs"] == {
        "prefix_norm": None,
        "limit": 200,
        "scan_limit": 400,
        "has_more_rows": True,
        "operation": "project.build_project_tree",
    }


@pytest.mark.anyio
async def test_extract_patch_blob_shas_async_uses_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"sha1"}

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    runs = [object()]
    result = await project_service._extract_patch_blob_shas_async(runs)

    assert result == {"sha1"}
    assert calls["func"] is project_service._extract_patch_blob_shas
    assert calls["args"] == (runs,)
    assert calls["kwargs"] == {"operation": "project.extract_patch_blob_shas"}


@pytest.mark.anyio
async def test_parse_snapshot_storage_payloads_async_uses_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return [("sha", "snap", {"storage": "local"})]

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    snapshots = [object()]
    result = await project_service._parse_snapshot_storage_payloads_async(snapshots)

    assert result == [("sha", "snap", {"storage": "local"})]
    assert calls["func"] is project_service._parse_snapshot_storage_payloads
    assert calls["args"] == (snapshots,)
    assert calls["kwargs"] == {"operation": "project.parse_snapshot_payloads"}


@pytest.mark.anyio
async def test_load_snapshot_ref_counts_async_groups_counts() -> None:
    class _Result:
        def all(self):
            return [("sha-a", 2), ("sha-b", 1)]

    class _Session:
        async def execute(self, _query):
            return _Result()

    result = await project_service._load_snapshot_ref_counts_async(
        _Session(),
        project_id=10,
        content_shas={"sha-a", "sha-b", ""},
    )

    assert result == {"sha-a": 2, "sha-b": 1}


@pytest.mark.anyio
async def test_load_snapshot_ref_counts_async_empty_input() -> None:
    class _Session:
        async def execute(self, _query):
            raise AssertionError("execute must not be called")

    result = await project_service._load_snapshot_ref_counts_async(
        _Session(),
        project_id=10,
        content_shas=set(),
    )

    assert result == {}


@pytest.mark.anyio
async def test_get_active_scan_task_async_uses_async_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeJob:
        id = "scan-task-1"
        status = "running"

    class _FakeResult:
        def scalars(self):
            return self

        def first(self):
            return _FakeJob()

    class _FakeSession:
        async def execute(self, stmt):
            _ = stmt
            return _FakeResult()

    calls: list[tuple[int, int]] = []

    async def _fake_get_scan_idempotency_key_async(org_id: int, project_id: int) -> str:
        calls.append((org_id, project_id))
        return "scan-key"

    monkeypatch.setattr(
        project_service,
        "get_scan_idempotency_key_async",
        _fake_get_scan_idempotency_key_async,
    )

    task_id, status = await project_service._get_active_scan_task_async(
        _FakeSession(),
        project_id=42,
        org_id=7,
    )

    assert task_id == "scan-task-1"
    assert status == "running"
    assert calls == [(7, 42)]


@pytest.mark.anyio
async def test_collect_delete_artifacts_async_runs_both_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_extract_patch_blob_shas_async(runs):
        calls.append("shas")
        assert runs == ["{}"]
        return {"sha-a"}

    async def _fake_parse_snapshot_storage_payloads_async(snapshots):
        calls.append("snapshots")
        assert snapshots == [("sha-s", "repo.zip", "{}")]
        return [("sha-s", "repo.zip", {"storage": "local"})]

    monkeypatch.setattr(project_service, "_extract_patch_blob_shas_async", _fake_extract_patch_blob_shas_async)
    monkeypatch.setattr(
        project_service,
        "_parse_snapshot_storage_payloads_async",
        _fake_parse_snapshot_storage_payloads_async,
    )

    shas, parsed = await project_service._collect_delete_artifacts_async(["{}"], [("sha-s", "repo.zip", "{}")])

    assert shas == {"sha-a"}
    assert parsed == [("sha-s", "repo.zip", {"storage": "local"})]
    assert calls == ["shas", "snapshots"]


@pytest.mark.anyio
async def test_delete_project_artifacts_async_runs_both_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_delete_patch_blobs_async(shas: set[str]):
        calls.append("patch")
        assert shas == {"sha-a"}
        return [("sha-a", RuntimeError("patch"))]

    async def _fake_delete_snapshots_async(snapshot_payloads):
        calls.append("snapshot")
        assert snapshot_payloads == [("sha-s", "repo.zip", {"storage": "local"})]
        return [("sha-s", "repo.zip", {"storage": "local"}, RuntimeError("snapshot"))]

    monkeypatch.setattr(project_service, "_delete_patch_blobs_async", _fake_delete_patch_blobs_async)
    monkeypatch.setattr(project_service, "_delete_snapshots_async", _fake_delete_snapshots_async)

    patch_errors, snapshot_errors = await project_service._delete_project_artifacts_async(
        {"sha-a"},
        [("sha-s", "repo.zip", {"storage": "local"})],
    )

    assert len(patch_errors) == 1
    assert patch_errors[0][0] == "sha-a"
    assert len(snapshot_errors) == 1
    assert snapshot_errors[0][0] == "sha-s"
    assert calls == ["patch", "snapshot"]


@pytest.mark.anyio
async def test_cache_project_delete_failures_async_writes_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict]] = []

    async def _fake_cache_set_json_async(parts: list[str], payload: dict):
        calls.append((parts, payload))

    monkeypatch.setattr(project_service, "cache_set_json_async", _fake_cache_set_json_async)

    rows = [
        (["project_delete_failed", "patch", "sha-a"], {"project_id": 1, "error": "boom"}),
        (["project_delete_failed", "snapshot", "snap-a"], {"project_id": 1, "error": "oops"}),
    ]
    await project_service._cache_project_delete_failures_async(rows)

    assert calls == rows


@pytest.mark.anyio
async def test_resolve_project_paths_async_resolves_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _fake_resolve_under_root_async(root, rel_path, *, max_length):
        _ = root, max_length
        calls.append(rel_path)
        if rel_path == "bad":
            raise ValueError("bad")
        return Path(f"/repo/{rel_path}"), f"norm/{rel_path}"

    monkeypatch.setattr(project_service, "_resolve_under_root_async", _fake_resolve_under_root_async)

    result = await project_service._resolve_project_paths_async(
        Path("/repo"),
        ["a.py", "bad", "a.py", "b.py"],
        max_parallel=2,
    )

    assert result == {
        "a.py": (Path("/repo/a.py"), "norm/a.py"),
        "b.py": (Path("/repo/b.py"), "norm/b.py"),
    }
    assert calls == ["a.py", "bad", "a.py", "b.py"]


@pytest.mark.anyio
async def test_search_project_text_async_uses_pre_resolved_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Project:
        org_id = 7
        root_path = "/repo"

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class _Session:
        def __init__(self):
            self.calls = 0

        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            _ = stmt
            self.calls += 1
            if self.calls == 1:
                return _Result([(1,)])
            return _Result([])

    async def _fake_cache_get_json_async(parts):
        _ = parts
        return None

    captured: list[dict] = []

    async def _fake_cache_set_json_async(parts, payload):
        _ = parts
        captured.append(payload)

    async def _fake_search_text_paths_async(session, project_id, needle, limit, prefix):
        _ = session, project_id, needle, limit, prefix
        return ["a.py"]

    async def _fake_read_project_files_async(root, non_indexed_paths, max_chars):
        _ = root, max_chars
        assert non_indexed_paths == ["a.py"]
        return {"norm/a.py": "alpha needle beta"}

    async def _fake_resolve_project_paths_async(root, rel_paths, *, max_parallel=16):
        _ = root, max_parallel
        assert rel_paths == ["a.py"]
        return {"a.py": (Path("/repo/a.py"), "norm/a.py")}

    async def _fake_find_text_matches_in_payload_async(*args, **kwargs):
        _ = args, kwargs
        return ([{"line": 1, "col": 7, "snippet": "needle", "truncated_file": False}], True)

    monkeypatch.setattr(project_service, "normalize_project_root", lambda root_path, max_length: Path("/repo"))
    monkeypatch.setattr(project_service, "cache_get_json_async", _fake_cache_get_json_async)
    monkeypatch.setattr(project_service, "cache_set_json_async", _fake_cache_set_json_async)
    monkeypatch.setattr(project_service, "search_text_paths_async", _fake_search_text_paths_async)
    monkeypatch.setattr(project_service, "_read_project_files_async", _fake_read_project_files_async)
    monkeypatch.setattr(project_service, "_resolve_project_paths_async", _fake_resolve_project_paths_async)
    monkeypatch.setattr(project_service, "_find_text_matches_in_payload_async", _fake_find_text_matches_in_payload_async)

    def _forbidden_resolve_under_root(*args, **kwargs):
        raise AssertionError("sync resolve_under_root should not be used")

    monkeypatch.setattr(project_service, "resolve_under_root", _forbidden_resolve_under_root)

    result = await project_service.search_project_text_async(
        _Session(),
        project_id=42,
        org_id=7,
        query="needle",
    )

    assert result["matches"] == [
        {"path": "norm/a.py", "line": 1, "col": 7, "snippet": "needle", "truncated_file": False}
    ]
    assert captured and captured[0] == result




@pytest.mark.anyio
async def test_search_project_text_async_returns_cached_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    cached_payload = {"matches": [{"path": "a.py"}], "meta": {"query": "needle"}}

    async def _fake_cache_get_json_async(parts):
        _ = parts
        return cached_payload

    class _Project:
        org_id = 1

    class _Session:
        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            raise AssertionError("session.execute should not be called when cache hit")

    monkeypatch.setattr(project_service, "cache_get_json_async", _fake_cache_get_json_async)

    result = await project_service.search_project_text_async(
        _Session(),
        project_id=1,
        org_id=1,
        query="needle",
    )

    assert result is cached_payload


@pytest.mark.anyio
async def test_search_project_text_async_returns_not_indexed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Project:
        org_id = 5
        root_path = "/repo"

    class _Result:
        def first(self):
            return None

    class _Session:
        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            _ = stmt
            return _Result()

    captured: list[dict] = []

    async def _fake_cache_get_json_async(parts):
        _ = parts
        return None

    async def _fake_cache_set_json_async(parts, payload):
        _ = parts
        captured.append(payload)

    monkeypatch.setattr(project_service, "cache_get_json_async", _fake_cache_get_json_async)
    monkeypatch.setattr(project_service, "cache_set_json_async", _fake_cache_set_json_async)

    result = await project_service.search_project_text_async(
        _Session(),
        project_id=10,
        org_id=5,
        query="needle",
    )

    assert result["matches"] == []
    assert "Проект не проиндексирован" in result["meta"]["message"]
    assert captured == [result]


@pytest.mark.anyio
async def test_search_project_text_async_uses_file_node_fallback_when_fts_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Project:
        org_id = 7
        root_path = "/repo"

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class _Session:
        def __init__(self):
            self.calls = 0

        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            _ = stmt
            self.calls += 1
            if self.calls == 1:
                return _Result([(1,)])
            if self.calls == 2:
                return _Result([("a.py",)])
            return _Result([])

    async def _fake_cache_get_json_async(parts):
        _ = parts
        return None

    captured: list[dict] = []

    async def _fake_cache_set_json_async(parts, payload):
        _ = parts
        captured.append(payload)

    async def _fake_search_text_paths_async(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("fts unavailable")

    async def _fake_read_project_files_async(root, non_indexed_paths, max_chars):
        _ = root, max_chars
        assert non_indexed_paths == ["a.py"]
        return {"a.py": "needle"}

    async def _fake_resolve_project_paths_async(root, rel_paths, *, max_parallel=16):
        _ = root, max_parallel
        assert rel_paths == ["a.py"]
        return {"a.py": (Path("/repo/a.py"), "a.py")}

    async def _fake_find_text_matches_in_payload_async(*args, **kwargs):
        _ = args, kwargs
        return ([{"line": 1, "col": 1, "snippet": "needle", "truncated_file": False}], True)

    monkeypatch.setattr(project_service, "cache_get_json_async", _fake_cache_get_json_async)
    monkeypatch.setattr(project_service, "cache_set_json_async", _fake_cache_set_json_async)
    monkeypatch.setattr(project_service, "search_text_paths_async", _fake_search_text_paths_async)
    monkeypatch.setattr(project_service, "_read_project_files_async", _fake_read_project_files_async)
    monkeypatch.setattr(project_service, "_resolve_project_paths_async", _fake_resolve_project_paths_async)
    monkeypatch.setattr(project_service, "_find_text_matches_in_payload_async", _fake_find_text_matches_in_payload_async)
    monkeypatch.setattr(project_service, "normalize_project_root", lambda root_path, max_length: Path("/repo"))

    result = await project_service.search_project_text_async(
        _Session(),
        project_id=42,
        org_id=7,
        query="needle",
    )

    assert result["matches"] == [
        {"path": "a.py", "line": 1, "col": 1, "snippet": "needle", "truncated_file": False}
    ]
    assert captured and captured[0] == result


@pytest.mark.anyio
async def test_search_project_text_async_truncated_indexed_fallback_second_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Project:
        org_id = 7
        root_path = "/repo"

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class _Session:
        def __init__(self):
            self.calls = 0

        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            _ = stmt
            self.calls += 1
            if self.calls == 1:
                return _Result([(1,)])
            if self.calls == 2:
                return _Result([("a.py", "abc")])
            return _Result([])

    async def _fake_cache_get_json_async(parts):
        _ = parts
        return None

    async def _fake_cache_set_json_async(parts, payload):
        _ = parts, payload

    async def _fake_search_text_paths_async(*args, **kwargs):
        _ = args, kwargs
        return ["a.py"]

    async def _fake_read_project_files_async(root, non_indexed_paths, max_chars):
        _ = root, non_indexed_paths, max_chars
        return {}

    async def _fake_resolve_project_paths_async(root, rel_paths, *, max_parallel=16):
        _ = root, max_parallel
        return {"a.py": (Path("/repo/a.py"), "a.py")}

    calls: list[str] = []

    async def _fake_find_text_matches_in_payload_async(payload, **kwargs):
        _ = kwargs
        calls.append(payload)
        if len(calls) == 1:
            return ([], False)
        return ([{"line": 1, "col": 1, "snippet": "x", "truncated_file": True}], True)

    monkeypatch.setattr(project_service, "cache_get_json_async", _fake_cache_get_json_async)
    monkeypatch.setattr(project_service, "cache_set_json_async", _fake_cache_set_json_async)
    monkeypatch.setattr(project_service, "search_text_paths_async", _fake_search_text_paths_async)
    monkeypatch.setattr(project_service, "_read_project_files_async", _fake_read_project_files_async)
    monkeypatch.setattr(project_service, "_resolve_project_paths_async", _fake_resolve_project_paths_async)
    monkeypatch.setattr(project_service, "_find_text_matches_in_payload_async", _fake_find_text_matches_in_payload_async)
    monkeypatch.setattr(project_service, "normalize_project_root", lambda root_path, max_length: Path("/repo"))
    monkeypatch.setattr(project_service.settings, "llm_agentic_max_file_chars", 1)

    result = await project_service.search_project_text_async(
        _Session(),
        project_id=42,
        org_id=7,
        query="needle",
    )

    assert len(calls) == 2
    assert result["matches"][0]["truncated_file"] is True


@pytest.mark.anyio
async def test_search_project_text_async_limit_matches_stops_after_first_batch_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Project:
        org_id = 7
        root_path = "/repo"

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class _Session:
        def __init__(self):
            self.calls = 0

        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            _ = stmt
            self.calls += 1
            if self.calls == 1:
                return _Result([(1,)])
            return _Result([])

    async def _fake_cache_get_json_async(parts):
        _ = parts
        return None

    async def _fake_cache_set_json_async(parts, payload):
        _ = parts, payload

    async def _fake_search_text_paths_async(*args, **kwargs):
        _ = args, kwargs
        return ["a.py", "b.py"]

    async def _fake_read_project_files_async(root, non_indexed_paths, max_chars):
        _ = root, max_chars
        return {"a.py": "needle", "b.py": "needle"}

    async def _fake_resolve_project_paths_async(root, rel_paths, *, max_parallel=16):
        _ = root, max_parallel
        return {rel: (Path(f"/repo/{rel}"), rel) for rel in rel_paths}

    async def _fake_find_text_matches_in_payload_async(payload, **kwargs):
        _ = payload, kwargs
        return ([{"line": 1, "col": 1, "snippet": "needle", "truncated_file": False}], True)

    monkeypatch.setattr(project_service, "cache_get_json_async", _fake_cache_get_json_async)
    monkeypatch.setattr(project_service, "cache_set_json_async", _fake_cache_set_json_async)
    monkeypatch.setattr(project_service, "search_text_paths_async", _fake_search_text_paths_async)
    monkeypatch.setattr(project_service, "_read_project_files_async", _fake_read_project_files_async)
    monkeypatch.setattr(project_service, "_resolve_project_paths_async", _fake_resolve_project_paths_async)
    monkeypatch.setattr(project_service, "_find_text_matches_in_payload_async", _fake_find_text_matches_in_payload_async)
    monkeypatch.setattr(project_service, "normalize_project_root", lambda root_path, max_length: Path("/repo"))

    result = await project_service.search_project_text_async(
        _Session(),
        project_id=42,
        org_id=7,
        query="needle",
        limit_matches=1,
    )

    assert len(result["matches"]) == 1
    assert result["meta"]["matched_files"] == 1

@pytest.mark.anyio
async def test_get_file_dependencies_async_uses_async_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Project:
        org_id = 7
        root_path = "/repo"

    class _CountResult:
        def __init__(self, value):
            self._value = value

        def one(self):
            return self._value

    class _RowsResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return list(self._rows)

    class _Session:
        def __init__(self):
            self.calls = 0

        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            _ = stmt
            self.calls += 1
            if self.calls <= 2:
                return _CountResult((0,))
            return _RowsResult([])

    monkeypatch.setattr(project_service, "normalize_project_root", lambda root_path, max_length: Path("/repo"))

    async def _fake_resolve_under_root_async(root, rel_path, *, max_length):
        _ = root, rel_path, max_length
        return Path("/repo/a.py"), "a.py"

    monkeypatch.setattr(project_service, "_resolve_under_root_async", _fake_resolve_under_root_async)

    def _forbidden_resolve_under_root(*args, **kwargs):
        raise AssertionError("sync resolve_under_root should not be used")

    monkeypatch.setattr(project_service, "resolve_under_root", _forbidden_resolve_under_root)

    result = await project_service.get_file_dependencies_async(
        _Session(),
        project_id=42,
        org_id=7,
        path="a.py",
    )

    assert result["path"] == "a.py"
    assert result["meta"]["total_inbound"] == 0
    assert result["meta"]["total_outbound"] == 0


@pytest.mark.anyio
async def test_load_local_graph_async_uses_async_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Project:
        org_id = 7
        root_path = "/repo"

    class _Result:
        def scalars(self):
            return self

        def first(self):
            return None

    class _Session:
        async def get(self, model, pk):
            _ = model, pk
            return _Project()

        async def execute(self, stmt):
            _ = stmt
            return _Result()

    monkeypatch.setattr(project_service, "normalize_project_root", lambda root_path, max_length: Path("/repo"))

    async def _fake_resolve_under_root_async(root, rel_path, *, max_length):
        _ = root, rel_path, max_length
        return Path("/repo/a.py"), "a.py"

    monkeypatch.setattr(project_service, "_resolve_under_root_async", _fake_resolve_under_root_async)

    def _forbidden_resolve_under_root(*args, **kwargs):
        raise AssertionError("sync resolve_under_root should not be used")

    monkeypatch.setattr(project_service, "resolve_under_root", _forbidden_resolve_under_root)

    result = await project_service.load_local_graph_async(
        _Session(),
        project_id=42,
        org_id=7,
        path="a.py",
        hops=1,
        max_nodes=10,
        max_edges=10,
    )

    assert result == {"nodes": [], "edges": [], "meta": {"center": "a.py", "found": False}}


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_fs_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(project_service, "run_fs_io_async", _fake_cpu_runtime)

    result = await project_service._normalize_project_root_async("/repo")

    assert result == Path("/repo")
    assert calls["func"] is project_service.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {"max_length": project_service.settings.max_root_path_chars, "operation": "project.normalize_root", "lane": "interactive"}


@pytest.mark.anyio
async def test_create_project_async_uses_async_root_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original_allow = project_service.settings.allow_local_root_path
    project_service.settings.allow_local_root_path = True

    class _Project:
        id = 1

    class _Session:
        def add(self, project):
            assert project.name == "demo"
            calls.append("add")

        async def commit(self):
            calls.append("commit")

        async def refresh(self, project):
            assert project is not None
            calls.append("refresh")

    async def _fake_normalize_project_root_async(root_path: str):
        calls.append(f"normalize:{root_path}")
        return Path("/repo")

    monkeypatch.setattr(
        project_service,
        "_normalize_project_root_async",
        _fake_normalize_project_root_async,
    )

    try:
        project = await project_service.create_project_async(
            _Session(),
            name="demo",
            root_path="/repo",
            org_id=7,
        )
    finally:
        project_service.settings.allow_local_root_path = original_allow

    assert getattr(project, "root_path", "") == "/repo"
    assert calls == ["normalize:/repo", "add", "commit", "refresh"]


@pytest.mark.anyio
async def test_create_project_from_snapshot_async_uses_async_root_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Session:
        def __init__(self):
            self.added = []

        def add(self, value):
            self.added.append(value)
            calls.append(type(value).__name__)

        async def flush(self):
            for value in self.added:
                if getattr(value, "id", None) is None and type(value).__name__ == "Project":
                    value.id = 42
            calls.append("flush")

        async def refresh(self, project):
            assert getattr(project, "id", None) == 42
            calls.append("refresh")

        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def begin(self):
            calls.append("begin")
            return self._Tx()

    async def _fake_prepare_project_snapshot_root_async(meta):
        _ = meta
        calls.append("prepare")
        return Path("/tmp/snap")

    async def _fake_normalize_project_root_async(root_path: str):
        calls.append(f"normalize:{root_path}")
        return Path("/repo")

    monkeypatch.setattr(
        project_service,
        "prepare_project_snapshot_root_async",
        _fake_prepare_project_snapshot_root_async,
    )
    monkeypatch.setattr(
        project_service,
        "_normalize_project_root_async",
        _fake_normalize_project_root_async,
    )

    meta = project_service.SnapshotMeta(
        storage="local",
        sha256="sha",
        archive_name="repo.zip",
        archive_ext=".zip",
        size=1,
        file="snapshots/sha/archive.zip",
        root_dir="snapshots/sha/repo",
    )

    project = await project_service.create_project_from_snapshot_async(
        _Session(),
        name="demo",
        meta=meta,
        org_id=7,
    )

    assert project.id == 42
    assert calls[:3] == ["prepare", "normalize:/tmp/snap", "begin"]


from app import graph


@pytest.mark.anyio
async def test_scan_and_update_graph_async_does_not_call_sync_graph_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Project:
        org_id = 7
        root_path = "/repo"

    class _SessionGet:
        async def get(self, model, project_id):
            _ = model, project_id
            return _Project()

    class _SessionMetrics:
        pass

    class _SessionCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    sessions = [_SessionGet(), _SessionMetrics()]

    def _fake_async_session_local():
        return _SessionCtx(sessions.pop(0))

    class _Lock:
        async def __aenter__(self):
            calls.append("lock-enter")
            return None

        async def __aexit__(self, exc_type, exc, tb):
            calls.append("lock-exit")
            return False

    async def _fake_cpu_runtime(func, *args, **kwargs):
        if getattr(func, "__name__", "") == "compute_graph_metrics_with_threshold":
            raise AssertionError("sync graph metrics path must not be used")
        return func(*args, **kwargs)

    async def _fake_scan_project_async(project_id: int, org_id: int, root: Path):
        assert project_id == 1
        assert org_id == 7
        assert root == Path("/repo")
        calls.append("scan")
        return {"files": 1}

    async def _fake_compute_graph_metrics_async(session, project_id, background_tasks=None):
        _ = background_tasks
        assert isinstance(session, _SessionMetrics)
        assert project_id == 1
        calls.append("metrics-async")
        return False

    async def _fake_cache_invalidate_prefix_async(parts):
        calls.append(f"cache:{parts[0]}")

    monkeypatch.setattr(project_service, "AsyncSessionLocal", _fake_async_session_local)
    monkeypatch.setattr(project_service, "project_lock_async", lambda *_args, **_kwargs: _Lock())
    async def _fake_normalize_project_root_async(_path: str):
        return Path("/repo")

    monkeypatch.setattr(project_service, "_normalize_project_root_async", _fake_normalize_project_root_async)
    monkeypatch.setattr(project_service, "scan_project_async", _fake_scan_project_async)
    monkeypatch.setattr(project_service, "compute_graph_metrics_async", _fake_compute_graph_metrics_async)
    monkeypatch.setattr(project_service, "cache_invalidate_prefix_async", _fake_cache_invalidate_prefix_async)

    result = await project_service._scan_and_update_graph_async(1, 7)

    assert result == {"ok": True, "stats": {"files": 1}, "metrics_pending": False}
    assert calls == ["scan", "lock-enter", "metrics-async", "lock-exit", "cache:project:1"]


@pytest.mark.anyio
async def test_scan_and_update_graph_async_does_not_touch_sync_get_session(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Project:
        org_id = 7
        root_path = "/repo"

    class _SessionGet:
        async def get(self, model, project_id):
            _ = model, project_id
            return _Project()

    class _SessionMetrics:
        pass

    class _SessionCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    sessions = [_SessionGet(), _SessionMetrics()]

    def _fake_async_session_local():
        return _SessionCtx(sessions.pop(0))

    class _Lock:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _fake_scan_project_async(_project_id: int, _org_id: int, _root: Path):
        return {"files": 1}

    async def _fake_compute_graph_metrics_async(_session, _project_id, background_tasks=None):
        _ = background_tasks
        return False

    def _fail_get_session(*_args, **_kwargs):
        raise AssertionError("sync get_session must not be called in async runtime path")

    monkeypatch.setattr(project_service, "AsyncSessionLocal", _fake_async_session_local)
    monkeypatch.setattr(project_service, "project_lock_async", lambda *_args, **_kwargs: _Lock())
    async def _fake_normalize_project_root_async(_path: str):
        return Path("/repo")

    async def _fake_cache_invalidate_prefix_async(_parts):
        return None

    monkeypatch.setattr(project_service, "_normalize_project_root_async", _fake_normalize_project_root_async)
    monkeypatch.setattr(project_service, "scan_project_async", _fake_scan_project_async)
    monkeypatch.setattr(project_service, "compute_graph_metrics_async", _fake_compute_graph_metrics_async)
    monkeypatch.setattr(project_service, "cache_invalidate_prefix_async", _fake_cache_invalidate_prefix_async)
    monkeypatch.setattr(graph, "get_session", _fail_get_session, raising=False)

    result = await project_service._scan_and_update_graph_async(1, 7)

    assert result["ok"] is True


@pytest.mark.anyio
async def test_compute_graph_metrics_async_runs_cpu_in_executor_and_keeps_db_async(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _ScalarResult:
        def __init__(self, value):
            self._value = value

        def scalar_one(self):
            return self._value

    class _RowsResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        def __init__(self):
            self._execute_idx = 0

        async def execute(self, stmt, params=None):
            _ = stmt
            if params is not None:
                calls.append("write")
                return _RowsResult([])
            self._execute_idx += 1
            if self._execute_idx == 1:
                return _ScalarResult(2)
            if self._execute_idx == 2:
                return _ScalarResult(1)
            if self._execute_idx == 3:
                return _RowsResult([(1, "a.py"), (2, "b.py")])
            if self._execute_idx == 4:
                return _RowsResult([("a.py", 1)])
            if self._execute_idx == 5:
                return _RowsResult([("a.py", 1)])
            if self._execute_idx == 6:
                return _RowsResult([("a.py", "b.py")])
            raise AssertionError("unexpected execute call")

        async def commit(self):
            calls.append("commit")

        async def get(self, model, ident):
            _ = (model, ident)

            class _Project:
                pass

            return _Project()

        def add(self, obj):
            _ = obj

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls.append(f"cpu:{func.__name__}")
        kwargs.pop("operation", None)
        return func(*args, **kwargs)

    monkeypatch.setattr(graph, "run_cpu_io_async", _fake_cpu_runtime)

    pending = await graph.compute_graph_metrics_async(_Session(), project_id=1)

    assert pending is False
    assert calls == ["cpu:_compute_graph_metrics_cpu", "write", "commit"]


@pytest.mark.anyio
async def test_cpu_runtime_receives_pickle_safe_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        captured["args"] = args
        return ([{"id": "src/a.py"}], ["src/a.py"])

    monkeypatch.setattr(project_service, "run_cpu_io_async", _fake_cpu_runtime)

    class _Node:
        path = "src/a.py"
        language = "py"
        loc = 10
        complexity = 2
        fan_in = 1
        fan_out = 3
        scc_id = 7
        status = "ok"

    await project_service._build_graph_node_payload_async(project_service._normalize_file_node_rows([_Node()]))

    assert isinstance(captured["args"][0][0], dict)
    assert captured["args"][0][0]["path"] == "src/a.py"


@pytest.mark.anyio
async def test_project_service_cpu_pipeline_does_not_increase_fs_queue_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    orig_fs_workers = settings.fs_runtime_interactive_max_workers
    orig_fs_concurrency = settings.fs_runtime_interactive_max_concurrency
    orig_cpu_workers = settings.cpu_runtime_max_workers
    orig_cpu_concurrency = settings.cpu_runtime_max_concurrency

    settings.fs_runtime_interactive_max_workers = 1
    settings.fs_runtime_interactive_max_concurrency = 1
    settings.cpu_runtime_max_workers = 2
    settings.cpu_runtime_max_concurrency = 4

    await fs_runtime.close_fs_runtime()
    await cpu_runtime.close_cpu_runtime()
    await fs_runtime.init_fs_runtime()
    await cpu_runtime.init_cpu_runtime()

    rows = [("a.py", 0, "[0.1, 0.2]", "sym", 1, 1)]
    try:
        fs_tasks = 4
        cpu_tasks = 16
        await asyncio.gather(
            *[
                project_service._score_semantic_rows_async(
                    rows,
                    query_embedding=[0.1, 0.2],
                    file_cache={"a.py": "line1\nline2"},
                    chunk_size=100,
                    step=80,
                )
                for _ in range(cpu_tasks)
            ],
            *[
                fs_runtime.run_fs_io_async(time.sleep, 0.03, operation="test.fs_load", lane="interactive")
                for _ in range(fs_tasks)
            ],
        )
        runtime = fs_runtime._fs_runtime
        assert runtime is not None
        assert runtime.interactive.peak_queue_depth <= fs_tasks
    finally:
        await fs_runtime.close_fs_runtime()
        await cpu_runtime.close_cpu_runtime()
        settings.fs_runtime_interactive_max_workers = orig_fs_workers
        settings.fs_runtime_interactive_max_concurrency = orig_fs_concurrency
        settings.cpu_runtime_max_workers = orig_cpu_workers
        settings.cpu_runtime_max_concurrency = orig_cpu_concurrency


def test_semantic_scoring_and_payload_builders_regression() -> None:
    compared, scored = project_service._score_semantic_rows(
        [("src/a.py", 0, "[1.0, 0.0]", "", 0, 0)],
        query_embedding=[1.0, 0.0],
        file_cache={"src/a.py": "abcdef"},
        chunk_size=4,
        step=2,
    )
    assert compared == 1
    assert scored[0]["score"] == 1.0
    assert scored[0]["snippet"] == "abcd"

    rows = [
        {"path": "src/a.py", "language": "py", "loc": 10, "complexity": 2, "fan_in": 3, "fan_out": 4, "status": "ok"},
        {"path": "src/b.py", "language": "py", "loc": 5, "complexity": 1, "fan_in": 0, "fan_out": 1, "status": "ok"},
    ]
    files, truncated, next_cursor = project_service._build_project_files_payload(rows, limit=1)
    assert files[0]["path"] == "src/a.py"
    assert truncated is True
    assert next_cursor == "src/a.py"
