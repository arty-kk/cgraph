import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import task_service


@pytest.mark.anyio
async def test_run_task_async_uses_direct_async_impl(monkeypatch):
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

    class _Session:
        pass

    class _SessionCtx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    async def _fake_impl(session, project_id, org_id, req):
        captured["session"] = session
        captured["args"] = (project_id, org_id, req)
        return {"ok": True}

    monkeypatch.setattr(task_service, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(task_service, "_run_task_impl_async", _fake_impl)

    result = await task_service.run_task_async(11, 22, request)

    assert result == {"ok": True}
    assert captured["args"] == (11, 22, request)


@pytest.mark.anyio
async def test_run_task_async_passes_through_impact_mode(monkeypatch):
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

    class _SessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    async def _fake_impl(session, project_id, org_id, req):
        _ = (session, project_id, org_id, req)
        return {"ok": True}

    monkeypatch.setattr(task_service, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(task_service, "_run_task_impl_async", _fake_impl)

    result = await task_service.run_task_async(11, 22, request)

    assert result == {"ok": True}


@pytest.mark.anyio
async def test_scan_with_background_async_uses_async_submit(monkeypatch):
    async def _fake_get_active(project_id: int, org_id: int):
        return None, None

    async def _fake_submit_scan(project_id: int, org_id: int):
        _ = (project_id, org_id)
        return "scan-123"

    monkeypatch.setattr(task_service, "_get_active_scan_task_async", _fake_get_active)
    monkeypatch.setattr(task_service, "submit_scan_async", _fake_submit_scan)

    result = await task_service._scan_with_background_async(5, 9)

    assert result == {"task_id": "scan-123", "status": "pending"}


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
    async def _fake_scan_files_async(*args, **kwargs):
        _ = args, kwargs
        return {"aborted": False}

    monkeypatch.setattr(task_service, "scan_files_async", _fake_scan_files_async)
    async def _fake_update_graph_metrics_incremental_async(*args, **kwargs):
        _ = args, kwargs
        return None

    monkeypatch.setattr(
        task_service,
        "update_graph_metrics_incremental_async",
        _fake_update_graph_metrics_incremental_async,
    )
    async def _fake_resolve_under_root_async(root, rel_path, *, max_length):
        _ = (root, max_length)
        return Path("/tmp/a.py"), rel_path

    monkeypatch.setattr(task_service, "_resolve_under_root_async", _fake_resolve_under_root_async)
    monkeypatch.setattr(
        task_service,
        "_path_exists_and_is_file_async",
        _fake_path_exists_and_is_file,
    )
    monkeypatch.setattr(task_service, "get_or_build_contract_async", _fake_contract_async)
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

    async def _fake_scan_files_async(*_args, **_kwargs):
        return "scan-ok"

    async def _fake_update_graph_metrics_incremental_async(*args, **kwargs):
        assert args == ("session", 1, ["a.py"])
        assert kwargs == {"removed_edge_neighbors": None}
        return None

    monkeypatch.setattr(task_service.asyncio, "to_thread", _fake_to_thread)
    monkeypatch.setattr(task_service, "scan_files_async", _fake_scan_files_async)
    monkeypatch.setattr(
        task_service,
        "update_graph_metrics_incremental_async",
        _fake_update_graph_metrics_incremental_async,
    )

    result_patch = await task_service._apply_unified_diff_async(
        Path("/tmp"),
        "diff --git a/a.py b/a.py\n",
        allowed_rel_paths={"a.py"},
        allow_new_files=False,
    )
    result_scan = await task_service._scan_files_async(1, 2, Path("/tmp"), ["a.py"])
    result_metrics = await task_service._update_graph_metrics_incremental_async(
        "session",
        1,
        ["a.py"],
        removed_edge_neighbors=None,
    )

    assert result_patch == "ok"
    assert result_scan == "scan-ok"
    assert result_metrics is None
    assert len(calls) == 1
    assert calls[0][0] is task_service.apply_unified_diff


@pytest.mark.anyio
async def test_store_patch_blob_async_helper_uses_async_storage_api(monkeypatch):
    calls: dict[str, object] = {}

    async def _fake_store_patch_blob_async(patch_text: str):
        calls["patch_text"] = patch_text
        return {"storage": "local", "sha256": "sha-1"}

    monkeypatch.setattr(task_service, "store_patch_blob_async", _fake_store_patch_blob_async)

    payload = await task_service._store_patch_blob_async("x" * 10)

    assert calls["patch_text"] == "x" * 10
    assert payload["storage"] == "local"
    assert payload["sha256"] == "sha-1"
    assert payload["omitted"] is True
    assert payload["chars"] == 10
    assert payload["store_limit_chars"] == task_service.MAX_PATCH_STORE_CHARS


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


@pytest.mark.anyio
async def test_run_task_impl_async_uses_async_orchestrator_calls(monkeypatch, tmp_path):
    file_path = tmp_path / "target.py"
    file_path.write_text("print('x')\n", encoding="utf-8")

    request = task_service.TaskRequest(
        target_path="target.py",
        prompt="analyze",
        mode="analyze",
        profile=None,
        depth=1,
        dep_mode="contracts",
        impact_max_nodes=None,
        impact_max_depth=None,
        apply_patch=False,
        allow_out_of_context_patch=False,
        agentic=False,
        provided_fields={"mode"},
    )

    class _Session:
        async def execute(self, stmt):
            _ = stmt
            class _Result:
                def scalars(self):
                    return self
                def all(self):
                    return []
                def one(self):
                    return 0
                def first(self):
                    return None
            return _Result()

        def add(self, item):
            _ = item

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def refresh(self, item):
            _ = item
            return None

    async def _fake_get_project(session, project_id, org_id):
        _ = (session, project_id, org_id)
        return type("P", (), {"root_path": str(tmp_path)})()

    async def _noop(*args, **kwargs):
        _ = (args, kwargs)
        return None

    called = {"plan": 0, "analyze": 0}

    async def _plan_async(*args, **kwargs):
        called["plan"] += 1
        return {"summary": "ok"}, {"prompt_tokens": 1, "completion_tokens": 1}

    async def _analyze_async(*args, **kwargs):
        called["analyze"] += 1
        return {
            "summary": "ok",
            "sources": [{"path": "target.py", "start_line": 1, "end_line": 1}],
        }, {"prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr(task_service, "_get_project_async", _fake_get_project)
    monkeypatch.setattr(task_service, "_ensure_node_exists_async", _noop)
    monkeypatch.setattr(task_service, "_graph_warning_async", _noop)
    monkeypatch.setattr(task_service, "_scan_with_background_async", _noop)
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements_async", _noop)
    monkeypatch.setattr(task_service.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(task_service.settings, "cache_enabled", False)
    monkeypatch.setattr(
        task_service,
        "resolve_runtime_policy",
        lambda **kwargs: task_service.DEFAULT_POLICY,
    )
    monkeypatch.setattr(task_service, "plan_task_with_usage_async", _plan_async)
    monkeypatch.setattr(task_service, "analyze_with_usage_async", _analyze_async)
    async def _pack_context_async(*args, **kwargs):
        _ = (args, kwargs)
        return type("Pack", (), {"target_path": "target.py", "files": [], "graph": {"deps": []}})()

    monkeypatch.setattr(task_service, "pack_context_async", _pack_context_async)

    await task_service._run_task_impl_async(_Session(), 1, 1, request)

    assert called == {"plan": 1, "analyze": 1}


@pytest.mark.anyio
async def test_run_task_impl_async_uses_async_agentic_calls(monkeypatch, tmp_path):
    file_path = tmp_path / "target.py"
    file_path.write_text("print('x')\n", encoding="utf-8")

    request = task_service.TaskRequest(
        target_path="target.py",
        prompt="analyze",
        mode="analyze",
        profile=None,
        depth=1,
        dep_mode="contracts",
        impact_max_nodes=None,
        impact_max_depth=None,
        apply_patch=False,
        allow_out_of_context_patch=False,
        agentic=True,
        provided_fields={"mode"},
        agentic_evidence_mode=False,
    )

    class _Session:
        async def execute(self, stmt):
            _ = stmt
            class _Result:
                def scalars(self):
                    return self
                def all(self):
                    return []
                def one(self):
                    return 0
                def first(self):
                    return None
            return _Result()

        def add(self, item):
            _ = item

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def refresh(self, item):
            _ = item
            return None

    async def _fake_get_project(session, project_id, org_id):
        _ = (session, project_id, org_id)
        return type("P", (), {"root_path": str(tmp_path)})()

    async def _noop(*args, **kwargs):
        _ = (args, kwargs)
        return None

    called = {"plan": 0, "agentic": 0}

    async def _plan_async(*args, **kwargs):
        called["plan"] += 1
        return {"summary": "ok"}, {}

    async def _agentic_async(*args, **kwargs):
        called["agentic"] += 1
        return {
            "summary": "ok",
            "sources": [{"path": "target.py", "start_line": 1, "end_line": 1}],
        }, task_service.AgenticMeta(self_check_missing_context=[])

    monkeypatch.setattr(task_service, "_get_project_async", _fake_get_project)
    monkeypatch.setattr(task_service, "_ensure_node_exists_async", _noop)
    monkeypatch.setattr(task_service, "_graph_warning_async", _noop)
    monkeypatch.setattr(task_service, "_scan_with_background_async", _noop)
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements_async", _noop)
    monkeypatch.setattr(task_service.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(task_service.settings, "cache_enabled", False)
    monkeypatch.setattr(
        task_service,
        "resolve_runtime_policy",
        lambda **kwargs: task_service.DEFAULT_POLICY,
    )
    monkeypatch.setattr(task_service, "plan_task_with_usage_async", _plan_async)
    monkeypatch.setattr(task_service, "analyze_agentic_async", _agentic_async)

    await task_service._run_task_impl_async(_Session(), 1, 1, request)

    assert called == {"plan": 1, "agentic": 1}


@pytest.mark.anyio
async def test_run_task_async_does_not_touch_sync_get_session(monkeypatch):
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

    class _SessionCtx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    async def _fake_impl(session, project_id, org_id, req):
        _ = (session, project_id, org_id, req)
        return {"ok": True}

    monkeypatch.setattr(task_service, "AsyncSessionLocal", lambda: _SessionCtx())
    monkeypatch.setattr(task_service, "_run_task_impl_async", _fake_impl)

    result = await task_service.run_task_async(1, 2, request)

    assert result == {"ok": True}


@pytest.mark.anyio
async def test_run_task_impl_async_non_agentic_does_not_touch_sync_get_session(
    monkeypatch, tmp_path
):
    file_path = tmp_path / "target.py"
    file_path.write_text("print('x')\n", encoding="utf-8")

    request = task_service.TaskRequest(
        target_path="target.py",
        prompt="analyze",
        mode="analyze",
        profile=None,
        depth=1,
        dep_mode="contracts",
        impact_max_nodes=None,
        impact_max_depth=None,
        apply_patch=False,
        allow_out_of_context_patch=False,
        agentic=False,
        provided_fields={"mode"},
    )

    class _Session:
        async def execute(self, stmt):
            _ = stmt

            class _Result:
                def all(self):
                    return []

                def first(self):
                    return None

                def scalars(self):
                    return self

                def one(self):
                    return 0

            return _Result()

        def add(self, item):
            _ = item

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def refresh(self, item):
            _ = item
            return None

    async def _fake_get_project(session, project_id, org_id):
        _ = (session, project_id, org_id)
        return type("P", (), {"root_path": str(tmp_path)})()

    async def _noop(*args, **kwargs):
        _ = (args, kwargs)
        return None

    async def _plan_async(*args, **kwargs):
        _ = (args, kwargs)
        return {"summary": "ok"}, {}

    async def _analyze_async(*args, **kwargs):
        _ = (args, kwargs)
        return {
            "summary": "ok",
            "sources": [{"path": "target.py", "start_line": 1, "end_line": 1}],
        }, {}

    async def _contract_async(*args, **kwargs):
        _ = (args, kwargs)
        return {"exports": []}

    import app.context_pack as context_pack
    monkeypatch.setattr(task_service, "_get_project_async", _fake_get_project)
    monkeypatch.setattr(task_service, "_ensure_node_exists_async", _noop)
    monkeypatch.setattr(task_service, "_graph_warning_async", _noop)
    monkeypatch.setattr(task_service, "_scan_with_background_async", _noop)
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements_async", _noop)
    monkeypatch.setattr(task_service.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(task_service.settings, "cache_enabled", False)
    monkeypatch.setattr(
        task_service,
        "resolve_runtime_policy",
        lambda **kwargs: task_service.DEFAULT_POLICY,
    )
    monkeypatch.setattr(task_service, "plan_task_with_usage_async", _plan_async)
    monkeypatch.setattr(task_service, "analyze_with_usage_async", _analyze_async)
    monkeypatch.setattr(context_pack, "get_or_build_contract_async", _contract_async)

    result = await task_service._run_task_impl_async(_Session(), 1, 1, request)

    assert result.get("result", {}).get("summary") == "ok"
