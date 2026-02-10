from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import settings
from .policy import ModelPolicy
from .routing_thresholds import resolve_routing_thresholds
from .routing_weights import resolve_routing_weights


@dataclass(frozen=True)
class RoutingSelection:
    policy: ModelPolicy
    confidence: float
    reason: str
    score_breakdown: dict[str, object]


def _parse_pool(value: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[|,]", str(value or ""))]
    return [p for p in parts if p]


def _normalize_metric(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _effective_weights(
    *,
    sla_profile: str,
    quality_weight: float,
    latency_weight: float,
    token_cost_weight: float,
    fail_rate_weight: float,
) -> dict[str, float]:
    profile = (sla_profile or "balanced").strip().lower()
    weights = {
        "quality": max(0.0, float(quality_weight)),
        "latency": max(0.0, float(latency_weight)),
        "token_cost": max(0.0, float(token_cost_weight)),
        "fail_rate": max(0.0, float(fail_rate_weight)),
    }
    if profile == "fast":
        weights["latency"] *= 1.35
        weights["token_cost"] *= 0.9
    elif profile == "cheap":
        weights["token_cost"] *= 1.4
        weights["quality"] *= 0.9
    elif profile == "quality":
        weights["quality"] *= 1.4
        weights["latency"] *= 0.9

    total = sum(weights.values())
    if total <= 0:
        return {"quality": 0.4, "latency": 0.25, "token_cost": 0.2, "fail_rate": 0.15}
    return {k: v / total for k, v in weights.items()}


def _score_model(
    model: str,
    stats: dict[str, dict[str, float]],
    *,
    complexity_coeff: float,
    prompt_len: int,
    quality_weight: float,
    latency_weight: float,
    token_cost_weight: float,
    fail_rate_weight: float,
) -> tuple[float, dict[str, float]] | None:
    row = stats.get(model)
    if not isinstance(row, dict):
        return None

    try:
        quality = float(row["quality"])
        latency_ms = float(row["latency_ms"])
        token_cost = float(row["token_cost"])
        fail_rate = float(row["fail_rate"])
    except Exception:
        return None

    all_latency = [float(v.get("latency_ms", 0.0)) for v in stats.values() if isinstance(v, dict)]
    all_cost = [float(v.get("token_cost", 0.0)) for v in stats.values() if isinstance(v, dict)]

    latency_norm = _normalize_metric(
        latency_ms,
        min(all_latency or [latency_ms]),
        max(all_latency or [latency_ms]),
    )
    token_norm = _normalize_metric(
        token_cost,
        min(all_cost or [token_cost]),
        max(all_cost or [token_cost]),
    )
    fail_norm = max(0.0, min(1.0, fail_rate))
    quality_norm = max(0.0, min(1.0, quality))

    complexity_bonus = max(0.0, min(0.2, (float(complexity_coeff) - 1.0) * 0.2))
    prompt_bonus = max(0.0, min(0.1, prompt_len / max(1, int(settings.max_prompt_chars)) * 0.1))

    breakdown = {
        "quality": quality_norm * quality_weight,
        "latency": (1.0 - latency_norm) * latency_weight,
        "token_cost": (1.0 - token_norm) * token_cost_weight,
        "fail_rate": (1.0 - fail_norm) * fail_rate_weight,
        "complexity_bonus": complexity_bonus,
        "prompt_bonus": prompt_bonus,
    }
    return sum(breakdown.values()), breakdown


def _pick_stage_model(
    *,
    stage_name: str,
    pool_value: str,
    stats: dict[str, dict[str, float]],
    complexity_coeff: float,
    prompt_len: int,
    quality_weight: float,
    latency_weight: float,
    token_cost_weight: float,
    fail_rate_weight: float,
) -> tuple[str, float, dict[str, object]] | None:
    pool = _parse_pool(pool_value)
    if not pool:
        return None

    ranked: list[tuple[str, float, dict[str, float]]] = []
    for candidate in pool:
        scored = _score_model(
            candidate,
            stats,
            complexity_coeff=complexity_coeff,
            prompt_len=prompt_len,
            quality_weight=quality_weight,
            latency_weight=latency_weight,
            token_cost_weight=token_cost_weight,
            fail_rate_weight=fail_rate_weight,
        )
        if scored is None:
            continue
        value, breakdown = scored
        ranked.append((candidate, value, breakdown))

    if not ranked:
        return None

    ranked.sort(key=lambda item: item[1], reverse=True)
    best_model, best_score, best_breakdown = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else max(0.0, best_score - 0.05)
    confidence = max(0.0, min(1.0, 0.5 + (best_score - second_score)))
    return best_model, confidence, {
        "stage": stage_name,
        "selected": best_model,
        "selected_score": best_score,
        "selected_score_breakdown": best_breakdown,
        "candidates": [
            {
                "model": model,
                "score": score,
                "score_breakdown": breakdown,
            }
            for model, score, breakdown in ranked
        ],
    }


def select_runtime_route(
    *,
    task_kind: str | None,
    complexity_coeff: float,
    prompt_len: int,
    project_nodes: int,
    sla_profile: str,
    model_stats: dict[str, dict[str, float]] | None,
    quality_weight: float,
    latency_weight: float,
    token_cost_weight: float,
    fail_rate_weight: float,
    low_confidence_threshold: float,
) -> RoutingSelection | None:
    if not isinstance(model_stats, dict) or not model_stats:
        return None

    resolved_weights = resolve_routing_weights(
        sla_profile,
        {
            "quality": quality_weight,
            "latency": latency_weight,
            "token_cost": token_cost_weight,
            "fail_rate": fail_rate_weight,
        },
    )
    weights = _effective_weights(
        sla_profile=sla_profile,
        quality_weight=resolved_weights["quality"],
        latency_weight=resolved_weights["latency"],
        token_cost_weight=resolved_weights["token_cost"],
        fail_rate_weight=resolved_weights["fail_rate"],
    )

    threshold_low, threshold_mid, threshold_high = resolve_routing_thresholds()

    eff_complexity = max(1.0, min(2.0, float(complexity_coeff) + min(0.2, project_nodes / 10000.0)))
    if task_kind == "fix":
        eff_complexity = max(1.0, min(2.0, eff_complexity + 0.1))

    triage_pick = _pick_stage_model(
        stage_name="triage",
        pool_value=settings.triage_model,
        stats=model_stats,
        complexity_coeff=eff_complexity,
        prompt_len=prompt_len,
        quality_weight=weights["quality"],
        latency_weight=weights["latency"],
        token_cost_weight=weights["token_cost"],
        fail_rate_weight=weights["fail_rate"],
    )
    analysis_pick = _pick_stage_model(
        stage_name="analysis",
        pool_value=settings.analysis_model,
        stats=model_stats,
        complexity_coeff=eff_complexity,
        prompt_len=prompt_len,
        quality_weight=weights["quality"],
        latency_weight=weights["latency"],
        token_cost_weight=weights["token_cost"],
        fail_rate_weight=weights["fail_rate"],
    )
    patch_pick = _pick_stage_model(
        stage_name="patch",
        pool_value=settings.patch_model,
        stats=model_stats,
        complexity_coeff=eff_complexity,
        prompt_len=prompt_len,
        quality_weight=weights["quality"],
        latency_weight=weights["latency"],
        token_cost_weight=weights["token_cost"],
        fail_rate_weight=weights["fail_rate"],
    )

    verifier_edge_case = bool(
        task_kind == "fix" and (eff_complexity >= threshold_high or prompt_len >= 6000)
    )
    verifier_complexity = max(
        1.0,
        min(2.0, eff_complexity if verifier_edge_case else min(threshold_mid, eff_complexity)),
    )
    verifier_weights = dict(weights)
    if not verifier_edge_case:
        verifier_weights["latency"] *= 1.15
        verifier_weights["token_cost"] *= 1.1
        total = sum(verifier_weights.values())
        verifier_weights = {k: (v / total if total > 0 else v) for k, v in verifier_weights.items()}
    verifier_pick = _pick_stage_model(
        stage_name="verifier",
        pool_value=settings.analysis_model,
        stats=model_stats,
        complexity_coeff=verifier_complexity,
        prompt_len=prompt_len,
        quality_weight=verifier_weights["quality"],
        latency_weight=verifier_weights["latency"],
        token_cost_weight=verifier_weights["token_cost"],
        fail_rate_weight=verifier_weights["fail_rate"],
    )

    if triage_pick is None or analysis_pick is None or patch_pick is None or verifier_pick is None:
        return None

    confidence = min(triage_pick[1], analysis_pick[1], patch_pick[1], verifier_pick[1])
    if confidence < max(0.0, min(1.0, float(low_confidence_threshold))):
        return None

    policy = ModelPolicy(
        triage_model=triage_pick[0],
        analysis_model=analysis_pick[0],
        patch_model=patch_pick[0],
        verifier_model=verifier_pick[0],
        triage_effort=settings.reasoning_effort_triage,
        analysis_effort=settings.reasoning_effort_analysis,
        patch_effort=settings.reasoning_effort_patch,
        verifier_effort="high" if verifier_edge_case else "medium",
    )

    return RoutingSelection(
        policy=policy,
        confidence=confidence,
        reason="telemetry_score",
        score_breakdown={
            "policy_version": settings.llm_routing_policy_version,
            "sla_profile": (sla_profile or "balanced").strip().lower(),
            "effective_weights": weights,
            "effective_complexity": eff_complexity,
            "stages": [triage_pick[2], analysis_pick[2], patch_pick[2], verifier_pick[2]],
            "verifier_edge_case": verifier_edge_case,
        },
    )
