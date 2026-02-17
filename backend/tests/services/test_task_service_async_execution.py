import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import task_service


@pytest.mark.anyio
async def test_run_task_async_offloads_sync_execution(monkeypatch):
    request = task_service.TaskRequest(
        target_path="backend/app/main.py",
        prompt="check",
        mode="analyze",
        profile=None,
        depth=1,
        dep_mode="contracts",
        impact_max_nodes=None,
        impact_max_depth=None,
        apply_patch=False,
        allow_out_of_context_patch=False,
        agentic=False,
        provided_fields=set(),
    )

    captured: dict[str, object] = {}
    entitlement_calls: list[int] = []

    class _Session:
        async def commit(self):
            return None

    class _SessionCtx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    async def _fake_enforce(session, org_id):
        _ = session
        entitlement_calls.append(org_id)

    async def _fake_to_thread(func, *args, **kwargs):
        captured["func"] = func
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(task_service, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements_async", _fake_enforce)

    result = await task_service.run_task_async(11, 22, request)

    assert result == {"ok": True}
    assert captured["func"] is task_service.run_task
    assert captured["args"] == (11, 22, request)
    assert captured["kwargs"] == {"enforce_llm_entitlements": False}
    assert entitlement_calls == [22]


@pytest.mark.anyio
async def test_run_task_async_skips_async_entitlements_for_impact_mode(monkeypatch):
    request = task_service.TaskRequest(
        target_path="backend/app/main.py",
        prompt="check",
        mode="impact",
        profile=None,
        depth=1,
        dep_mode="contracts",
        impact_max_nodes=None,
        impact_max_depth=None,
        apply_patch=False,
        allow_out_of_context_patch=False,
        agentic=False,
        provided_fields=set(),
    )

    async def _fake_to_thread(func, *args, **kwargs):
        _ = (func, args, kwargs)
        return {"ok": True}

    async def _fail_enforce(session, org_id):
        _ = (session, org_id)
        raise AssertionError("entitlements check should be skipped")

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements_async", _fail_enforce)

    result = await task_service.run_task_async(11, 22, request)

    assert result == {"ok": True}


def test_scan_with_background_uses_async_submit(monkeypatch):
    async def _fake_get_active(project_id: int, org_id: int):
        return None, None

    async def _fake_submit_scan(project_id: int, org_id: int):
        _ = (project_id, org_id)
        return "scan-123"

    run_calls = {"count": 0}
    original_run = task_service.asyncio.run

    def _fake_run(coro):
        run_calls["count"] += 1
        return original_run(coro)

    monkeypatch.setattr(task_service, "_get_active_scan_task_async", _fake_get_active)
    monkeypatch.setattr(task_service, "submit_scan_async", _fake_submit_scan)
    monkeypatch.setattr(task_service.asyncio, "run", _fake_run)

    result = task_service.scan_with_background(5, 9)

    assert result == {"task_id": "scan-123", "status": "pending"}
    assert run_calls["count"] == 2


@pytest.mark.anyio
async def test_apply_patch_and_record_async_builds_contracts_via_async_path(monkeypatch):
    class _Run:
        applied_json = None

    class _Session:
        def __init__(self):
            self.run = _Run()
            self.commits = 0

        async def get(self, model, run_id):
            _ = (model, run_id)
            return self.run

        def add(self, item):
            _ = item

        async def commit(self):
            self.commits += 1

        async def execute(self, stmt):
            _ = stmt
            return None

    class _Lock:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    calls = {"path_state": 0, "contract_async": 0}

    async def _fake_path_exists_and_is_file(path):
        _ = path
        calls["path_state"] += 1
        return True, True

    async def _fake_contract_async(session, project_id, root, rel_path):
        _ = (session, project_id, root)
        calls["contract_async"] += 1
        return {"path": rel_path}

    monkeypatch.setattr(task_service, "project_lock_async", lambda *_args, **_kwargs: _Lock())
    monkeypatch.setattr(task_service, "_parse_diff_paths", lambda root, patch_text: ["a.py"])
    monkeypatch.setattr(task_service, "apply_unified_diff", lambda *args, **kwargs: ["a.py"])
    monkeypatch.setattr(task_service, "scan_files", lambda *args, **kwargs: {"aborted": False})
    monkeypatch.setattr(
        task_service,
        "update_graph_metrics_incremental",
        lambda *args, **kwargs: None,
    )
    async def _fake_resolve_under_root_async(root, rel_path, *, max_length):
        _ = (root, max_length)
        return Path("/tmp/a.py"), rel_path

    monkeypatch.setattr(task_service, "_resolve_under_root_async", _fake_resolve_under_root_async)
    monkeypatch.setattr(
        task_service,
        "resolve_under_root",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sync resolve path must not be used")
        ),
    )
    monkeypatch.setattr(
        task_service,
        "_path_exists_and_is_file_async",
        _fake_path_exists_and_is_file,
    )
    monkeypatch.setattr(task_service, "get_or_build_contract_async", _fake_contract_async)
    monkeypatch.setattr(
        task_service,
        "get_or_build_contract",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("sync contract path must not be used")
        ),
    )

    session = _Session()
    result = await task_service._apply_patch_and_record_async(
        session,
        project_id=7,
        org_id=8,
        run_id=9,
        root=Path("/tmp"),
        patch_text="diff --git a/a.py b/a.py\n",
        allowed_patch_paths={"a.py"},
        allow_out_of_context_patch=False,
    )

    assert result is not None
    assert result["contracts_updated"] == ["a.py"]
    assert calls == {"path_state": 1, "contract_async": 1}
    assert session.commits == 1


@pytest.mark.anyio
async def test_path_exists_and_is_file_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return True, True

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)

    result = await task_service._path_exists_and_is_file_async(Path("/tmp/a.py"))

    assert result == (True, True)
    assert calls["func"] is task_service._path_exists_and_is_file
    assert calls["args"] == (Path("/tmp/a.py"),)
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_task_service_async_wrappers_use_to_thread(monkeypatch):
    calls: list[tuple[object, tuple, dict]] = []

    async def _fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return "ok"

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)

    result_patch = await task_service._apply_unified_diff_async(
        Path("/tmp"),
        "diff --git a/a.py b/a.py\n",
        allowed_rel_paths={"a.py"},
        allow_new_files=False,
    )
    result_scan = await task_service._scan_files_async(1, 2, Path("/tmp"), ["a.py"])
    result_metrics = await task_service._update_graph_metrics_incremental_async(
        1,
        ["a.py"],
        removed_edge_neighbors=None,
    )

    assert result_patch == "ok"
    assert result_scan == "ok"
    assert result_metrics is None
    assert calls[0][0] is task_service.apply_unified_diff
    assert calls[1][0] is task_service.scan_files
    assert calls[2][0] is task_service.update_graph_metrics_incremental


@pytest.mark.anyio
async def test_resolve_under_root_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return Path("/tmp/a.py"), "a.py"

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)

    result = await task_service._resolve_under_root_async(
        Path("/tmp"),
        "a.py",
        max_length=120,
    )

    assert result == (Path("/tmp/a.py"), "a.py")
    assert calls["func"] is task_service.resolve_under_root
    assert calls["args"] == (Path("/tmp"), "a.py")
    assert calls["kwargs"] == {"max_length": 120}


@pytest.mark.anyio
async def test_parse_diff_paths_async_uses_to_thread(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return ["a.py"]

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)

    result = await task_service._parse_diff_paths_async(Path("/tmp"), "diff --git a/a.py b/a.py\n")

    assert result == ["a.py"]
    assert calls["func"] is task_service._parse_diff_paths
    assert calls["args"] == (Path("/tmp"), "diff --git a/a.py b/a.py\n")
    assert calls["kwargs"] == {}


@pytest.mark.anyio
async def test_get_active_scan_task_async_uses_async_idempotency_key(monkeypatch):
    class _FakeResult:
        def scalars(self):
            return self

        def first(self):
            return None

    class _FakeSession:
        async def execute(self, stmt):
            _ = stmt
            return _FakeResult()

    class _FakeSessionContext:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    calls: list[tuple[int, int]] = []

    async def _fake_get_scan_idempotency_key_async(org_id: int, project_id: int) -> str:
        calls.append((org_id, project_id))
        return "scan-idem-key"

    monkeypatch.setattr(
        task_service,
        "get_scan_idempotency_key_async",
        _fake_get_scan_idempotency_key_async,
    )
    monkeypatch.setattr(task_service, "AsyncSessionLocal", lambda: _FakeSessionContext())

    task_id, status = await task_service._get_active_scan_task_async(project_id=10, org_id=20)

    assert task_id is None
    assert status is None
    assert calls == [(20, 10)]
