from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..infra.cache import cache_set_json
from ..logging import get_logger
from ..models import AnalysisStageTelemetry

logger = get_logger("stubgraph.routing_calibration")
_SLA_PROFILES = ("balanced", "fast", "cheap", "quality")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _derive_thresholds(
    *, defaults: tuple[float, float, float], rows: list[AnalysisStageTelemetry]
) -> tuple[float, float, float]:
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


def _validate_and_normalize_weights(weights: dict[str, float]) -> dict[str, float] | None:
    normalized: dict[str, float] = {}
    for key in ("quality", "latency", "token_cost", "fail_rate"):
        try:
            value = float(weights[key])
        except (KeyError, TypeError, ValueError):
            return None
        if value < 0:
            return None
        normalized[key] = value

    total = sum(normalized.values())
    if total <= 0:
        return None
    return {key: round(value / total, 6) for key, value in normalized.items()}


def _profile_transform(base_weights: dict[str, float], *, sla_profile: str) -> dict[str, float]:
    weights = dict(base_weights)
    if sla_profile == "fast":
        weights["latency"] *= 1.35
        weights["token_cost"] *= 0.9
    elif sla_profile == "cheap":
        weights["token_cost"] *= 1.4
        weights["quality"] *= 0.9
    elif sla_profile == "quality":
        weights["quality"] *= 1.4
        weights["latency"] *= 0.9
    return weights


def _derive_base_weights(
    *, defaults: dict[str, float], rows: list[AnalysisStageTelemetry]
) -> dict[str, float]:
    default_weights = _validate_and_normalize_weights(defaults)
    if default_weights is None:
        default_weights = {"quality": 0.4, "latency": 0.25, "token_cost": 0.2, "fail_rate": 0.15}
    if not rows:
        return default_weights

    samples = len(rows)
    failure_score = 0.0
    retry_score = 0.0
    self_check_failed = 0
    latency_values: list[int] = []
    token_values: list[int] = []

    for row in rows:
        failure_class = str(row.failure_class or "").strip().lower()
        if failure_class:
            if any(tag in failure_class for tag in ("timeout", "overload", "rate", "unavailable")):
                failure_score += 1.0
            else:
                failure_score += 0.8
        retry_score += min(2.0, max(0.0, float(int(row.retry_index or 0)) * 0.5))
        if row.self_check_result == "failed":
            self_check_failed += 1
        if isinstance(row.latency_ms, int) and row.latency_ms >= 0:
            latency_values.append(row.latency_ms)
        prompt_tokens = max(0, int(row.prompt_tokens or 0))
        completion_tokens = max(0, int(row.completion_tokens or 0))
        token_values.append(prompt_tokens + completion_tokens)

    latency_values.sort()
    token_values.sort()
    p95_latency = (
        latency_values[min(len(latency_values) - 1, int(round((len(latency_values) - 1) * 0.95)))]
        if latency_values
        else 0
    )
    p75_tokens = (
        token_values[min(len(token_values) - 1, int(round((len(token_values) - 1) * 0.75)))]
        if token_values
        else 0
    )

    failure_rate = _clamp(failure_score / max(1, samples), 0.0, 1.0)
    retry_rate = _clamp(retry_score / max(1, samples), 0.0, 1.0)
    self_check_rate = _clamp(self_check_failed / max(1, samples), 0.0, 1.0)
    quality_pressure = _clamp(
        0.5 * failure_rate + 0.3 * self_check_rate + 0.2 * retry_rate, 0.0, 1.0
    )
    fail_rate_pressure = _clamp(0.65 * failure_rate + 0.35 * retry_rate, 0.0, 1.0)
    latency_pressure = _clamp((p95_latency - 2000) / 8000, 0.0, 1.0)
    token_pressure = _clamp((p75_tokens - 2000) / 8000, 0.0, 1.0)

    raw = {
        "quality": max(
            0.0,
            default_weights["quality"]
            + 0.20 * quality_pressure
            - 0.05 * ((latency_pressure + token_pressure) / 2.0),
        ),
        "latency": max(
            0.0, default_weights["latency"] + 0.22 * latency_pressure - 0.04 * quality_pressure
        ),
        "token_cost": max(
            0.0, default_weights["token_cost"] + 0.22 * token_pressure - 0.03 * quality_pressure
        ),
        "fail_rate": max(0.0, default_weights["fail_rate"] + 0.18 * fail_rate_pressure),
    }
    return _validate_and_normalize_weights(raw) or default_weights


def calibrate_routing_policy_thresholds() -> dict[str, object]:
    if not bool(settings.llm_routing_calibration_enabled):
        return {"updated": False, "reason": "disabled"}

    defaults = (
        float(settings.llm_routing_threshold_low),
        float(settings.llm_routing_threshold_mid),
        float(settings.llm_routing_threshold_high),
    )
    default_weights = {
        "quality": float(settings.llm_routing_weight_quality),
        "latency": float(settings.llm_routing_weight_latency),
        "token_cost": float(settings.llm_routing_weight_token_cost),
        "fail_rate": float(settings.llm_routing_weight_fail_rate),
    }

    with get_session() as session:
        rows = session.exec(
            select(AnalysisStageTelemetry)
            .where(
                AnalysisStageTelemetry.stage_name.in_(
                    [
                        "analyze_agentic",
                        "evolve_agentic",
                        "fix_agentic",
                        "analyze_pack",
                        "evolve_pack",
                        "fix_pack",
                    ]
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
    thresholds_payload = {
        "version": settings.llm_routing_policy_version,
        "low": low,
        "mid": mid,
        "high": high,
        "samples": len(rows),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_set_json(
        ["routing_policy", "thresholds", settings.llm_routing_policy_version], thresholds_payload
    )

    base_weights = _derive_base_weights(defaults=default_weights, rows=rows)
    calibrated_weights_by_profile: dict[str, dict[str, float]] = {}
    for sla_profile in _SLA_PROFILES:
        profile_weights = _validate_and_normalize_weights(
            _profile_transform(base_weights, sla_profile=sla_profile)
        )
        if profile_weights is None:
            continue
        calibrated_weights_by_profile[sla_profile] = profile_weights
        weight_payload = {
            "version": settings.llm_routing_policy_version,
            "policy_version": settings.llm_routing_policy_version,
            "sla_profile": sla_profile,
            "weights": profile_weights,
            "samples": len(rows),
            "updated_at": thresholds_payload["updated_at"],
        }
        cache_set_json(
            ["routing_policy", "weights", settings.llm_routing_policy_version, sla_profile],
            weight_payload,
        )
        logger.info("Routing policy weights calibrated", extra=weight_payload)

    logger.info("Routing policy thresholds calibrated", extra=thresholds_payload)
    return {"updated": True, **thresholds_payload, "weights": calibrated_weights_by_profile}
