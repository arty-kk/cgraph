import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.models import AnalysisStageTelemetry
from app.services.routing_calibration_service import _derive_thresholds


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


if __name__ == "__main__":
    unittest.main()
