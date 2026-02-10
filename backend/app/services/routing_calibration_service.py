from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..infra.cache import cache_set_json
from ..logging import get_logger
from ..models import AnalysisStageTelemetry

logger = get_logger("stubgraph.routing_calibration")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _derive_thresholds(*, defaults: tuple[float, float, float], rows: list[AnalysisStageTelemetry]) -> tuple[float, float, float]:
    low_default, mid_default, high_default = defaults
    if not rows:
        return defaults

    samples = len(rows)
    failure_count = 0
    retry_count = 0
    self_check_failed = 0
    latency_values: list[int] = []

    for row in rows:
        if isinstance(row.failure_class, str) and row.failure_class:
            failure_count += 1
        if int(row.retry_index or 0) > 0:
            retry_count += 1
        if row.self_check_result == "failed":
            self_check_failed += 1
        if isinstance(row.latency_ms, int) and row.latency_ms >= 0:
            latency_values.append(row.latency_ms)

    quality_pressure = (failure_count + retry_count + self_check_failed) / max(1, samples)
    p95_latency = 0
    if latency_values:
        latency_values.sort()
        idx = int(round((len(latency_values) - 1) * 0.95))
        p95_latency = latency_values[max(0, min(len(latency_values) - 1, idx))]
    latency_pressure = _clamp((p95_latency - 4000) / 6000, 0.0, 1.0)

    low = low_default + 0.08 * quality_pressure - 0.04 * latency_pressure
    mid = mid_default + 0.10 * quality_pressure - 0.06 * latency_pressure
    high = high_default + 0.12 * quality_pressure - 0.08 * latency_pressure

    low = _clamp(low, 1.0, 2.0)
    mid = _clamp(mid, max(1.0, low), 2.0)
    high = _clamp(high, max(mid, 1.0), 2.0)

    return (round(low, 4), round(mid, 4), round(high, 4))


def calibrate_routing_policy_thresholds() -> dict[str, object]:
    if not bool(settings.llm_routing_calibration_enabled):
        return {"updated": False, "reason": "disabled"}

    defaults = (
        float(settings.llm_routing_threshold_low),
        float(settings.llm_routing_threshold_mid),
        float(settings.llm_routing_threshold_high),
    )

    with get_session() as session:
        rows = session.exec(
            select(AnalysisStageTelemetry)
            .where(
                AnalysisStageTelemetry.stage_name.in_(
                    ["analyze_agentic", "evolve_agentic", "fix_agentic", "analyze_pack", "evolve_pack", "fix_pack"]
                )
            )
            .order_by(AnalysisStageTelemetry.id.desc())
            .limit(max(2000, int(settings.llm_routing_calibration_min_samples) * 2))
        ).all()

    if len(rows) < int(settings.llm_routing_calibration_min_samples):
        return {
            "updated": False,
            "reason": "insufficient_samples",
            "samples": len(rows),
            "min_samples": int(settings.llm_routing_calibration_min_samples),
        }

    low, mid, high = _derive_thresholds(defaults=defaults, rows=rows)
    payload = {
        "version": settings.llm_routing_policy_version,
        "low": low,
        "mid": mid,
        "high": high,
        "samples": len(rows),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_set_json(["routing_policy", "thresholds", settings.llm_routing_policy_version], payload)
    logger.info("Routing policy thresholds calibrated", extra=payload)
    return {"updated": True, **payload}
