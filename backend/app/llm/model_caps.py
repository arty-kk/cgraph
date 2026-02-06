# backend/app/llm/model_caps.py
from __future__ import annotations

import re

_GPT_VERSION_RE = re.compile(r"^gpt-(\d+)(?:\.(\d+))?(?:[.-].*|[a-z].*)?$")
_REASONING_MODEL_RE = re.compile(r"^o(\d+)(?:[.-].*)?$")


def _gpt_major_version(model: str) -> int | None:
    if not isinstance(model, str):
        return None
    name = model.strip().lower()
    if not name:
        return None
    match = _GPT_VERSION_RE.match(name)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _is_reasoning_model(model: str) -> bool:
    if not isinstance(model, str):
        return False
    name = model.strip().lower()
    if not name:
        return False
    return _REASONING_MODEL_RE.match(name) is not None


def supports_reasoning(model: str) -> bool:
    if _is_reasoning_model(model):
        return True
    major = _gpt_major_version(model)
    if major is None:
        return False
    return major >= 5


def supports_temperature(model: str) -> bool:
    if _is_reasoning_model(model):
        return False
    major = _gpt_major_version(model)
    if major is None:
        return True
    return major < 5
