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
    def one(self):
        return 0

    def all(self):
        return []

    def first(self):
        return None


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def exec(self, query):
        return _FakeResult()



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

    monkeypatch.setattr(
        task_service,
        "get_project",
        lambda project_id, org_id: SimpleNamespace(root_path=str(tmp_path)),
    )
    monkeypatch.setattr(task_service, "_ensure_node_exists", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_service, "_graph_warning", lambda project_id: None)
    monkeypatch.setattr(task_service, "scan_with_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements", lambda org_id: None)
    monkeypatch.setattr(task_service, "resolve_runtime_policy", lambda **kwargs: ModelPolicy())
    monkeypatch.setattr(task_service, "plan_task", lambda *args, **kwargs: {"summary": "ok"})
    monkeypatch.setattr(task_service, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(task_service.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(task_service.settings, "llm_evidence_min_sources", 2)


def test_pack_mode_returns_quality_gate_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_common(monkeypatch, tmp_path)

    monkeypatch.setattr(
        task_service,
        "pack_context",
        lambda *args, **kwargs: SimpleNamespace(
            target_path="target.py",
            files=[{"path": "target.py", "kind": "target", "content": "x"}],
            graph={"deps": [], "inbound": [], "outbound": []},
        ),
    )
    monkeypatch.setattr(
        task_service,
        "fix",
        lambda *args, **kwargs: {
            "sources": [],
            "patch_unified_diff": "",
            "tests": ["   "],
        },
    )

    with pytest.raises(BadRequestError) as exc:
        task_service.run_task(1, 1, _request(mode="fix", agentic=False))

    assert exc.value.code == "quality_gate_failed"
    assert exc.value.context["mode"] == "fix"
    assert any(reason["field"] == "sources" for reason in exc.value.context["reasons"])


def test_agentic_retry_path_runs_quality_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_common(monkeypatch, tmp_path)


    calls = {"count": 0}

    def _analyze_agentic(*args, **kwargs):
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

    monkeypatch.setattr(task_service, "analyze_agentic", _analyze_agentic)

    with pytest.raises(BadRequestError) as exc:
        task_service.run_task(1, 1, _request(mode="analyze", agentic=True, evidence_mode=True))

    assert calls["count"] == 2
    assert exc.value.code == "quality_gate_failed"
    assert exc.value.context["evidence_mode"] is True
    assert exc.value.context["min_sources"] == 2
    assert any(reason["code"] == "insufficient_sources" for reason in exc.value.context["reasons"])
