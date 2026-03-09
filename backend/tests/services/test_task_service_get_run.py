import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import task_service


class _FakeAsyncSession:
    def __init__(self, run):
        self._run = run
        self.deleted = []
        self.committed = False

    async def get(self, model, run_id):
        return self._run

    async def delete(self, row):
        self.deleted.append(row)

    async def commit(self):
        self.committed = True


@pytest.mark.anyio
async def test_get_run_does_not_start_scan_from_read_path(monkeypatch):
    run = SimpleNamespace(
        id=101,
        project_id=77,
        org_id=55,
        target_path='backend/app/main.py',
        mode='analyze',
        prompt='check graph readiness',
        model_used='gpt-test',
        depth=1,
        dep_mode='contracts',
        retrieval='agentic',
        retrieval_settings_json=json.dumps({'agentic': {'max_calls': 4}}),
        apply_patch=False,
        applied_json='null',
        created_at=SimpleNamespace(isoformat=lambda: '2026-01-01T00:00:00Z'),
        result_json=json.dumps({'ok': True}),
    )

    async def _graph_warning_async(session, project_id: int):
        return task_service.GRAPH_NOT_READY_WARNING

    monkeypatch.setattr(task_service, '_graph_warning_async', _graph_warning_async)

    payload = await task_service.get_run_async(
        _FakeAsyncSession(run), project_id=77, org_id=55, run_id=101
    )

    assert payload['warning'] == task_service.GRAPH_NOT_READY_WARNING
    assert 'graph_scan_task_id' not in payload
    assert 'graph_scan_status' not in payload


@pytest.mark.anyio
async def test_get_run_patch_async_reads_blob_via_async_helper(monkeypatch):
    run = SimpleNamespace(
        id=101,
        project_id=77,
        org_id=55,
        result_json=json.dumps({"patch_unified_diff_meta": {"sha256": "sha"}}),
    )
    session = _FakeAsyncSession(run)

    calls: dict[str, object] = {}

    async def _fake_read_patch_blob_async(meta):
        calls["meta"] = meta
        return "diff --git a/a.py b/a.py\n"

    monkeypatch.setattr(task_service, "_read_patch_blob_async", _fake_read_patch_blob_async)
    async def _fake_get_patch_download_url_async(meta):
        _ = meta
        return None

    monkeypatch.setattr(
        task_service,
        "get_patch_download_url_async",
        _fake_get_patch_download_url_async,
    )

    payload = await task_service.get_run_patch_async(session, 77, 55, 101)

    assert payload == {"patch_unified_diff": "diff --git a/a.py b/a.py\n"}
    assert calls["meta"] == {"sha256": "sha"}


@pytest.mark.anyio
async def test_delete_run_async_deletes_blob_via_async_helper(monkeypatch):
    run = SimpleNamespace(
        id=101,
        project_id=77,
        org_id=55,
        result_json=json.dumps({"patch_unified_diff_meta": {"sha256": "sha-del"}}),
    )
    session = _FakeAsyncSession(run)

    calls: list[str] = []

    async def _fake_delete_patch_blob_for_sha_async(sha: str) -> None:
        calls.append(sha)

    async def _fake_load_patch_blob_ref_counts_async(_session, shas, *, exclude_run_id=None, exclude_project_id=None):
        assert _session is session
        assert shas == {"sha-del"}
        assert exclude_run_id == 101
        assert exclude_project_id is None
        return {"sha-del": 0}

    monkeypatch.setattr(
        task_service,
        "_delete_patch_blob_for_sha_async",
        _fake_delete_patch_blob_for_sha_async,
    )
    monkeypatch.setattr(
        task_service,
        "load_patch_blob_ref_counts_async",
        _fake_load_patch_blob_ref_counts_async,
    )

    result = await task_service.delete_run_async(session, 77, 55, 101)

    assert result == {"ok": True}
    assert calls == ["sha-del"]
    assert session.deleted == [run]
    assert session.committed is True


@pytest.mark.anyio
async def test_delete_run_async_keeps_shared_blob(monkeypatch):
    run = SimpleNamespace(
        id=102,
        project_id=77,
        org_id=55,
        result_json=json.dumps({"patch_unified_diff_meta": {"sha256": "sha-shared"}}),
    )
    session = _FakeAsyncSession(run)

    calls: list[str] = []

    async def _fake_delete_patch_blob_for_sha_async(sha: str) -> None:
        calls.append(sha)

    async def _fake_load_patch_blob_ref_counts_async(_session, shas, *, exclude_run_id=None, exclude_project_id=None):
        _ = (_session, shas, exclude_project_id)
        assert exclude_run_id == 102
        return {"sha-shared": 1}

    monkeypatch.setattr(
        task_service,
        "_delete_patch_blob_for_sha_async",
        _fake_delete_patch_blob_for_sha_async,
    )
    monkeypatch.setattr(
        task_service,
        "load_patch_blob_ref_counts_async",
        _fake_load_patch_blob_ref_counts_async,
    )

    result = await task_service.delete_run_async(session, 77, 55, 102)

    assert result == {"ok": True}
    assert calls == []
    assert session.deleted == [run]
    assert session.committed is True


@pytest.mark.anyio
async def test_json_loads_or_async_uses_run_cpu_io_async(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(task_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await task_service._json_loads_or_async('{"ok":true}', {})

    assert result == {"ok": True}
    assert calls["func"] is task_service._json_loads_or
    assert calls["args"] == ('{"ok":true}', {})
    assert calls["kwargs"] == {"operation": "task_service.json_loads_or"}


@pytest.mark.anyio
async def test_build_patch_payload_from_run_async_uses_blob_meta(monkeypatch):
    run = SimpleNamespace(
        result_json=json.dumps(
            {"patch_unified_diff_meta": {"sha256": "sha-1", "expires_at": "soon"}}
        )
    )

    async def _fake_json_loads_or_async(raw, fallback):
        return json.loads(raw)

    async def _fake_read_patch_blob_async(meta):
        return "diff --git a/a.py b/a.py\n"

    monkeypatch.setattr(task_service, "_json_loads_or_async", _fake_json_loads_or_async)
    monkeypatch.setattr(task_service, "_read_patch_blob_async", _fake_read_patch_blob_async)
    async def _fake_get_patch_download_url_async(meta):
        _ = meta
        return "https://example.test/diff"

    monkeypatch.setattr(
        task_service,
        "get_patch_download_url_async",
        _fake_get_patch_download_url_async,
    )

    payload = await task_service._build_patch_payload_from_run_async(run, run_id=101)

    assert payload["patch_unified_diff"].startswith("diff --git")
    assert payload["download_url"] == "https://example.test/diff"
    assert payload["expires_at"] == "soon"


@pytest.mark.anyio
async def test_apply_run_patch_async_does_not_call_get_run_patch_async(monkeypatch):
    project = SimpleNamespace(org_id=55, root_path=".")
    run = SimpleNamespace(
        id=101,
        project_id=77,
        org_id=55,
        allowed_patch_paths_json="[]",
    )

    class _Session:
        async def get(self, model, _id):
            if model.__name__ == "Project":
                return project
            return run

    async def _fake_build_patch_payload_from_run_async(_run, *, run_id):
        return {"patch_unified_diff": "diff --git a/a.py b/a.py\n"}

    async def _fake_apply_patch_and_record_async(*args, **kwargs):
        return {"modified": ["a.py"]}

    async def _fake_normalize_project_root_async(root_path: str, *, max_length: int):
        _ = max_length
        assert root_path == "."
        return Path("/normalized")

    async def _boom(*args, **kwargs):
        raise AssertionError("get_run_patch_async must not be called")

    monkeypatch.setattr(task_service, "get_run_patch_async", _boom)
    monkeypatch.setattr(
        task_service,
        "_build_patch_payload_from_run_async",
        _fake_build_patch_payload_from_run_async,
    )
    monkeypatch.setattr(
        task_service,
        "_apply_patch_and_record_async",
        _fake_apply_patch_and_record_async,
    )
    monkeypatch.setattr(
        task_service,
        "_normalize_project_root_async",
        _fake_normalize_project_root_async,
    )
    monkeypatch.setattr(
        task_service,
        "normalize_project_root",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sync normalize_project_root must not be used")
        ),
    )

    result = await task_service.apply_run_patch_async(_Session(), 77, 55, 101)

    assert result == {"applied": {"modified": ["a.py"]}}


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_run_fs_io_async(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_run_fs_io_async(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(task_service, "run_fs_io_async", _fake_run_fs_io_async)

    result = await task_service._normalize_project_root_async("/repo", max_length=111)

    assert result == Path("/repo")
    assert calls["func"] is task_service.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {
        "max_length": 111,
        "operation": "task_service.normalize_project_root",
        "lane": "interactive",
    }


@pytest.mark.anyio
async def test_get_run_async_parses_json_fields_via_async_helper(monkeypatch):
    run = SimpleNamespace(
        id=101,
        project_id=77,
        org_id=55,
        target_path='backend/app/main.py',
        mode='analyze',
        prompt='check graph readiness',
        model_used='gpt-test',
        depth=1,
        dep_mode='contracts',
        retrieval='agentic',
        retrieval_settings_json='{"a":2}',
        apply_patch=False,
        applied_json='{"b":3}',
        created_at=SimpleNamespace(isoformat=lambda: '2026-01-01T00:00:00Z'),
        result_json='{"c":1}',
    )

    calls: list[tuple[str | None, object]] = []

    async def _fake_json_loads_or_async(raw, fallback):
        calls.append((raw, fallback))
        if raw == '{"c":1}':
            return {"c": 1}
        if raw == '{"a":2}':
            return {"a": 2}
        if raw == '{"b":3}':
            return {"b": 3}
        return fallback

    async def _graph_warning_async(session, project_id: int):
        return None

    monkeypatch.setattr(task_service, '_json_loads_or_async', _fake_json_loads_or_async)
    monkeypatch.setattr(task_service, '_graph_warning_async', _graph_warning_async)

    payload = await task_service.get_run_async(_FakeAsyncSession(run), 77, 55, 101)

    assert payload['result'] == {'c': 1}
    assert payload['retrieval_settings'] == {'a': 2}
    assert payload['applied'] == {'b': 3}
    assert calls == [('{"c":1}', {}), ('{"a":2}', {}), ('{"b":3}', None)]
