import json
import sys
from pathlib import Path

import pytest
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal, async_engine
from app.models import AnalysisRun, AnalysisStageTelemetry
from app.services.task_service import _append_stage_telemetry
from tests.services.db_helpers import ensure_async_postgres


def test_stage_telemetry_payload_shape() -> None:
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
        prompt_tokens=321,
        completion_tokens=123,
    )
    assert len(stages) == 1
    row = stages[0]
    assert row["stage_name"] == "analyze_agentic"
    assert row["model"] == "gpt-5-mini"
    assert row["prompt_tokens"] == 321
    assert row["completion_tokens"] == 123
    assert row["latency_ms"] == 123
    assert row["retry_index"] == 1
    assert row["self_check_result"] == "ok"
    assert row["failure_class"] is None
    assert row["stop_reason"] == "completed"
    assert row["tool_calls"] == 5
    assert row["tool_output_chars"] == 2048


@pytest.mark.anyio
async def test_stage_telemetry_persistence(ensure_async_postgres) -> None:
    if async_engine.sync_engine.dialect.name != "postgresql":
        pytest.skip("Postgres is required for stage telemetry persistence tests")

    org_id = 9201
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisStageTelemetry).where(AnalysisStageTelemetry.org_id == org_id))
        await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
        await session.commit()

    retrieval_settings = {
        "agentic": {"model_routing": {"analysis_model": "gpt-5-mini"}},
        "telemetry": {
            "stages": [
                {
                    "stage_name": "plan_agentic",
                    "model": "gpt-5-mini",
                    "prompt_tokens": 555,
                    "completion_tokens": 111,
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

    try:
        async with AsyncSessionLocal() as session:
            run = AnalysisRun(
                org_id=org_id,
                project_id=org_id,
                target_path="a.py",
                mode="analyze",
                prompt="prompt",
                model_used="gpt-5-mini",
                retrieval="agentic",
                retrieval_settings_json=json.dumps(retrieval_settings, ensure_ascii=False),
                result_json=json.dumps({"ok": True}, ensure_ascii=False),
            )
            session.add(run)
            await session.flush()
            session.add(
                AnalysisStageTelemetry(
                    run_id=int(run.id or 0),
                    org_id=org_id,
                    project_id=org_id,
                    stage_name="plan_agentic",
                    model="gpt-5-mini",
                    prompt_tokens=555,
                    completion_tokens=111,
                    latency_ms=42,
                    retry_index=0,
                    stop_reason="completed",
                )
            )
            await session.commit()

        async with AsyncSessionLocal() as session:
            run = ((await session.execute(select(AnalysisRun).where(AnalysisRun.org_id == org_id))).scalars().first())
            assert run is not None
            data = json.loads((run.retrieval_settings_json if run else "") or "{}")
            assert isinstance(data.get("telemetry"), dict)
            assert data["telemetry"]["stages"][0]["stage_name"] == "plan_agentic"

            stages = (
                (await session.execute(select(AnalysisStageTelemetry).where(AnalysisStageTelemetry.org_id == org_id)))
                .scalars()
                .all()
            )
            assert len(stages) == 1
            assert stages[0].stage_name == "plan_agentic"
            assert stages[0].latency_ms == 42
            assert stages[0].stop_reason == "completed"
            assert stages[0].prompt_tokens == 555
            assert stages[0].completion_tokens == 111
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AnalysisStageTelemetry).where(AnalysisStageTelemetry.org_id == org_id))
            await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
            await session.commit()
