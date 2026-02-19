# backend/app/llm/orchestrator.py
from __future__ import annotations

import json
from typing import Any

import openai

from ..config import settings
from .client import get_async_openai_client
from .model_caps import supports_reasoning, supports_temperature
from .policy import DEFAULT_POLICY, ModelPolicy
from .schemas import ANALYZE_SCHEMA, DOCS_SCHEMA, FIX_SCHEMA, PLAN_TZ_SCHEMA, TRIAGE_SCHEMA
from .usage import extract_usage

SYSTEM_INSTRUCTIONS = (
    "Ты — StubGraph: сверхточный кодовый архитектор. Твоя цель — давать полезный, "
    "проверяемый результат с минимальным радиусом изменений.\n"
    "Правила:\n"
    "- Опирайся только на предоставленный код/контракты/запрос.\n"
    "- Если данных недостаточно — явно укажи допущения.\n"
    "- Для фикса: предложи unified diff. Не выдумывай файлы, которых нет.\n"
    "- Сохраняй поведение и исходную стилистику, если пользователь не просит менять "
    "публичный API.\n"
)


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


async def _json_call_with_usage_async(
    model: str,
    schema: dict,
    input_items: list[dict[str, Any]],
    reasoning_effort: str | None = None,
    instructions: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict[str, int | None]]:
    client = get_async_openai_client()
    fmt = _normalize_responses_json_schema(schema)
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": instructions if instructions is not None else SYSTEM_INSTRUCTIONS,
        "input": input_items,
        "text": {"format": fmt},
    }
    kwargs["store"] = bool(settings.openai_store)
    if temperature is not None and supports_temperature(model):
        kwargs["temperature"] = float(temperature)
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
    if reasoning_effort and supports_reasoning(model):
        kwargs["reasoning"] = {"effort": reasoning_effort}

    try:
        resp = await client.responses.create(**kwargs)
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
        if "temperature" in msg:
            kwargs.pop("temperature", None)
            removed = True
        if removed:
            resp = await client.responses.create(**kwargs)
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
        return data, extract_usage(resp)
    except Exception as e:
        txt = _extract_output_text(resp)
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(txt[start : end + 1])
                if isinstance(data, dict):
                    return data, extract_usage(resp)
            except Exception:
                pass
        refusal = _extract_refusal(resp)
        if refusal:
            raise RuntimeError(f"Model refusal: {refusal}") from e
        raise RuntimeError(f"Failed to parse model JSON output: {e}\nRaw: {txt[:4000]}") from e


async def triage_with_usage_async(
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    *,
    instructions: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict[str, int | None]]:
    items = [
        {
            "role": "user",
            "content": (
                "Сконфигурируй задачу по запросу пользователя. Запрос: "
                f"{user_prompt!r}\n\n"
                "Верни: task_kind, depth, dep_mode, needs_patch, notes."
            ),
        },
    ]
    return await _json_call_with_usage_async(
        policy.triage_model,
        TRIAGE_SCHEMA,
        items,
        reasoning_effort=policy.triage_effort,
        instructions=instructions,
        temperature=temperature,
    )


async def analyze_with_usage_async(
    packed_context: dict,
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    *,
    instructions: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict[str, int | None]]:
    ctx = json.dumps(packed_context, ensure_ascii=False)
    items = [
        {
            "role": "user",
            "content": (
                f"Задача: ANALYZE. Пользовательский запрос: {user_prompt}\n\n"
                f"Контекст (JSON):\n{ctx}"
            ),
        },
    ]
    return await _json_call_with_usage_async(
        policy.analysis_model,
        ANALYZE_SCHEMA,
        items,
        reasoning_effort=policy.analysis_effort,
        instructions=instructions,
        temperature=temperature,
    )


async def evolve_with_usage_async(
    packed_context: dict,
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    *,
    instructions: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict[str, int | None]]:
    ctx = json.dumps(packed_context, ensure_ascii=False)
    items = [
        {
            "role": "user",
            "content": (
                "Задача: EVOLUTION POINTS. Найди точки эволюции бизнес-логики/домена, "
                "узкие места API, места частых изменений.\n"
                f"Пользовательский запрос: {user_prompt}\n\n"
                f"Контекст (JSON):\n{ctx}"
            ),
        },
    ]
    return await _json_call_with_usage_async(
        policy.analysis_model,
        ANALYZE_SCHEMA,
        items,
        reasoning_effort=policy.analysis_effort,
        instructions=instructions,
        temperature=temperature,
    )


async def plan_task_with_usage_async(
    knowledge: dict,
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    *,
    instructions: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict[str, int | None]]:
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
    return await _json_call_with_usage_async(
        policy.analysis_model,
        PLAN_TZ_SCHEMA,
        items,
        reasoning_effort=policy.analysis_effort,
        instructions=instructions,
        temperature=temperature,
    )


async def fix_with_usage_async(
    packed_context: dict,
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    *,
    instructions: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict[str, int | None]]:
    ctx = json.dumps(packed_context, ensure_ascii=False)
    items = [
        {
            "role": "user",
            "content": (
                f"Задача: FIX. Требование пользователя: {user_prompt}\n\n"
                "Сгенерируй минимальный безопасный unified diff (patch_unified_diff). "
                "Если нужно изменить поведение — делай это ровно по ТЗ.\n"
                "Поле tests обязательно: верни непустой список конкретных тестов или "
                "ручных шагов проверки. Отсутствие проверок недопустимо.\n\n"
                f"Контекст (JSON):\n{ctx}"
            ),
        },
    ]
    return await _json_call_with_usage_async(
        policy.patch_model,
        FIX_SCHEMA,
        items,
        reasoning_effort=policy.patch_effort,
        instructions=instructions,
        temperature=temperature,
    )


async def generate_docs_async(
    facts: dict,
    policy: ModelPolicy = DEFAULT_POLICY,
    *,
    instructions: str | None = None,
    temperature: float | None = None,
) -> dict:
    payload, _usage = await generate_docs_with_usage_async(
        facts,
        policy=policy,
        instructions=instructions,
        temperature=temperature,
    )
    return payload


async def generate_docs_with_usage_async(
    facts: dict,
    policy: ModelPolicy = DEFAULT_POLICY,
    *,
    instructions: str | None = None,
    temperature: float | None = None,
) -> tuple[dict, dict[str, int | None]]:
    ctx = json.dumps(facts, ensure_ascii=False)
    items = [
        {
            "role": "user",
            "content": (
                "Задача: PROJECT DOCS.\n"
                "Сгенерируй полезную документацию по проекту в Markdown.\n"
                "Критично: используй ТОЛЬКО предоставленные факты. Если данных недостаточно — "
                "явно укажи это.\n"
                "Структура: Overview, Architecture, Key modules, Hotspots, How to run "
                "(если можно вывести), Next steps.\n"
                "Подсказка: в фактах могут быть api_summary (API индекс из Scan), module_map "
                "(агрегаты по папкам),\n"
                "tree_outline (дерево файлов), contracts_sample (контракты файлов), "
                "key_files (snippets),\n"
                "hotspots/hubs_by_fan_in (таблицы рисков), run_hints (команды/таргеты), "
                "counts/languages.\n"
                "Если данные есть — используй их в соответствующих разделах.\n"
                "Если этих данных нет — так и напиши, не додумывай.\n\n"
                f"Факты (JSON):\n{ctx}"
            ),
        },
    ]
    return await _json_call_with_usage_async(
        policy.analysis_model,
        DOCS_SCHEMA,
        items,
        reasoning_effort=policy.analysis_effort,
        instructions=instructions,
        temperature=temperature,
    )
