import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.llm.routing_selector import select_runtime_route_async
from tests.llm._routing_fixtures import MODEL_STATS_CANONICAL


@pytest.mark.anyio
async def test_returns_none_without_stats() -> None:
    selection = await select_runtime_route_async(
        task_kind="analyze",
        complexity_coeff=1.2,
        prompt_len=120,
        project_nodes=100,
        sla_profile="balanced",
        model_stats=None,
        quality_weight=0.4,
        latency_weight=0.25,
        token_cost_weight=0.2,
        fail_rate_weight=0.15,
        low_confidence_threshold=0.55,
    )
    assert selection is None


@pytest.mark.anyio
async def test_selects_telemetry_route_for_quality_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = {key: dict(value) for key, value in MODEL_STATS_CANONICAL.items()}
    old_triage = settings.triage_model
    old_analysis = settings.analysis_model
    old_patch = settings.patch_model
    try:
        settings.triage_model = "gpt-5-nano|gpt-5-mini"
        settings.analysis_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
        settings.patch_model = "gpt-5-mini|gpt-5.2-codex"

        async def _weights_async(*_args, **_kwargs):
            return {"quality": 0.9, "latency": 0.05, "token_cost": 0.03, "fail_rate": 0.02}

        async def _thresholds_async():
            return (1.0, 1.4, 1.8)

        monkeypatch.setattr(
            "app.llm.routing_selector.resolve_routing_weights_async",
            _weights_async,
        )
        monkeypatch.setattr(
            "app.llm.routing_selector.resolve_routing_thresholds_async",
            _thresholds_async,
        )

        selection = await select_runtime_route_async(
            task_kind="fix",
            complexity_coeff=1.9,
            prompt_len=6000,
            project_nodes=1200,
            sla_profile="quality",
            model_stats=stats,
            quality_weight=0.9,
            latency_weight=0.05,
            token_cost_weight=0.03,
            fail_rate_weight=0.02,
            low_confidence_threshold=0.05,
        )
    finally:
        settings.triage_model = old_triage
        settings.analysis_model = old_analysis
        settings.patch_model = old_patch

    assert selection is not None
    assert selection.reason == "telemetry_score"
    assert selection.policy.analysis_model == "gpt-5.2-codex"
