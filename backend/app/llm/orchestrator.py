#backend/app/llm/orchestrator.py
from __future__ import annotations

import json
import openai
from typing import Any
from .client import get_openai_client
from .schemas import TRIAGE_SCHEMA, ANALYZE_SCHEMA, FIX_SCHEMA
from .policy import ModelPolicy, DEFAULT_POLICY

SYSTEM_INSTRUCTIONS = """Ты — Code Surgeon: сверхточный кодовый хирург. Твоя цель — давать полезный, проверяемый результат с минимальным радиусом изменений.
Правила:
- Опирайся только на предоставленный код/контракты/запрос.
- Если данных недостаточно — явно укажи допущения.
- Для фикса: предложи unified diff. Не выдумывай файлы, которых нет.
- Сохраняй поведение, если пользователь не просит менять публичный API.
"""

def _normalize_responses_json_schema(schema: dict) -> dict:
    if not isinstance(schema, dict):
        raise TypeError("schema must be a dict")
    name = schema.get("name")
    inner = schema.get("schema")
    strict = schema.get("strict", True)
    if not isinstance(name, str) or not name:
        raise ValueError("schema.name must be a non-empty string")
    if not isinstance(inner, dict):
        raise ValueError("schema.schema must be a dict (JSON Schema)")
    if not isinstance(strict, bool):
        raise ValueError("schema.strict must be a bool")
    return {"type": "json_schema", "name": name, "schema": inner, "strict": strict}

def _extract_refusal(resp: Any) -> str | None:
    out = getattr(resp, "output", None)
    if not isinstance(out, list):
        return None
    for item in out:
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            refusal = getattr(c, "refusal", None)
            if refusal is None and isinstance(c, dict):
                refusal = c.get("refusal")
            if isinstance(refusal, str) and refusal.strip():
                return refusal.strip()
            c_type = getattr(c, "type", None)
            if c_type is None and isinstance(c, dict):
                c_type = c.get("type")
            if c_type == "refusal":
                txt = getattr(c, "text", None)
                if txt is None and isinstance(c, dict):
                    txt = c.get("text")
                if isinstance(txt, str) and txt.strip():
                    return txt.strip()
    return None

def _json_call(model: str, schema: dict, input_items: list[dict[str, Any]], reasoning_effort: str | None = None) -> dict:
    client = get_openai_client()
    fmt = _normalize_responses_json_schema(schema)
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": input_items,
        "text": {"format": fmt},
    }
    kwargs["prompt_cache_key"] = "code-surgeon-local"
    if reasoning_effort:
        kwargs["reasoning"] = {"effort": reasoning_effort}

    try:
        resp = client.responses.create(**kwargs)
    except TypeError as e:
        msg = str(e)
        if "prompt_cache_key" in msg:
            kwargs.pop("prompt_cache_key", None)
            resp = client.responses.create(**kwargs)
        else:
            raise
    except openai.APIError as e:
        status = getattr(e, "status_code", None)
        if status is not None:
            raise RuntimeError(f"OpenAI API error (HTTP {status}): {e}") from e
        raise RuntimeError(f"OpenAI API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"OpenAI request failed: {e}") from e

    try:
        txt = (getattr(resp, "output_text", None) or "").strip()
        if not txt:
            refusal = _extract_refusal(resp)
            if refusal:
                raise RuntimeError(f"Model refusal: {refusal}")
        data = json.loads(txt)
        if not isinstance(data, dict):
            raise RuntimeError("Model returned JSON, but not an object")
        return data
    except Exception as e:
        txt = (getattr(resp, "output_text", None) or "").strip()
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(txt[start:end+1])
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        refusal = _extract_refusal(resp)
        if refusal:
            raise RuntimeError(f"Model refusal: {refusal}") from e
        raise RuntimeError(f"Failed to parse model JSON output: {e}\nRaw: {txt[:4000]}") from e

def triage(user_prompt: str, policy: ModelPolicy = DEFAULT_POLICY) -> dict:
    items = [
        {"role": "user", "content": f"Сконфигурируй задачу по запросу пользователя. Запрос: {user_prompt!r}\n\nВерни: task_kind, depth, dep_mode, needs_patch, notes."},
    ]
    return _json_call(policy.triage_model, TRIAGE_SCHEMA, items, reasoning_effort=policy.triage_effort)

def analyze(packed_context: dict, user_prompt: str, policy: ModelPolicy = DEFAULT_POLICY) -> dict:
    ctx = json.dumps(packed_context, ensure_ascii=False)
    items = [
        {"role": "user", "content": f"Задача: ANALYZE. Пользовательский запрос: {user_prompt}\n\nКонтекст (JSON):\n{ctx}"},
    ]
    return _json_call(policy.analysis_model, ANALYZE_SCHEMA, items, reasoning_effort=policy.analysis_effort)

def evolve(packed_context: dict, user_prompt: str, policy: ModelPolicy = DEFAULT_POLICY) -> dict:
    ctx = json.dumps(packed_context, ensure_ascii=False)
    items = [
        {"role": "user", "content": f"Задача: EVOLUTION POINTS. Найди точки эволюции бизнес-логики/домена, узкие места API, места частых изменений.\nПользовательский запрос: {user_prompt}\n\nКонтекст (JSON):\n{ctx}"},
    ]
    return _json_call(policy.analysis_model, ANALYZE_SCHEMA, items, reasoning_effort=policy.analysis_effort)

def fix(packed_context: dict, user_prompt: str, policy: ModelPolicy = DEFAULT_POLICY) -> dict:
    ctx = json.dumps(packed_context, ensure_ascii=False)
    items = [
        {"role": "user", "content": f"Задача: FIX. Требование пользователя: {user_prompt}\n\nСгенерируй минимальный безопасный unified diff (patch_unified_diff). Если нужно изменить поведение — делай это ровно по ТЗ.\n\nКонтекст (JSON):\n{ctx}"},
    ]
    return _json_call(policy.patch_model, FIX_SCHEMA, items, reasoning_effort=policy.patch_effort)
