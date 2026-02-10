import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.llm.routing_selector import select_runtime_route


class TestRoutingSelector(unittest.TestCase):
    @staticmethod
    def _model_stats() -> dict[str, dict[str, float]]:
        return {
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

    @staticmethod
    def _tradeoff_stats() -> dict[str, dict[str, float]]:
        return {
            "gpt-5-nano": {
                "quality": 0.74,
                "latency_ms": 180,
                "token_cost": 0.08,
                "fail_rate": 0.07,
            },
            "gpt-5-mini": {
                "quality": 0.84,
                "latency_ms": 420,
                "token_cost": 0.3,
                "fail_rate": 0.04,
            },
            "gpt-5.2-codex": {
                "quality": 0.95,
                "latency_ms": 980,
                "token_cost": 0.95,
                "fail_rate": 0.02,
            },
        }

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
        stats = self._model_stats()
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
        self.assertTrue(
            isinstance(selection.policy.verifier_model, str) and selection.policy.verifier_model
        )
        self.assertIn(selection.policy.verifier_effort, ("medium", "high"))

    def test_select_runtime_route_uses_thresholds_from_cache_override(self) -> None:
        stats = self._model_stats()
        old_triage = settings.triage_model
        old_analysis = settings.analysis_model
        old_patch = settings.patch_model
        old_low = settings.llm_routing_threshold_low
        old_mid = settings.llm_routing_threshold_mid
        old_high = settings.llm_routing_threshold_high
        try:
            settings.triage_model = "gpt-5-nano|gpt-5-mini"
            settings.analysis_model = "gpt-5-nano|gpt-5-mini"
            settings.patch_model = "gpt-5-mini|gpt-5.2-codex"
            settings.llm_routing_threshold_low = 1.0
            settings.llm_routing_threshold_mid = 1.2
            settings.llm_routing_threshold_high = 1.4

            with patch(
                "app.llm.routing_thresholds.cache_get_json",
                return_value={"low": 1.0, "mid": 1.8, "high": 1.9},
            ):
                selection = select_runtime_route(
                    task_kind="fix",
                    complexity_coeff=1.4,
                    prompt_len=120,
                    project_nodes=0,
                    sla_profile="balanced",
                    model_stats=stats,
                    quality_weight=0.4,
                    latency_weight=0.25,
                    token_cost_weight=0.2,
                    fail_rate_weight=0.15,
                    low_confidence_threshold=0.05,
                )
        finally:
            settings.triage_model = old_triage
            settings.analysis_model = old_analysis
            settings.patch_model = old_patch
            settings.llm_routing_threshold_low = old_low
            settings.llm_routing_threshold_mid = old_mid
            settings.llm_routing_threshold_high = old_high

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.policy.verifier_effort, "medium")

    def test_select_runtime_route_falls_back_to_defaults_for_invalid_cache_thresholds(self) -> None:
        stats = self._model_stats()
        old_triage = settings.triage_model
        old_analysis = settings.analysis_model
        old_patch = settings.patch_model
        old_low = settings.llm_routing_threshold_low
        old_mid = settings.llm_routing_threshold_mid
        old_high = settings.llm_routing_threshold_high
        try:
            settings.triage_model = "gpt-5-nano|gpt-5-mini"
            settings.analysis_model = "gpt-5-nano|gpt-5-mini"
            settings.patch_model = "gpt-5-mini|gpt-5.2-codex"
            settings.llm_routing_threshold_low = 1.0
            settings.llm_routing_threshold_mid = 1.2
            settings.llm_routing_threshold_high = 1.4

            with patch(
                "app.llm.routing_thresholds.cache_get_json",
                return_value={"low": 1.9, "mid": 1.5, "high": 2.1},
            ):
                selection = select_runtime_route(
                    task_kind="fix",
                    complexity_coeff=1.4,
                    prompt_len=120,
                    project_nodes=0,
                    sla_profile="balanced",
                    model_stats=stats,
                    quality_weight=0.4,
                    latency_weight=0.25,
                    token_cost_weight=0.2,
                    fail_rate_weight=0.15,
                    low_confidence_threshold=0.05,
                )
        finally:
            settings.triage_model = old_triage
            settings.analysis_model = old_analysis
            settings.patch_model = old_patch
            settings.llm_routing_threshold_low = old_low
            settings.llm_routing_threshold_mid = old_mid
            settings.llm_routing_threshold_high = old_high

        self.assertIsNotNone(selection)
        assert selection is not None
        self.assertEqual(selection.policy.verifier_effort, "high")

    def test_routing_weights_cache_fallbacks_to_settings_defaults(self) -> None:
        stats = self._tradeoff_stats()
        old_triage = settings.triage_model
        old_analysis = settings.analysis_model
        old_patch = settings.patch_model
        try:
            settings.triage_model = "gpt-5-mini|gpt-5.2-codex"
            settings.analysis_model = "gpt-5-mini|gpt-5.2-codex"
            settings.patch_model = "gpt-5-mini|gpt-5.2-codex"

            with patch("app.llm.routing_weights.cache_get_json", return_value=None):
                from_defaults = select_runtime_route(
                    task_kind="analyze",
                    complexity_coeff=1.2,
                    prompt_len=240,
                    project_nodes=200,
                    sla_profile="balanced",
                    model_stats=stats,
                    quality_weight=0.7,
                    latency_weight=0.1,
                    token_cost_weight=0.1,
                    fail_rate_weight=0.1,
                    low_confidence_threshold=0.01,
                )
            with patch(
                "app.llm.routing_weights.cache_get_json",
                return_value={
                    "weights": {"quality": -2, "latency": 1, "token_cost": 1, "fail_rate": 1}
                },
            ):
                from_invalid_cache = select_runtime_route(
                    task_kind="analyze",
                    complexity_coeff=1.2,
                    prompt_len=240,
                    project_nodes=200,
                    sla_profile="balanced",
                    model_stats=stats,
                    quality_weight=0.7,
                    latency_weight=0.1,
                    token_cost_weight=0.1,
                    fail_rate_weight=0.1,
                    low_confidence_threshold=0.01,
                )
        finally:
            settings.triage_model = old_triage
            settings.analysis_model = old_analysis
            settings.patch_model = old_patch

        self.assertIsNotNone(from_defaults)
        self.assertIsNotNone(from_invalid_cache)
        assert from_defaults is not None and from_invalid_cache is not None
        self.assertEqual(
            from_defaults.policy.analysis_model, from_invalid_cache.policy.analysis_model
        )

    def test_cache_calibrated_weights_change_ranking_and_breakdown(self) -> None:
        stats = self._tradeoff_stats()
        old_triage = settings.triage_model
        old_analysis = settings.analysis_model
        old_patch = settings.patch_model
        try:
            settings.triage_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
            settings.analysis_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
            settings.patch_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"

            with patch("app.llm.routing_weights.cache_get_json", return_value=None):
                default_selection = select_runtime_route(
                    task_kind="analyze",
                    complexity_coeff=1.1,
                    prompt_len=160,
                    project_nodes=30,
                    sla_profile="balanced",
                    model_stats=stats,
                    quality_weight=0.8,
                    latency_weight=0.08,
                    token_cost_weight=0.08,
                    fail_rate_weight=0.04,
                    low_confidence_threshold=0.01,
                )

            with patch(
                "app.llm.routing_weights.cache_get_json",
                return_value={
                    "weights": {
                        "quality": 0.05,
                        "latency": 0.55,
                        "token_cost": 0.3,
                        "fail_rate": 0.1,
                    }
                },
            ):
                cached_selection = select_runtime_route(
                    task_kind="analyze",
                    complexity_coeff=1.1,
                    prompt_len=160,
                    project_nodes=30,
                    sla_profile="balanced",
                    model_stats=stats,
                    quality_weight=0.8,
                    latency_weight=0.08,
                    token_cost_weight=0.08,
                    fail_rate_weight=0.04,
                    low_confidence_threshold=0.01,
                )
        finally:
            settings.triage_model = old_triage
            settings.analysis_model = old_analysis
            settings.patch_model = old_patch

        self.assertIsNotNone(default_selection)
        self.assertIsNotNone(cached_selection)
        assert default_selection is not None and cached_selection is not None
        self.assertNotEqual(
            default_selection.policy.analysis_model, cached_selection.policy.analysis_model
        )
        self.assertEqual(cached_selection.policy.analysis_model, "gpt-5-nano")
        self.assertGreater(
            cached_selection.score_breakdown["effective_weights"]["latency"],
            cached_selection.score_breakdown["effective_weights"]["quality"],
        )

    def test_sla_profiles_produce_distinct_rankings_with_cached_weights(self) -> None:
        stats = self._tradeoff_stats()
        old_triage = settings.triage_model
        old_analysis = settings.analysis_model
        old_patch = settings.patch_model
        try:
            settings.triage_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
            settings.analysis_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
            settings.patch_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"

            def _profiled_cache_payload(key: list[object]) -> dict[str, dict[str, float]]:
                profile = key[3] if len(key) > 3 else "balanced"
                if profile == "quality":
                    return {
                        "weights": {
                            "quality": 0.95,
                            "latency": 0.02,
                            "token_cost": 0.01,
                            "fail_rate": 0.02,
                        }
                    }
                if profile == "cheap":
                    return {
                        "weights": {
                            "quality": 0.1,
                            "latency": 0.2,
                            "token_cost": 0.6,
                            "fail_rate": 0.1,
                        }
                    }
                return {
                    "weights": {
                        "quality": 0.2,
                        "latency": 0.55,
                        "token_cost": 0.15,
                        "fail_rate": 0.1,
                    }
                }

            with patch(
                "app.llm.routing_weights.cache_get_json", side_effect=_profiled_cache_payload
            ):
                fast_selection = select_runtime_route(
                    task_kind="analyze",
                    complexity_coeff=1.1,
                    prompt_len=220,
                    project_nodes=10,
                    sla_profile="fast",
                    model_stats=stats,
                    quality_weight=0.35,
                    latency_weight=0.25,
                    token_cost_weight=0.25,
                    fail_rate_weight=0.15,
                    low_confidence_threshold=0.01,
                )
                cheap_selection = select_runtime_route(
                    task_kind="analyze",
                    complexity_coeff=1.1,
                    prompt_len=220,
                    project_nodes=10,
                    sla_profile="cheap",
                    model_stats=stats,
                    quality_weight=0.35,
                    latency_weight=0.25,
                    token_cost_weight=0.25,
                    fail_rate_weight=0.15,
                    low_confidence_threshold=0.01,
                )
                quality_selection = select_runtime_route(
                    task_kind="analyze",
                    complexity_coeff=1.1,
                    prompt_len=220,
                    project_nodes=10,
                    sla_profile="quality",
                    model_stats=stats,
                    quality_weight=0.35,
                    latency_weight=0.25,
                    token_cost_weight=0.25,
                    fail_rate_weight=0.15,
                    low_confidence_threshold=0.01,
                )
        finally:
            settings.triage_model = old_triage
            settings.analysis_model = old_analysis
            settings.patch_model = old_patch

        self.assertIsNotNone(fast_selection)
        self.assertIsNotNone(cheap_selection)
        self.assertIsNotNone(quality_selection)
        assert (
            fast_selection is not None
            and cheap_selection is not None
            and quality_selection is not None
        )
        self.assertEqual(fast_selection.policy.analysis_model, "gpt-5-nano")
        self.assertEqual(cheap_selection.policy.analysis_model, "gpt-5-nano")
        self.assertEqual(quality_selection.policy.analysis_model, "gpt-5.2-codex")
        self.assertGreater(
            quality_selection.score_breakdown["effective_weights"]["quality"],
            fast_selection.score_breakdown["effective_weights"]["quality"],
        )


if __name__ == "__main__":
    unittest.main()
