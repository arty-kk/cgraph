#backend/app/llm/orchestrator.py
from __future__ import annotations

import json
import openai
from typing import Any
from .client import get_openai_client
from .schemas import TRIAGE_SCHEMA, ANALYZE_SCHEMA, FIX_SCHEMA, DOCS_SCHEMA, PLAN_TZ_SCHEMA
from .policy import ModelPolicy, DEFAULT_POLICY
from .model_caps import supports_reasoning
from ..config import settings

SYSTEM_INSTRUCTIONS = """Ты — CGRAPH: сверхточный кодовый архитектор. Твоя цель — давать полезный, проверяемый результат с минимальным радиусом изменений.
Правила:
- Опирайся только на предоставленный код/контракты/запрос.
- Если данных недостаточно — явно укажи допущения.
- Для фикса: предложи unified diff. Не выдумывай файлы, которых нет.
- Сохраняй поведение и исходную стилистику, если пользователь не просит менять публичный API.
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

def _extract_output_text(resp: Any) -> str:
    txt = getattr(resp, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()
    out = getattr(resp, "output", None)
    if not isinstance(out, list):
        return ""
    for item in out:
        item_text = getattr(item, "text", None)
        if item_text is None and isinstance(item, dict):
            item_text = item.get("text")
        if isinstance(item_text, str) and item_text.strip():
            return item_text.strip()
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if not isinstance(content, list):
            continue
        for c in content:
            text = getattr(c, "text", None)
            if text is None and isinstance(c, dict):
                text = c.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            if isinstance(c, dict):
                inner_text = c.get("content")
                if isinstance(inner_text, str) and inner_text.strip():
                    return inner_text.strip()
    return ""

def _json_call(model: str, schema: dict, input_items: list[dict[str, Any]], reasoning_effort: str | None = None) -> dict:
    client = get_openai_client()
    fmt = _normalize_responses_json_schema(schema)
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": input_items,
        "text": {"format": fmt},
    }
    kwargs["store"] = bool(settings.openai_store)
    if isinstance(settings.openai_prompt_cache_key, str) and settings.openai_prompt_cache_key.strip():
        kwargs["prompt_cache_key"] = settings.openai_prompt_cache_key.strip()
        if isinstance(settings.openai_prompt_cache_retention, str) and settings.openai_prompt_cache_retention.strip():
            kwargs["prompt_cache_retention"] = settings.openai_prompt_cache_retention.strip()
    if reasoning_effort and supports_reasoning(model):
        kwargs["reasoning"] = {"effort": reasoning_effort}

    try:
        resp = client.responses.create(**kwargs)
    except TypeError as e:
        msg = str(e)
        removed = False
        if "prompt_cache_key" in msg:
            kwargs.pop("prompt_cache_key", None)
            removed = True
        if "prompt_cache_retention" in msg:
            kwargs.pop("prompt_cache_retention", None)
            removed = True
        if "store" in msg:
            kwargs.pop("store", None)
            removed = True
        if removed:
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
        txt = _extract_output_text(resp)
        if not txt:
            refusal = _extract_refusal(resp)
            if refusal:
                raise RuntimeError(f"Model refusal: {refusal}")
        data = json.loads(txt)
        if not isinstance(data, dict):
            raise RuntimeError("Model returned JSON, but not an object")
        return data
    except Exception as e:
        txt = _extract_output_text(resp)
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

def plan_task(knowledge: dict, user_prompt: str, policy: ModelPolicy = DEFAULT_POLICY) -> dict:
    ctx = json.dumps(knowledge, ensure_ascii=False)
    items = [
        {
            "role": "user",
            "content": (
                "Задача: PLAN + ТЗ. Сформируй план реализации и оптимальное техническое задание.\n"
                "Требования:\n"
                "- Используй ТОЛЬКО предоставленные факты.\n"
                "- Если данных недостаточно — явно укажи допущения/открытые вопросы.\n"
                "- План должен быть практичным и проверяемым.\n\n"
                f"Пользовательский запрос: {user_prompt}\n\n"
                f"Факты (JSON):\n{ctx}"
            ),
        },
    ]
    return _json_call(policy.analysis_model, PLAN_TZ_SCHEMA, items, reasoning_effort=policy.analysis_effort)

def fix(packed_context: dict, user_prompt: str, policy: ModelPolicy = DEFAULT_POLICY) -> dict:
    ctx = json.dumps(packed_context, ensure_ascii=False)
    items = [
        {"role": "user", "content": (
            f"Задача: FIX. Требование пользователя: {user_prompt}\n\n"
            "Сгенерируй минимальный безопасный unified diff (patch_unified_diff). Если нужно изменить поведение — делай это ровно по ТЗ.\n"
            "Поле tests обязательно: верни непустой список конкретных тестов или ручных шагов проверки. Отсутствие проверок недопустимо.\n\n"
            f"Контекст (JSON):\n{ctx}"
        )},
    ]
    return _json_call(policy.patch_model, FIX_SCHEMA, items, reasoning_effort=policy.patch_effort)

def generate_docs(facts: dict, policy: ModelPolicy = DEFAULT_POLICY) -> dict:
    ctx = json.dumps(facts, ensure_ascii=False)
    items = [
        {"role": "user", "content": (
            "Задача: PROJECT DOCS.\n"
            "Сгенерируй полезную документацию по проекту в Markdown.\n"
            "Критично: используй ТОЛЬКО предоставленные факты. Если данных недостаточно — явно укажи это.\n"
            "Структура: Overview, Architecture, Key modules, Hotspots, How to run (если можно вывести), Next steps.\n"
            "Подсказка: в фактах могут быть api_summary (API индекс из Scan), module_map (агрегаты по папкам),\n"
            "tree_outline (дерево файлов), contracts_sample (контракты файлов), key_files (snippets),\n"
            "hotspots/hubs_by_fan_in (таблицы рисков), run_hints (команды/таргеты), counts/languages.\n"
            "Если данные есть — используй их в соответствующих разделах.\n"
            "Если этих данных нет — так и напиши, не додумывай.\n\n"
            f"Факты (JSON):\n{ctx}"
        )},
    ]
    return _json_call(policy.analysis_model, DOCS_SCHEMA, items, reasoning_effort=policy.analysis_effort)
