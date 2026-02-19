import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.errors import BadRequestError
from app.llm.agentic.types import AgenticMeta
from app.llm.policy import ModelPolicy
from app.services import task_service
from app.services.task_service import TaskRequest


class _FakeResult:
    def scalars(self):
        return self

    def one(self):
        return 0

    def all(self):
        return []

    def first(self):
        return None


class _FakeSession:
    async def execute(self, query):
        _ = query
        return _FakeResult()

    def add(self, item):
        _ = item

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def refresh(self, item):
        _ = item
        return None



def _request(*, mode: str, agentic: bool, evidence_mode: bool = False) -> TaskRequest:
    return TaskRequest(
        target_path="target.py",
        prompt="fix it",
        mode=mode,
        profile=None,
        depth=1,
        dep_mode="contracts",
        impact_max_nodes=None,
        impact_max_depth=None,
        apply_patch=False,
        allow_out_of_context_patch=False,
        agentic=agentic,
        provided_fields={"mode"},
        agentic_evidence_mode=evidence_mode,
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "target.py"
    file_path.write_text("print('x')\n", encoding="utf-8")

    async def _fake_get_project(session, project_id, org_id):
        _ = (session, project_id, org_id)
        return SimpleNamespace(root_path=str(tmp_path))

    async def _noop(*args, **kwargs):
        _ = (args, kwargs)
        return None

    monkeypatch.setattr(task_service, "_get_project_async", _fake_get_project)
    monkeypatch.setattr(task_service, "_ensure_node_exists_async", _noop)
    monkeypatch.setattr(task_service, "_graph_warning_async", _noop)
    monkeypatch.setattr(task_service, "_scan_with_background_async", _noop)
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements_async", _noop)
    async def _policy_async(**kwargs):
        _ = kwargs
        return ModelPolicy()

    monkeypatch.setattr(task_service, "resolve_runtime_policy_async", _policy_async)
    
    async def _plan_task_async(*args, **kwargs):
        _ = (args, kwargs)
        return {"summary": "ok"}, {}

    monkeypatch.setattr(task_service, "plan_task_with_usage_async", _plan_task_async)
    monkeypatch.setattr(task_service.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(task_service.settings, "llm_evidence_min_sources", 2)


@pytest.mark.anyio
async def test_pack_mode_returns_quality_gate_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_common(monkeypatch, tmp_path)

    async def _pack_context_async(*args, **kwargs):
        _ = (args, kwargs)
        return SimpleNamespace(
            target_path="target.py",
            files=[{"path": "target.py", "kind": "target", "content": "x"}],
            graph={"deps": [], "inbound": [], "outbound": []},
        )

    monkeypatch.setattr(task_service, "pack_context_async", _pack_context_async)
    async def _fix_async(*args, **kwargs):
        _ = (args, kwargs)
        return {"sources": [], "patch_unified_diff": "", "tests": ["   "]}, {}

    monkeypatch.setattr(task_service, "fix_with_usage_async", _fix_async)

    with pytest.raises(BadRequestError) as exc:
        await task_service._run_task_impl_async(
            _FakeSession(), 1, 1, _request(mode="fix", agentic=False)
        )

    assert exc.value.code == "quality_gate_failed"
    assert exc.value.context["mode"] == "fix"
    assert any(reason["field"] == "sources" for reason in exc.value.context["reasons"])


@pytest.mark.anyio
async def test_agentic_retry_path_runs_quality_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_common(monkeypatch, tmp_path)


    calls = {"count": 0}

    async def _analyze_agentic_async(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                {"sources": [
                    {"path": "target.py", "start_line": 1, "end_line": 1},
                    {"path": "other.py", "start_line": 2, "end_line": 3},
                ]},
                AgenticMeta(self_check_missing_context=["need one more file"]),
            )
        return (
            {"sources": [{"path": "", "start_line": 1, "end_line": 1}]},
            AgenticMeta(self_check_missing_context=[]),
        )

    monkeypatch.setattr(task_service, "analyze_agentic_async", _analyze_agentic_async)

    with pytest.raises(BadRequestError) as exc:
        await task_service._run_task_impl_async(
            _FakeSession(), 1, 1, _request(mode="analyze", agentic=True, evidence_mode=True)
        )

    assert calls["count"] == 2
    assert exc.value.code == "quality_gate_failed"
    assert exc.value.context["evidence_mode"] is True
    assert exc.value.context["min_sources"] == 2
    assert any(reason["code"] == "insufficient_sources" for reason in exc.value.context["reasons"])
