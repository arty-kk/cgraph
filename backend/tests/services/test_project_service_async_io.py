import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import project_service


@pytest.mark.anyio
async def test_read_text_if_file_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        called["func"] = func
        called["args"] = args
        called["kwargs"] = kwargs
        return "payload"

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    result = await project_service._read_text_if_file_async(Path("/tmp/test.txt"), 123)

    assert result == "payload"
    assert called["func"] is project_service._read_text_if_file
    assert called["args"] == (Path("/tmp/test.txt"), 123)
    assert called["kwargs"] == {}


@pytest.mark.anyio
async def test_resolve_under_root_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        called["func"] = func
        called["args"] = args
        called["kwargs"] = kwargs
        return (Path("/repo/a.py"), "a.py")

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    result = await project_service._resolve_under_root_async(
        Path("/repo"),
        "a.py",
        max_length=120,
    )

    assert result == (Path("/repo/a.py"), "a.py")
    assert called["func"] is project_service.resolve_under_root
    assert called["args"] == (Path("/repo"), "a.py")
    assert called["kwargs"] == {"max_length": 120}


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
async def test_resolve_and_read_text_under_root_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ("a.py", "payload")

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

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
    }


@pytest.mark.anyio
async def test_score_semantic_rows_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return 1, [{"path": "a.py", "score": 1.0}]

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

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
    }


@pytest.mark.anyio
async def test_find_text_matches_in_payload_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"line": 1, "col": 1, "snippet": "abc", "truncated_file": False}], True)

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

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
    }


@pytest.mark.anyio
async def test_build_graph_node_payload_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"id": "a.py"}], ["a.py"])

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    node_row = object()
    result = await project_service._build_graph_node_payload_async([node_row])

    assert result == ([{"id": "a.py"}], ["a.py"])
    assert calls["func"] is project_service._build_graph_node_payload
    assert calls["args"] == ([node_row],)
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_build_graph_edge_payload_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return [{"source": "a.py", "target": "b.py", "kind": "import"}]

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    edge_row = object()
    result = await project_service._build_graph_edge_payload_async(
        [edge_row],
        effective_limit=10,
        node_set={"a.py", "b.py"},
    )

    assert result == [{"source": "a.py", "target": "b.py", "kind": "import"}]
    assert calls["func"] is project_service._build_graph_edge_payload
    assert calls["args"] == ([edge_row],)
    assert calls["kwargs"] == {"effective_limit": 10, "node_set": {"a.py", "b.py"}}


@pytest.mark.anyio
async def test_build_local_graph_payload_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"id": "center.py"}], [{"source": "a.py", "target": "b.py", "kind": "import"}])

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    node_rows = [object()]
    edge_set = {("a.py", "b.py", "import")}
    nodes_set = {"a.py", "b.py"}
    result = await project_service._build_local_graph_payload_async(node_rows, edge_set, nodes_set)

    assert result == ([{"id": "center.py"}], [{"source": "a.py", "target": "b.py", "kind": "import"}])
    assert calls["func"] is project_service._build_local_graph_payload
    assert calls["args"] == (node_rows, edge_set, nodes_set)
    assert calls["kwargs"] == {}


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
        [(_Snap("ok"), payload_ok), (_Snap("bad"), payload_bad)],
        max_parallel=2,
    )

    assert len(errors) == 1
    assert errors[0][0].content_sha256 == "bad"
    assert errors[0][1]["sha256"] == "bad"
    assert isinstance(errors[0][2], RuntimeError)


@pytest.mark.anyio
async def test_build_project_files_payload_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"path": "a.py"}], True, "a.py")

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    rows = [object()]
    result = await project_service._build_project_files_payload_async(rows, limit=100)

    assert result == ([{"path": "a.py"}], True, "a.py")
    assert calls["func"] is project_service._build_project_files_payload
    assert calls["args"] == (rows,)
    assert calls["kwargs"] == {"limit": 100}


@pytest.mark.anyio
async def test_build_project_tree_payload_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ([{"type": "dir", "path": "src", "name": "src", "has_children": True}], "src", True)

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

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
    }


@pytest.mark.anyio
async def test_extract_patch_blob_shas_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"sha1"}

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    runs = [object()]
    result = await project_service._extract_patch_blob_shas_async(runs)

    assert result == {"sha1"}
    assert calls["func"] is project_service._extract_patch_blob_shas
    assert calls["args"] == (runs,)
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_parse_snapshot_storage_payloads_async_uses_to_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return [("snap", {"storage": "local"})]

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    snapshots = [object()]
    result = await project_service._parse_snapshot_storage_payloads_async(snapshots)

    assert result == [("snap", {"storage": "local"})]
    assert calls["func"] is project_service._parse_snapshot_storage_payloads
    assert calls["args"] == (snapshots,)
    assert calls["kwargs"] == {}


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
        assert runs == ["run-1"]
        return {"sha-a"}

    async def _fake_parse_snapshot_storage_payloads_async(snapshots):
        calls.append("snapshots")
        assert snapshots == ["snap-1"]
        return [("snap-1", {"storage": "local"})]

    monkeypatch.setattr(project_service, "_extract_patch_blob_shas_async", _fake_extract_patch_blob_shas_async)
    monkeypatch.setattr(
        project_service,
        "_parse_snapshot_storage_payloads_async",
        _fake_parse_snapshot_storage_payloads_async,
    )

    shas, parsed = await project_service._collect_delete_artifacts_async(["run-1"], ["snap-1"])

    assert shas == {"sha-a"}
    assert parsed == [("snap-1", {"storage": "local"})]
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
        assert snapshot_payloads == [("snap-1", {"storage": "local"})]
        return [("snap-1", {"storage": "local"}, RuntimeError("snapshot"))]

    monkeypatch.setattr(project_service, "_delete_patch_blobs_async", _fake_delete_patch_blobs_async)
    monkeypatch.setattr(project_service, "_delete_snapshots_async", _fake_delete_snapshots_async)

    patch_errors, snapshot_errors = await project_service._delete_project_artifacts_async(
        {"sha-a"},
        [("snap-1", {"storage": "local"})],
    )

    assert len(patch_errors) == 1
    assert patch_errors[0][0] == "sha-a"
    assert len(snapshot_errors) == 1
    assert snapshot_errors[0][0] == "snap-1"
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
async def test_normalize_project_root_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(project_service.asyncio, "to_thread", _fake_to_thread)

    result = await project_service._normalize_project_root_async("/repo")

    assert result == Path("/repo")
    assert calls["func"] is project_service.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {"max_length": project_service.settings.max_root_path_chars}


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
