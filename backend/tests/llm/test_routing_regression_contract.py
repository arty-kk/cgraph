import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.llm.policy import ModelPolicy
from app.llm.routing_selector import RoutingSelection, select_runtime_route
from app.services import task_service
from app.services.task_service import TaskRequest

from tests.llm._routing_fixtures import (
    DEFAULT_ROUTING_SETTINGS,
    MODEL_STATS_CANONICAL,
    MODEL_STATS_THRESHOLD_SWITCH,
)


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

    def add(self, obj):
        return None

    def commit(self):
        return None

    def flush(self):
        return None

    def refresh(self, obj):
        return None


def _run_route_case(
    monkeypatch: pytest.MonkeyPatch,
    *,
    task_kind: str,
    complexity_coeff: float,
    prompt_len: int,
    project_nodes: int,
    sla_profile: str = "balanced",
    model_stats: dict[str, dict[str, float]] | None = MODEL_STATS_CANONICAL,
    low_confidence_threshold: float = 0.05,
    thresholds_cache_payload: dict[str, float] | None = None,
    weights_cache_payload: dict[str, object] | None = None,
    settings_overrides: dict[str, object] | None = None,
):
    for key, value in DEFAULT_ROUTING_SETTINGS.items():
        monkeypatch.setattr(settings, key, value)
    for key, value in (settings_overrides or {}).items():
        monkeypatch.setattr(settings, key, value)

    with patch(
        "app.llm.routing_thresholds.cache_get_json",
        return_value=thresholds_cache_payload,
    ), patch(
        "app.llm.routing_weights.cache_get_json",
        return_value=weights_cache_payload,
    ):
        return select_runtime_route(
            task_kind=task_kind,
            complexity_coeff=complexity_coeff,
            prompt_len=prompt_len,
            project_nodes=project_nodes,
            sla_profile=sla_profile,
            model_stats=model_stats,
            quality_weight=settings.llm_routing_weight_quality,
            latency_weight=settings.llm_routing_weight_latency,
            token_cost_weight=settings.llm_routing_weight_token_cost,
            fail_rate_weight=settings.llm_routing_weight_fail_rate,
            low_confidence_threshold=low_confidence_threshold,
        )


@pytest.mark.parametrize(
    ("case_name", "params", "expected"),
    [
        (
            "simple",
            {
                "task_kind": "analyze",
                "complexity_coeff": 1.05,
                "prompt_len": 120,
                "project_nodes": 20,
            },
            {
                "triage_model": "gpt-5-nano",
                "analysis_model": "gpt-5-nano",
                "patch_model": "gpt-5-mini",
                "verifier_model": "gpt-5-nano",
                "verifier_effort": "medium",
                "verifier_edge_case": False,
                "effective_complexity": 1.052,
            },
        ),
        (
            "medium",
            {
                "task_kind": "fix",
                "complexity_coeff": 1.45,
                "prompt_len": 2200,
                "project_nodes": 500,
            },
            {
                "triage_model": "gpt-5-nano",
                "analysis_model": "gpt-5-nano",
                "patch_model": "gpt-5-mini",
                "verifier_model": "gpt-5-nano",
                "verifier_effort": "medium",
                "verifier_edge_case": False,
                "effective_complexity": 1.6,
            },
        ),
        (
            "complex",
            {
                "task_kind": "fix",
                "complexity_coeff": 1.75,
                "prompt_len": 6800,
                "project_nodes": 1600,
            },
            {
                "triage_model": "gpt-5-nano",
                "analysis_model": "gpt-5-nano",
                "patch_model": "gpt-5-mini",
                "verifier_model": "gpt-5-nano",
                "verifier_effort": "high",
                "verifier_edge_case": True,
                "effective_complexity": 2.0,
            },
        ),
    ],
)
def test_select_runtime_route_contract_for_canonical_cases(
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    params: dict[str, object],
    expected: dict[str, object],
) -> None:
    selection = _run_route_case(monkeypatch, **params)

    assert selection is not None, case_name
    assert selection.reason == "telemetry_score"
    assert selection.policy.triage_model == expected["triage_model"]
    assert selection.policy.analysis_model == expected["analysis_model"]
    assert selection.policy.patch_model == expected["patch_model"]
    assert selection.policy.verifier_model == expected["verifier_model"]
    assert selection.policy.verifier_effort == expected["verifier_effort"]

    breakdown = selection.score_breakdown
    assert breakdown["policy_version"] == settings.llm_routing_policy_version
    assert breakdown["sla_profile"] == "balanced"
    assert breakdown["effective_weights"] == {
        "quality": 0.4,
        "latency": 0.25,
        "token_cost": 0.2,
        "fail_rate": 0.15,
    }
    assert breakdown["effective_complexity"] == expected["effective_complexity"]
    assert breakdown["verifier_edge_case"] is expected["verifier_edge_case"]

    stages = breakdown["stages"]
    assert len(stages) == 4
    assert [stage.get("stage") for stage in stages] == ["triage", "analysis", "patch", "verifier"]
    for stage in stages:
        assert "stage" in stage
        assert "selected" in stage


def test_select_runtime_route_returns_none_without_model_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _run_route_case(
        monkeypatch,
        task_kind="analyze",
        complexity_coeff=1.2,
        prompt_len=240,
        project_nodes=100,
        model_stats=None,
    )
    assert selection is None


def test_select_runtime_route_returns_none_on_low_confidence_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _run_route_case(
        monkeypatch,
        task_kind="analyze",
        complexity_coeff=1.2,
        prompt_len=240,
        project_nodes=100,
        low_confidence_threshold=0.95,
    )
    assert selection is None


@pytest.mark.parametrize(
    ("routing_selection", "expected_source"),
    [
        (None, "fallback_policy"),
        (
            RoutingSelection(
                policy=ModelPolicy(),
                confidence=0.77,
                reason="telemetry_score",
                score_breakdown={"policy_version": "contract-v1"},
            ),
            "telemetry_score",
        ),
    ],
)
def test_task_service_sets_model_routing_reason_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    routing_selection: RoutingSelection | None,
    expected_source: str,
) -> None:
    target = tmp_path / "target.py"
    target.write_text("print('x')\n", encoding="utf-8")

    monkeypatch.setattr(
        task_service,
        "get_project",
        lambda project_id, org_id: SimpleNamespace(root_path=str(tmp_path)),
    )
    monkeypatch.setattr(task_service, "_ensure_node_exists", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_service, "_graph_warning", lambda project_id: None)
    monkeypatch.setattr(task_service, "scan_with_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_service, "_enforce_llm_entitlements", lambda org_id: None)
    monkeypatch.setattr(task_service, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(task_service, "_impact", lambda *args, **kwargs: ([], False))
    monkeypatch.setattr(task_service, "resolve_runtime_policy", lambda **kwargs: ModelPolicy())
    monkeypatch.setattr(task_service, "select_runtime_route", lambda **kwargs: routing_selection)
    monkeypatch.setattr(task_service.settings, "openai_api_key", "")

    response = task_service.run_task(
        1,
        1,
        TaskRequest(
            target_path="target.py",
            prompt="impact",
            mode="impact",
            profile=None,
            depth=1,
            dep_mode="contracts",
            impact_max_nodes=None,
            impact_max_depth=None,
            apply_patch=False,
            allow_out_of_context_patch=False,
            agentic=False,
            provided_fields={"mode"},
        ),
    )

    reason = response["retrieval_settings"]["agentic"]["model_routing_reason"]
    assert reason["source"] == expected_source


def test_thresholds_cache_override_controls_verifier_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _run_route_case(
        monkeypatch,
        task_kind="fix",
        complexity_coeff=1.4,
        prompt_len=120,
        project_nodes=0,
        model_stats=MODEL_STATS_THRESHOLD_SWITCH,
        thresholds_cache_payload={"low": 1.0, "mid": 1.8, "high": 1.9},
        settings_overrides={
            "llm_routing_threshold_low": 1.0,
            "llm_routing_threshold_mid": 1.2,
            "llm_routing_threshold_high": 1.4,
        },
    )

    assert selection is not None
    assert selection.policy.verifier_model == "gpt-5-nano"
    assert selection.policy.verifier_effort == "medium"
    assert selection.score_breakdown["verifier_edge_case"] is False


def test_invalid_thresholds_cache_payload_falls_back_to_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selection = _run_route_case(
        monkeypatch,
        task_kind="fix",
        complexity_coeff=1.4,
        prompt_len=120,
        project_nodes=0,
        model_stats=MODEL_STATS_THRESHOLD_SWITCH,
        thresholds_cache_payload={"low": 1.9, "mid": 1.5, "high": 2.1},
        settings_overrides={
            "llm_routing_threshold_low": 1.0,
            "llm_routing_threshold_mid": 1.2,
            "llm_routing_threshold_high": 1.4,
        },
    )

    assert selection is not None
    assert selection.policy.verifier_model == "gpt-5-mini"
    assert selection.policy.verifier_effort == "high"
    assert selection.score_breakdown["verifier_edge_case"] is True
