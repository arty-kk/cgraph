import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings
from app.llm.policy import _parse_model_pool, resolve_runtime_policy


class TestRuntimePolicy(unittest.TestCase):
    def test_parse_model_pool(self) -> None:
        self.assertEqual(_parse_model_pool("gpt-5-nano"), ["gpt-5-nano"])
        self.assertEqual(
            _parse_model_pool("gpt-5-nano|gpt-5-mini, gpt-5.2-codex"),
            ["gpt-5-nano", "gpt-5-mini", "gpt-5.2-codex"],
        )

    def test_runtime_policy_uses_single_models_without_pool(self) -> None:
        policy = resolve_runtime_policy(task_kind="analyze", complexity_coeff=1.0, prompt_len=10)
        self.assertTrue(isinstance(policy.triage_model, str) and policy.triage_model)
        self.assertTrue(isinstance(policy.analysis_model, str) and policy.analysis_model)
        self.assertTrue(isinstance(policy.patch_model, str) and policy.patch_model)
        self.assertTrue(isinstance(policy.verifier_model, str) and policy.verifier_model)
        self.assertIn(policy.verifier_effort, ("low", "medium", "high"))

    def test_runtime_policy_selects_higher_tier_for_higher_complexity(self) -> None:
        old_triage = settings.triage_model
        old_analysis = settings.analysis_model
        old_patch = settings.patch_model
        try:
            settings.triage_model = "gpt-5-nano|gpt-5-mini"
            settings.analysis_model = "gpt-5-nano|gpt-5-mini|gpt-5.2-codex"
            settings.patch_model = "gpt-5-mini|gpt-5.2-codex"

            low = resolve_runtime_policy(task_kind="analyze", complexity_coeff=1.0, prompt_len=10)
            high = resolve_runtime_policy(task_kind="fix", complexity_coeff=1.9, prompt_len=5000)

            self.assertEqual(low.analysis_model, "gpt-5-nano")
            self.assertEqual(high.analysis_model, "gpt-5.2-codex")
            self.assertEqual(low.patch_model, "gpt-5-mini")
            self.assertEqual(high.patch_model, "gpt-5.2-codex")
            self.assertEqual(low.verifier_model, "gpt-5-nano")
            self.assertIn(high.verifier_model, ("gpt-5-mini", "gpt-5.2-codex"))
            self.assertEqual(high.verifier_effort, "high")
        finally:
            settings.triage_model = old_triage
            settings.analysis_model = old_analysis
            settings.patch_model = old_patch


    def test_runtime_policy_uses_configurable_thresholds(self) -> None:
        old_analysis = settings.analysis_model
        old_low = settings.llm_routing_threshold_low
        old_mid = settings.llm_routing_threshold_mid
        old_high = settings.llm_routing_threshold_high
        try:
            settings.analysis_model = "gpt-5-nano|gpt-5-mini"
            settings.llm_routing_threshold_low = 1.2
            settings.llm_routing_threshold_mid = 1.8
            settings.llm_routing_threshold_high = 1.9

            low = resolve_runtime_policy(task_kind="analyze", complexity_coeff=1.5, prompt_len=100)
            high = resolve_runtime_policy(task_kind="analyze", complexity_coeff=1.9, prompt_len=100)

            self.assertEqual(low.analysis_model, "gpt-5-nano")
            self.assertEqual(high.analysis_model, "gpt-5-mini")
        finally:
            settings.analysis_model = old_analysis
            settings.llm_routing_threshold_low = old_low
            settings.llm_routing_threshold_mid = old_mid
            settings.llm_routing_threshold_high = old_high

if __name__ == "__main__":
    unittest.main()
