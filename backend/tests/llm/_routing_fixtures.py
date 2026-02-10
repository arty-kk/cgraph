"""Shared deterministic fixtures for LLM routing tests."""

MODEL_STATS_CANONICAL = {
    "gpt-5-nano": {
        "quality": 0.70,
        "latency_ms": 400,
        "token_cost": 0.2,
        "fail_rate": 0.04,
    },
    "gpt-5-mini": {
        "quality": 0.82,
        "latency_ms": 650,
        "token_cost": 0.5,
        "fail_rate": 0.03,
    },
    "gpt-5.2-codex": {
        "quality": 0.93,
        "latency_ms": 900,
        "token_cost": 0.9,
        "fail_rate": 0.02,
    },
}

MODEL_STATS_TRADEOFF = {
    "gpt-5-nano": {
        "quality": 0.74,
        "latency_ms": 180,
        "token_cost": 0.08,
        "fail_rate": 0.07,
    },
    "gpt-5-mini": {
        "quality": 0.84,
        "latency_ms": 420,
        "token_cost": 0.3,
        "fail_rate": 0.04,
    },
    "gpt-5.2-codex": {
        "quality": 0.95,
        "latency_ms": 980,
        "token_cost": 0.95,
        "fail_rate": 0.02,
    },
}

MODEL_STATS_THRESHOLD_SWITCH = {
    "gpt-5-nano": {
        "quality": 0.72,
        "latency_ms": 307,
        "token_cost": 0.14,
        "fail_rate": 0.04,
    },
    "gpt-5-mini": {
        "quality": 0.86,
        "latency_ms": 343,
        "token_cost": 0.23,
        "fail_rate": 0.02,
    },
    "gpt-5.2-codex": {
        "quality": 0.98,
        "latency_ms": 647,
        "token_cost": 0.7,
        "fail_rate": 0.02,
    },
}

DEFAULT_ROUTING_SETTINGS = {
    "triage_model": "gpt-5-nano|gpt-5-mini|gpt-5.2-codex",
    "analysis_model": "gpt-5-nano|gpt-5-mini|gpt-5.2-codex",
    "patch_model": "gpt-5-mini|gpt-5.2-codex",
    "llm_routing_policy_version": "contract-v1",
    "llm_routing_weight_quality": 0.4,
    "llm_routing_weight_latency": 0.25,
    "llm_routing_weight_token_cost": 0.2,
    "llm_routing_weight_fail_rate": 0.15,
    "llm_routing_threshold_low": 1.35,
    "llm_routing_threshold_mid": 1.5,
    "llm_routing_threshold_high": 1.7,
}
