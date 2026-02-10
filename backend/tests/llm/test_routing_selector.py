import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.llm.routing_selector import select_runtime_route


class TestRoutingSelector(unittest.TestCase):
    def test_returns_none_without_stats(self) -> None:
        selection = select_runtime_route(
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
        self.assertIsNone(selection)

    def test_selects_telemetry_route_for_quality_profile(self) -> None:
        stats = {
            "gpt-5-nano": {
                "quality": 0.70,
                "latency_ms": 400,
                "token_cost": 0.2,
                "fail_rate": 0.04,
            },
            "gpt-5-mini": {
                "quality": 0.82,
                "latency_ms": 650,
                "token_cost": 0.5,
                "fail_rate": 0.03,
            },
            "gpt-5.2-codex": {
                "quality": 0.93,
                "latency_ms": 900,
                "token_cost": 0.9,
                "fail_rate": 0.02,
            },
        }
        old_triage = settings.triage_model
        old_analysis = settings.analysis_model
        old_patch = settings.patch_model
        try:
            settings.triage_model = "gpt-5-nano|gpt-5-mini"
            settings.analysis_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
            settings.patch_model = "gpt-5-mini|gpt-5.2-codex"

            selection = select_runtime_route(
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

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.reason, "telemetry_score")
        self.assertGreater(selection.confidence, 0.05)
        self.assertEqual(selection.policy.analysis_model, "gpt-5.2-codex")
        self.assertTrue(isinstance(selection.policy.verifier_model, str) and selection.policy.verifier_model)
        self.assertIn(selection.policy.verifier_effort, ("medium", "high"))


if __name__ == "__main__":
    unittest.main()
