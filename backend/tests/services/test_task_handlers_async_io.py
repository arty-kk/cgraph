import base64
import asyncio
import json
import sys
from datetime import timezone
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import task_handlers


@pytest.mark.anyio
async def test_normalize_project_root_async_uses_fs_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_fs_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/repo")

    monkeypatch.setattr(task_handlers, "run_fs_io_async", _fake_fs_runtime)

    result = await task_handlers._normalize_project_root_async("/repo")

    assert result == Path("/repo")
    assert calls["func"] is task_handlers.normalize_project_root
    assert calls["args"] == ("/repo",)
    assert calls["kwargs"] == {"operation": "task_handlers.normalize_root"}


@pytest.mark.anyio
async def test_consume_queued_task_payload_dispatches_by_task_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    async def _fake_scan(job_id: str, project_id: int, org_id: int) -> None:
        received["scan"] = (job_id, project_id, org_id)

    monkeypatch.setattr(task_handlers, "_scan_task_async", _fake_scan)
    monkeypatch.setattr(task_handlers, "_TASK_DISPATCH", {"stubgraph.scan": _fake_scan})

    body = json.dumps([["job-1", 11, 22], {}, None], ensure_ascii=False).encode("utf-8")
    payload = {
        "body": base64.b64encode(body).decode("ascii"),
        "headers": {"task": "stubgraph.scan"},
        "properties": {"body_encoding": "base64"},
    }

    await task_handlers.consume_queued_task_payload_async(json.dumps(payload, ensure_ascii=False))

    assert received["scan"] == ("job-1", 11, 22)


@pytest.mark.anyio
async def test_consume_queued_task_payload_uses_cpu_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    async def _fake_cpu_runtime(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return "stubgraph.scan", ["job-1", 11, 22]

    received: dict[str, object] = {}

    async def _fake_execute(task_name: str, args: list[object]) -> str:
        received["task_name"] = task_name
        received["args"] = args
        return "ok"

    monkeypatch.setattr(task_handlers, "run_cpu_io_async", _fake_cpu_runtime)
    monkeypatch.setattr(task_handlers, "execute_task_by_name_async", _fake_execute)

    result = await task_handlers.consume_queued_task_payload_async("{\"body\":\"[]\"}")

    assert result == "ok"
    assert calls["func"] is task_handlers._decode_task_payload
    assert calls["args"] == ('{"body":"[]"}',)
    assert calls["kwargs"] == {"operation": "task_handlers.decode_task_payload"}
    assert received == {"task_name": "stubgraph.scan", "args": ["job-1", 11, 22]}


def test_decode_task_payload_rejects_too_large_raw_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_handlers, "_task_payload_raw_max_bytes", lambda: 10)

    with pytest.raises(RuntimeError, match="Task payload exceeds raw size limit"):
        task_handlers._decode_task_payload("x" * 11)


def test_decode_task_payload_rejects_invalid_payload_format() -> None:
    with pytest.raises(RuntimeError, match="Task payload root must be object"):
        task_handlers._decode_task_payload("[1, 2, 3]")


def test_decode_task_payload_rejects_invalid_base64_body() -> None:
    payload = {
        "body": "***",
        "headers": {"task": "stubgraph.scan"},
        "properties": {"body_encoding": "base64"},
    }

    with pytest.raises(RuntimeError, match="Task payload body base64 is invalid"):
        task_handlers._decode_task_payload(json.dumps(payload, ensure_ascii=False))


def test_decode_task_payload_rejects_too_large_decoded_base64_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(task_handlers, "_task_payload_body_max_bytes", lambda: 2)
    payload = {
        "body": base64.b64encode(b"[1,2,3]").decode("ascii"),
        "headers": {"task": "stubgraph.scan"},
        "properties": {"body_encoding": "base64"},
    }

    with pytest.raises(RuntimeError, match="Task payload body exceeds decoded size limit"):
        task_handlers._decode_task_payload(json.dumps(payload, ensure_ascii=False))


@pytest.mark.anyio
async def test_scan_task_async_marks_failed_when_business_coroutine_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses: list[str] = []

    async def _fake_set_job_status_async(_session, _job_id: str, status: str, **_kwargs) -> None:
        statuses.append(status)

    async def _boom(_project_id: int, _org_id: int) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(task_handlers, "_set_job_status_async", _fake_set_job_status_async)
    monkeypatch.setattr(task_handlers, "_scan_and_update_graph_async", _boom)

    await task_handlers._scan_task_async("job", 1, 1)

    assert statuses == ["running", "failed"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("handler_name", "handler_args", "result_payload"),
    [
        ("_scan_task_async", ("job-scan", 11, 5), {"scan": True}),
        ("_docs_task_async", ("job-docs", 22, 5), {"docs": True}),
        ("_run_task_job_async", ("job-run", 33, 5, {"query": "q"}), {"run": True}),
        (
            "_mutation_indexing_task_async",
            ("job-mut", 44, 5, ["a.py"], "upsert"),
            {"mut": True},
        ),
    ],
)
async def test_target_handlers_use_single_session_per_run(
    monkeypatch: pytest.MonkeyPatch,
    handler_name: str,
    handler_args: tuple,
    result_payload: dict[str, object],
) -> None:
    status_calls: list[tuple[object, str]] = []
    session_ref = object()

    class _SessionCtx:
        async def __aenter__(self):
            return session_ref

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    async def _fake_set_job_status_async(session, _job_id: str, status: str, **_kwargs) -> None:
        status_calls.append((session, status))

    monkeypatch.setattr(task_handlers, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(task_handlers, "_set_job_status_async", _fake_set_job_status_async)

    async def _fake_scan(_project_id: int, _org_id: int) -> dict[str, object]:
        return result_payload

    async def _fake_docs(_project_id: int, _org_id: int) -> dict[str, object]:
        return result_payload

    async def _fake_run_task(_project_id: int, _org_id: int, _request) -> dict[str, object]:
        return result_payload

    async def _fake_mutation(*_args, **_kwargs) -> dict[str, object]:
        return dict(result_payload)

    async def _fake_root(_project_id: int, _org_id: int) -> Path:
        return Path("/repo")

    monkeypatch.setattr(task_handlers, "_scan_and_update_graph_async", _fake_scan)
    monkeypatch.setattr(task_handlers, "build_project_docs_async", _fake_docs)
    monkeypatch.setattr(task_handlers, "run_task_async", _fake_run_task)

    monkeypatch.setattr(task_handlers, "TaskRequest", lambda **_payload: object())
    monkeypatch.setattr(task_handlers, "run_mutation_indexing_async", _fake_mutation)
    monkeypatch.setattr(task_handlers, "_resolve_project_root_async", _fake_root)

    handler = getattr(task_handlers, handler_name)
    await handler(*handler_args)

    assert [status for _, status in status_calls] == ["running", "succeeded"]
    assert all(session is session_ref for session, _ in status_calls)


@pytest.mark.anyio
async def test_set_job_status_async_preserves_terminal_fields_contract() -> None:
    now_before = task_handlers.datetime.now(timezone.utc)
    job = type(
        "Job",
        (),
        {
            "id": "job-1",
            "org_id": 1,
            "status": "running",
            "queue": "heavy",
            "updated_at": None,
            "completed_at": None,
            "error": "keep-me",
            "result_json": '{"keep":true}',
        },
    )()

    class _Session:
        def __init__(self):
            self.commits = 0

        async def get(self, _model, _job_id):
            return job

        def add(self, _value):
            return None

        async def commit(self):
            self.commits += 1

    session = _Session()
    cleanup_calls: list[object] = []
    touch_calls: list[str] = []
    decrement_calls: list[str] = []

    async def _fake_cleanup(current_session) -> None:
        cleanup_calls.append(current_session)

    async def _fake_touch(job_id: str) -> None:
        touch_calls.append(job_id)

    async def _fake_decrement(job_id: str) -> None:
        decrement_calls.append(job_id)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(task_handlers, "cleanup_completed_jobs_async", _fake_cleanup)
    monkeypatch.setattr(task_handlers, "_touch_inflight_async", _fake_touch)
    monkeypatch.setattr(task_handlers, "_decrement_inflight_async", _fake_decrement)
    try:
        await task_handlers._set_job_status_async(session, "job-1", "succeeded")
    finally:
        monkeypatch.undo()

    assert session.commits == 1
    assert touch_calls == []
    assert decrement_calls == ["job-1"]
    assert cleanup_calls == [session]
    assert job.completed_at is not None
    assert job.completed_at >= now_before
    assert job.error == "keep-me"
    assert job.result_json == '{"keep":true}'


@pytest.mark.anyio
async def test_snapshot_import_task_async_tracks_lifecycle_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses: list[tuple[str, dict[str, object]]] = []
    staged_paths: list[str] = []

    async def _fake_set_job_status_async(_session, _job_id: str, status: str, **kwargs) -> None:
        statuses.append((status, kwargs))

    class _Project:
        id = 73
        name = "snapshot-project"

    class _SessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    async def _fake_store_snapshot_upload_from_path_async(path: str, archive_name: str):
        _ = path
        assert archive_name == "repo.zip"
        return type("Meta", (), {"archive_name": "repo.zip"})()

    async def _fake_create_project_from_snapshot_async(session, name: str, meta, org_id: int):
        _ = (session, meta)
        assert name == "snapshot-project"
        assert org_id == 12
        return _Project()

    async def _fake_delete_staged_snapshot_upload_async(path: str) -> None:
        staged_paths.append(path)

    monkeypatch.setattr(task_handlers, "_set_job_status_async", _fake_set_job_status_async)
    monkeypatch.setattr(task_handlers, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(
        task_handlers,
        "store_snapshot_upload_from_path_async",
        _fake_store_snapshot_upload_from_path_async,
    )
    monkeypatch.setattr(
        task_handlers,
        "create_project_from_snapshot_async",
        _fake_create_project_from_snapshot_async,
    )
    monkeypatch.setattr(
        task_handlers,
        "delete_staged_snapshot_upload_async",
        _fake_delete_staged_snapshot_upload_async,
    )

    await task_handlers._snapshot_import_task_async(
        "job-1",
        "snapshot-project",
        "repo.zip",
        "/tmp/staged.zip",
        12,
    )

    assert [status for status, _ in statuses] == ["running", "succeeded"]
    assert statuses[1][1]["result"] == {
        "project_id": 73,
        "name": "snapshot-project",
        "snapshot_label": "repo.zip",
    }
    assert staged_paths == ["/tmp/staged.zip"]


@pytest.mark.anyio
async def test_snapshot_import_task_async_cleans_snapshot_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses: list[str] = []
    cleanup_calls: list[str] = []

    async def _fake_set_job_status_async(_session, _job_id: str, status: str, **_kwargs) -> None:
        statuses.append(status)

    class _SessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    meta = type("Meta", (), {"archive_name": "repo.zip"})()

    async def _fake_store_snapshot_upload_from_path_async(path: str, archive_name: str):
        _ = (path, archive_name)
        return meta

    async def _fake_create_project_from_snapshot_async(session, name: str, _meta, org_id: int):
        _ = (session, name, _meta, org_id)
        raise RuntimeError("db failure")

    async def _fake_delete_snapshot_async(cleanup_meta) -> None:
        assert cleanup_meta is meta
        cleanup_calls.append("snapshot")

    async def _fake_delete_staged_snapshot_upload_async(path: str) -> None:
        _ = path
        cleanup_calls.append("staged")

    monkeypatch.setattr(task_handlers, "_set_job_status_async", _fake_set_job_status_async)
    monkeypatch.setattr(task_handlers, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(
        task_handlers,
        "store_snapshot_upload_from_path_async",
        _fake_store_snapshot_upload_from_path_async,
    )
    monkeypatch.setattr(
        task_handlers,
        "create_project_from_snapshot_async",
        _fake_create_project_from_snapshot_async,
    )
    monkeypatch.setattr(task_handlers, "delete_snapshot_async", _fake_delete_snapshot_async)
    monkeypatch.setattr(
        task_handlers,
        "delete_staged_snapshot_upload_async",
        _fake_delete_staged_snapshot_upload_async,
    )

    await task_handlers._snapshot_import_task_async(
        "job-2",
        "snapshot-project",
        "repo.zip",
        "/tmp/staged.zip",
        12,
    )

    assert statuses == ["running", "failed"]
    assert cleanup_calls == ["snapshot", "staged"]


@pytest.mark.anyio
async def test_snapshot_import_task_async_cleans_snapshot_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses: list[str] = []
    cleanup_calls: list[str] = []

    async def _fake_set_job_status_async(_session, _job_id: str, status: str, **_kwargs) -> None:
        statuses.append(status)

    class _SessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    meta = type("Meta", (), {"archive_name": "repo.zip"})()

    async def _fake_store_snapshot_upload_from_path_async(path: str, archive_name: str):
        _ = (path, archive_name)
        return meta

    async def _fake_create_project_from_snapshot_async(session, name: str, _meta, org_id: int):
        _ = (session, name, _meta, org_id)
        raise asyncio.CancelledError("cancelled")

    async def _fake_delete_snapshot_async(cleanup_meta) -> None:
        assert cleanup_meta is meta
        cleanup_calls.append("snapshot")

    async def _fake_delete_staged_snapshot_upload_async(path: str) -> None:
        _ = path
        cleanup_calls.append("staged")

    monkeypatch.setattr(task_handlers, "_set_job_status_async", _fake_set_job_status_async)
    monkeypatch.setattr(task_handlers, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(
        task_handlers,
        "store_snapshot_upload_from_path_async",
        _fake_store_snapshot_upload_from_path_async,
    )
    monkeypatch.setattr(
        task_handlers,
        "create_project_from_snapshot_async",
        _fake_create_project_from_snapshot_async,
    )
    monkeypatch.setattr(task_handlers, "delete_snapshot_async", _fake_delete_snapshot_async)
    monkeypatch.setattr(
        task_handlers,
        "delete_staged_snapshot_upload_async",
        _fake_delete_staged_snapshot_upload_async,
    )

    await task_handlers._snapshot_import_task_async(
        "job-3",
        "snapshot-project",
        "repo.zip",
        "/tmp/staged.zip",
        12,
    )

    assert statuses == ["running", "failed"]
    assert cleanup_calls == ["snapshot", "staged"]
