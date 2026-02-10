import json
import sys
import unittest
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.db import engine, get_session
from app.models import AnalysisRun, AnalysisStageTelemetry
from app.services.task_service import _append_stage_telemetry


class TestStageTelemetryStorage(unittest.TestCase):
    def setUp(self) -> None:
        if engine.dialect.name != "postgresql":
            self.skipTest("Postgres is required for stage telemetry persistence tests")
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            self.skipTest("Postgres is not available for stage telemetry persistence tests")

    def tearDown(self) -> None:
        with get_session() as session:
            session.exec(
                delete(AnalysisStageTelemetry).where(AnalysisStageTelemetry.org_id == 9201)
            )
            session.exec(delete(AnalysisRun).where(AnalysisRun.org_id == 9201))
            session.commit()

    def test_stage_telemetry_payload_shape(self) -> None:
        stages: list[dict] = []
        _append_stage_telemetry(
            stages,
            stage_name="analyze_agentic",
            model="gpt-5-mini",
            latency_ms=123.4,
            retry_index=1,
            self_check_result="ok",
            failure_class=None,
            stop_reason="completed",
            tool_calls=5,
            tool_output_chars=2048,
        )
        self.assertEqual(len(stages), 1)
        row = stages[0]
        self.assertEqual(row["stage_name"], "analyze_agentic")
        self.assertEqual(row["model"], "gpt-5-mini")
        self.assertIsNone(row["prompt_tokens"])
        self.assertIsNone(row["completion_tokens"])
        self.assertEqual(row["latency_ms"], 123)
        self.assertEqual(row["retry_index"], 1)
        self.assertEqual(row["self_check_result"], "ok")
        self.assertIsNone(row["failure_class"])
        self.assertEqual(row["stop_reason"], "completed")
        self.assertEqual(row["tool_calls"], 5)
        self.assertEqual(row["tool_output_chars"], 2048)

    def test_stage_telemetry_persistence(self) -> None:
        retrieval_settings = {
            "agentic": {"model_routing": {"analysis_model": "gpt-5-mini"}},
            "telemetry": {
                "stages": [
                    {
                        "stage_name": "plan_agentic",
                        "model": "gpt-5-mini",
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "latency_ms": 42,
                        "retry_index": 0,
                        "self_check_result": None,
                        "failure_class": None,
                        "stop_reason": "completed",
                        "tool_calls": None,
                        "tool_output_chars": None,
                    }
                ]
            },
        }

        with get_session() as session:
            run = AnalysisRun(
                org_id=9201,
                project_id=9201,
                target_path="a.py",
                mode="analyze",
                prompt="prompt",
                model_used="gpt-5-mini",
                retrieval="agentic",
                retrieval_settings_json=json.dumps(retrieval_settings, ensure_ascii=False),
                result_json=json.dumps({"ok": True}, ensure_ascii=False),
            )
            session.add(run)
            session.flush()
            session.add(
                AnalysisStageTelemetry(
                    run_id=int(run.id or 0),
                    org_id=9201,
                    project_id=9201,
                    stage_name="plan_agentic",
                    model="gpt-5-mini",
                    latency_ms=42,
                    retry_index=0,
                    stop_reason="completed",
                )
            )
            session.commit()

        with get_session() as session:
            run = session.exec(select(AnalysisRun).where(AnalysisRun.org_id == 9201)).first()
            self.assertIsNotNone(run)
            data = json.loads((run.retrieval_settings_json if run else "") or "{}")
            self.assertTrue(isinstance(data.get("telemetry"), dict))
            self.assertEqual(data["telemetry"]["stages"][0]["stage_name"], "plan_agentic")

            stages = session.exec(
                select(AnalysisStageTelemetry).where(AnalysisStageTelemetry.org_id == 9201)
            ).all()
            self.assertEqual(len(stages), 1)
            self.assertEqual(stages[0].stage_name, "plan_agentic")
            self.assertEqual(stages[0].latency_ms, 42)
            self.assertEqual(stages[0].stop_reason, "completed")


if __name__ == "__main__":
    unittest.main()
