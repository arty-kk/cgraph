from __future__ import annotations

import json
from typing import Any

import openai

from ...config import settings
from ..model_caps import supports_reasoning, supports_temperature
from ..schemas import SELF_CHECK_SCHEMA
from .schema import _normalize_responses_json_schema, _parse_model_json


def _run_self_check(
    *,
    client: openai.Client,
    model: str,
    reasoning_effort: str | None,
    user_prompt: str,
    seed: dict,
    response_payload: dict,
) -> dict:
    fmt = _normalize_responses_json_schema(SELF_CHECK_SCHEMA)
    input_list = [
        {
            "role": "user",
            "content": (
                "Проверь, соответствует ли ответ задаче и контексту. "
                "Если контекста недостаточно — перечисли, что запросить.\n\n"
                f"User prompt:\n{user_prompt}\n\n"
                f"Seed context (JSON):\n{json.dumps(seed, ensure_ascii=False)}\n\n"
                f"Model response (JSON):\n{json.dumps(response_payload, ensure_ascii=False)}"
            ),
        }
    ]
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": "You are a strict reviewer. Reply with JSON only.",
        "input": input_list,
        "text": {"format": fmt},
        "store": bool(settings.openai_store),
        "parallel_tool_calls": False,
    }
    if supports_temperature(model):
        kwargs["temperature"] = 0.0
    if reasoning_effort and supports_reasoning(model):
        kwargs["reasoning"] = {"effort": reasoning_effort}
    if (
        isinstance(settings.openai_prompt_cache_key, str)
        and settings.openai_prompt_cache_key.strip()
    ):
        kwargs["prompt_cache_key"] = settings.openai_prompt_cache_key.strip()
        if (
            isinstance(settings.openai_prompt_cache_retention, str)
            and settings.openai_prompt_cache_retention.strip()
        ):
            kwargs["prompt_cache_retention"] = settings.openai_prompt_cache_retention.strip()
    try:
        resp = client.responses.create(**kwargs)
    except TypeError as e:
        msg = str(e)
        for k in (
            "prompt_cache_key",
            "prompt_cache_retention",
            "store",
            "temperature",
            "parallel_tool_calls",
        ):
            if k in msg:
                kwargs.pop(k, None)
        resp = client.responses.create(**kwargs)
    return _parse_model_json(resp)
