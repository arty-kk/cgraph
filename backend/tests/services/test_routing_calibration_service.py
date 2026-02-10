import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.models import AnalysisStageTelemetry
from app.services.routing_calibration_service import (
    _derive_base_weights,
    _derive_thresholds,
    _profile_transform,
    _validate_and_normalize_weights,
)


class TestRoutingCalibrationService(unittest.TestCase):
    def test_derive_thresholds_no_data_returns_defaults(self) -> None:
        defaults = (1.35, 1.5, 1.7)
        got = _derive_thresholds(defaults=defaults, rows=[])
        self.assertEqual(got, defaults)

    def test_derive_thresholds_shifts_on_quality_pressure(self) -> None:
        defaults = (1.35, 1.5, 1.7)
        rows: list[AnalysisStageTelemetry] = []
        for i in range(30):
            rows.append(
                AnalysisStageTelemetry(
                    run_id=i + 1,
                    org_id=1,
                    project_id=1,
                    stage_name="analyze_agentic",
                    model="gpt-5-mini",
                    latency_ms=5000,
                    retry_index=1 if i % 3 == 0 else 0,
                    self_check_result="failed" if i % 4 == 0 else "ok",
                    failure_class="RuntimeError" if i % 5 == 0 else None,
                )
            )

        low, mid, high = _derive_thresholds(defaults=defaults, rows=rows)
        self.assertTrue(1.0 <= low <= mid <= high <= 2.0)
        self.assertGreaterEqual(mid, defaults[1])

    def test_derive_base_weights_normalized_and_non_negative(self) -> None:
        defaults = {"quality": 0.4, "latency": 0.25, "token_cost": 0.2, "fail_rate": 0.15}
        rows: list[AnalysisStageTelemetry] = []
        for i in range(40):
            rows.append(
                AnalysisStageTelemetry(
                    run_id=i + 1,
                    org_id=1,
                    project_id=1,
                    stage_name="analyze_agentic",
                    model="gpt-5-mini",
                    latency_ms=3000 + i * 20,
                    prompt_tokens=1200 + i * 10,
                    completion_tokens=500 + i * 8,
                    retry_index=1 if i % 3 == 0 else 0,
                    self_check_result="failed" if i % 5 == 0 else "ok",
                    failure_class="TimeoutError" if i % 7 == 0 else None,
                )
            )

        weights = _derive_base_weights(defaults=defaults, rows=rows)
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=5)
        self.assertTrue(all(value >= 0 for value in weights.values()))
        self.assertGreater(weights["latency"], 0.2)
        self.assertGreater(weights["token_cost"], 0.15)

    def test_profile_transform_and_normalization_for_all_sla_profiles(self) -> None:
        base_weights = {"quality": 0.35, "latency": 0.25, "token_cost": 0.25, "fail_rate": 0.15}

        fast = _validate_and_normalize_weights(_profile_transform(base_weights, sla_profile="fast"))
        cheap = _validate_and_normalize_weights(
            _profile_transform(base_weights, sla_profile="cheap")
        )
        quality = _validate_and_normalize_weights(
            _profile_transform(base_weights, sla_profile="quality")
        )

        self.assertIsNotNone(fast)
        self.assertIsNotNone(cheap)
        self.assertIsNotNone(quality)
        assert fast is not None and cheap is not None and quality is not None
        self.assertAlmostEqual(sum(fast.values()), 1.0, places=5)
        self.assertAlmostEqual(sum(cheap.values()), 1.0, places=5)
        self.assertAlmostEqual(sum(quality.values()), 1.0, places=5)
        self.assertGreater(fast["latency"], quality["latency"])
        self.assertGreater(cheap["token_cost"], fast["token_cost"])
        self.assertGreater(quality["quality"], cheap["quality"])


if __name__ == "__main__":
    unittest.main()
