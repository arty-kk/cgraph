from __future__ import annotations

from typing import Any


def _usage_get(source: Any, key: str) -> Any:
    value = getattr(source, key, None)
    if value is None and isinstance(source, dict):
        value = source.get(key)
    return value


def _normalize_token_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except Exception:
        return None


def extract_usage(response: Any) -> dict[str, int | None]:
    usage = _usage_get(response, "usage")
    return {
        "prompt_tokens": _normalize_token_value(_usage_get(usage, "prompt_tokens")),
        "completion_tokens": _normalize_token_value(_usage_get(usage, "completion_tokens")),
        "total_tokens": _normalize_token_value(_usage_get(usage, "total_tokens")),
    }


def merge_usage(
    current: dict[str, int | None],
    extra: dict[str, int | None],
) -> dict[str, int | None]:
    merged: dict[str, int | None] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        left = current.get(key)
        right = extra.get(key)
        if left is None and right is None:
            merged[key] = None
        else:
            merged[key] = int(left or 0) + int(right or 0)
    return merged
