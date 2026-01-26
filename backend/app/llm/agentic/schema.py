from __future__ import annotations

import json
from typing import Any


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


def _parse_model_json(resp: Any) -> dict:
    txt = (getattr(resp, "output_text", None) or "").strip()
    if not txt:
        refusal = _extract_refusal(resp)
        if refusal:
            raise RuntimeError(f"Model refusal: {refusal}")
        raise RuntimeError("Empty model output_text")
    try:
        data = json.loads(txt)
        if not isinstance(data, dict):
            raise RuntimeError("Model returned JSON, but not an object")
        return data
    except Exception as e:
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(txt[start : end + 1])
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        refusal = _extract_refusal(resp)
        if refusal:
            raise RuntimeError(f"Model refusal: {refusal}") from e
        raise RuntimeError(f"Failed to parse model JSON output: {e}\nRaw: {txt[:4000]}") from e
