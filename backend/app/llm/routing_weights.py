"""Resolve calibrated routing weights from cache with strict fallback behavior."""

from __future__ import annotations

from ..config import settings
from ..errors import ExternalServiceError
from ..infra.cache import cache_get_json_async

_ALLOWED_SLA_PROFILES = {"balanced", "fast", "cheap", "quality"}


def _normalize_sla_profile(sla_profile: str | None) -> str:
    profile = (sla_profile or "balanced").strip().lower()
    return profile if profile in _ALLOWED_SLA_PROFILES else "balanced"


def _validate_and_normalize_weights(weights: dict[str, float]) -> dict[str, float] | None:
    parsed: dict[str, float] = {}
    for key in ("quality", "latency", "token_cost", "fail_rate"):
        try:
            value = float(weights[key])
        except (KeyError, TypeError, ValueError):
            return None
        if value < 0:
            return None
        parsed[key] = value

    total = sum(parsed.values())
    if total <= 0:
        return None
    return {key: parsed[key] / total for key in parsed}


async def resolve_routing_weights_async(
    sla_profile: str | None, defaults: dict[str, float]
) -> dict[str, float]:
    fallback = _validate_and_normalize_weights(defaults)
    if fallback is None:
        fallback = {"quality": 0.4, "latency": 0.25, "token_cost": 0.2, "fail_rate": 0.15}

    normalized_sla_profile = _normalize_sla_profile(sla_profile)
    try:
        cached = await cache_get_json_async(
            [
                "routing_policy",
                "weights",
                settings.llm_routing_policy_version,
                normalized_sla_profile,
            ]
        )
    except ExternalServiceError:
        return fallback
    if not isinstance(cached, dict):
        return fallback

    payload = cached.get("weights") if isinstance(cached.get("weights"), dict) else cached
    if not isinstance(payload, dict):
        return fallback

    resolved = _validate_and_normalize_weights(payload)
    return resolved if resolved is not None else fallback
