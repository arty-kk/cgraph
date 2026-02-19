import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.llm.policy import _parse_model_pool, resolve_runtime_policy_async


def test_parse_model_pool() -> None:
    assert _parse_model_pool("gpt-5-nano") == ["gpt-5-nano"]
    assert _parse_model_pool("gpt-5-nano|gpt-5-mini, gpt-5.2-codex") == [
        "gpt-5-nano",
        "gpt-5-mini",
        "gpt-5.2-codex",
    ]


@pytest.mark.anyio
async def test_runtime_policy_selects_higher_tier_for_higher_complexity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_triage = settings.triage_model
    old_analysis = settings.analysis_model
    old_patch = settings.patch_model
    try:
        settings.triage_model = "gpt-5-nano|gpt-5-mini"
        settings.analysis_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
        settings.patch_model = "gpt-5-mini|gpt-5.2-codex"
        async def _thresholds_async():
            return (1.0, 1.5, 1.9)

        monkeypatch.setattr("app.llm.policy.resolve_routing_thresholds_async", _thresholds_async)

        low = await resolve_runtime_policy_async(
            task_kind="analyze",
            complexity_coeff=1.0,
            prompt_len=10,
        )
        high = await resolve_runtime_policy_async(
            task_kind="fix",
            complexity_coeff=1.9,
            prompt_len=5000,
        )

        assert low.analysis_model == "gpt-5-mini"
        assert high.analysis_model == "gpt-5.2-codex"
        assert low.patch_model == "gpt-5-mini"
        assert high.patch_model == "gpt-5.2-codex"
        assert high.verifier_effort == "high"
    finally:
        settings.triage_model = old_triage
        settings.analysis_model = old_analysis
        settings.patch_model = old_patch
