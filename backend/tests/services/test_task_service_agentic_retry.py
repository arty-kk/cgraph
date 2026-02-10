import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services.task_service import (  # noqa: E402
    _append_stage_telemetry,
    _resolve_agentic_retry_stop_reason,
)


def test_agentic_retry_limit_stop_reason() -> None:
    stop_reason = _resolve_agentic_retry_stop_reason(
        retry_index=1,
        retry_limit=1,
        previous_missing_context=["A"],
        current_missing_context=["A"],
        stability_threshold=0.9,
        stage_name="analyze_agentic",
        escalation_count_by_stage={"analyze_agentic": 0},
        escalation_limit=1,
    )
    assert stop_reason == "retry_limit"


def test_agentic_repeating_missing_context_stop_reason() -> None:
    stop_reason = _resolve_agentic_retry_stop_reason(
        retry_index=0,
        retry_limit=2,
        previous_missing_context=["  Missing  API ", "No schema"],
        current_missing_context=["missing api", "no   schema"],
        stability_threshold=0.95,
        stage_name="evolve_agentic",
        escalation_count_by_stage={"evolve_agentic": 0},
        escalation_limit=2,
    )
    assert stop_reason == "repeating_missing_context"


def test_agentic_escalation_limit_stop_reason() -> None:
    stop_reason = _resolve_agentic_retry_stop_reason(
        retry_index=0,
        retry_limit=2,
        previous_missing_context=["context one"],
        current_missing_context=["context two"],
        stability_threshold=0.95,
        stage_name="fix_agentic",
        escalation_count_by_stage={"fix_agentic": 1},
        escalation_limit=1,
    )
    assert stop_reason == "escalation_limit"


def test_agentic_telemetry_and_state_payload_contains_stop_reason_and_counters() -> None:
    retrieval_settings = {
        "agentic": {
            "retry_count": 1,
            "retry_limit": 2,
            "escalation_count_by_stage": {"analyze_agentic": 1},
            "stop_reason": "retry_limit",
        }
    }

    stages: list[dict] = []
    _append_stage_telemetry(
        stages,
        stage_name="analyze_agentic",
        model="gpt-5-mini",
        latency_ms=50,
        retry_index=1,
        stop_reason="retry_limit",
    )

    assert retrieval_settings["agentic"]["retry_count"] == 1
    assert retrieval_settings["agentic"]["retry_limit"] == 2
    assert retrieval_settings["agentic"]["escalation_count_by_stage"]["analyze_agentic"] == 1
    assert retrieval_settings["agentic"]["stop_reason"] == "retry_limit"
    assert stages[0]["stop_reason"] == "retry_limit"
