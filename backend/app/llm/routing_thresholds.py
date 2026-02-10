from __future__ import annotations

from ..config import settings
from ..infra.cache import cache_get_json


def resolve_routing_thresholds() -> tuple[float, float, float]:
    defaults = (
        float(settings.llm_routing_threshold_low),
        float(settings.llm_routing_threshold_mid),
        float(settings.llm_routing_threshold_high),
    )
    cached = cache_get_json(["routing_policy", "thresholds", settings.llm_routing_policy_version])
    if not isinstance(cached, dict):
        return defaults

    try:
        low = float(cached.get("low", defaults[0]))
        mid = float(cached.get("mid", defaults[1]))
        high = float(cached.get("high", defaults[2]))
    except (TypeError, ValueError):
        return defaults

    if 1.0 <= low <= mid <= high <= 2.0:
        return (low, mid, high)
    return defaults
