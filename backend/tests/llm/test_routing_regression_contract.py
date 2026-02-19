import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.llm.routing_selector import select_runtime_route_async
from tests.llm._routing_fixtures import MODEL_STATS_CANONICAL


@pytest.mark.anyio
async def test_async_routing_regression_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    stats = {k: dict(v) for k, v in MODEL_STATS_CANONICAL.items()}

    async def _thresholds_async():
        return (1.1, 1.5, 1.9)

    async def _weights_async(*_args, **_kwargs):
        return {"quality": 0.4, "latency": 0.25, "token_cost": 0.2, "fail_rate": 0.15}

    monkeypatch.setattr(
        "app.llm.routing_selector.resolve_routing_thresholds_async",
        _thresholds_async,
    )
    monkeypatch.setattr("app.llm.routing_selector.resolve_routing_weights_async", _weights_async)

    selection = await select_runtime_route_async(
        task_kind="analyze",
        complexity_coeff=1.5,
        prompt_len=300,
        project_nodes=500,
        sla_profile="balanced",
        model_stats=stats,
        quality_weight=0.4,
        latency_weight=0.25,
        token_cost_weight=0.2,
        fail_rate_weight=0.15,
        low_confidence_threshold=0.0,
    )

    assert selection is not None
    assert selection.reason == "telemetry_score"
    assert isinstance(selection.score_breakdown.get("stages"), list)
