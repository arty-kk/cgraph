#backend/app/llm/agentic.py
from __future__ import annotations

import json
import time
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openai
from sqlmodel import select
from sqlalchemy import text as sa_text

from ..config import settings
from ..contracts import get_or_build_contract
from ..db import get_session
from ..graph import search_nodes, search_semantic
from ..models import FileEdge, FileNode, ApiRoute, ApiCall, ApiInclude, ApiRouteContract, ApiCallMeta, TsTypeDef, ModuleContract
from ..utils import resolve_under_root
from ..api_map import split_skeleton, patterns_compatible, static_match_score, backend_path_skeleton
from ..api_scaffold import suggest_frontend_module_file, build_frontend_snippet
from ..api_contracts import build_backend_contract_for_route
from ..services.docs_service import _compute_project_summary_facts, _tree_outline
from ..ts_edits import unified_diff as _unified_diff, ts_add_fields_to_typedef, ts_patch_wrapper_function
from ..py_edits import py_add_keys_to_function_return_dicts
from ..scan import SEARCH_INDEX_MAX_CHARS
from .client import get_openai_client
from .model_caps import supports_reasoning, supports_temperature
from .policy import ModelPolicy, DEFAULT_POLICY
from .schemas import ANALYZE_SCHEMA, FIX_SCHEMA, SELF_CHECK_SCHEMA
from .orchestrator import SYSTEM_INSTRUCTIONS


@dataclass
class AgenticMeta:
    full_file_paths: set[str] = field(default_factory=set)
    tool_calls: int = 0
    total_tool_output_chars: int = 0
    cache_hits: int = 0
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    retrieval_plan: dict | None = None
    self_check_ok: bool | None = None
    self_check_notes: list[str] = field(default_factory=list)
    self_check_missing_context: list[str] = field(default_factory=list)


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


def _run_self_check(
    *,
    client: openai.Client,
    model: str,
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
    if isinstance(settings.openai_prompt_cache_key, str) and settings.openai_prompt_cache_key.strip():
        kwargs["prompt_cache_key"] = settings.openai_prompt_cache_key.strip()
        if isinstance(settings.openai_prompt_cache_retention, str) and settings.openai_prompt_cache_retention.strip():
            kwargs["prompt_cache_retention"] = settings.openai_prompt_cache_retention.strip()
    try:
        resp = client.responses.create(**kwargs)
    except TypeError as e:
        msg = str(e)
        for k in ("prompt_cache_key", "prompt_cache_retention", "store", "temperature", "parallel_tool_calls"):
            if k in msg:
                kwargs.pop(k, None)
        resp = client.responses.create(**kwargs)
    return _parse_model_json(resp)


def _neighbors_limited(
    project_id: int,
    start: str,
    *,
    direction: str,
    depth: int,
    limit: int,
) -> list[str]:
    if depth <= 0 or limit <= 0:
        return []
    depth = max(0, min(depth, 6))
    limit = max(1, min(limit, 2000))
    visited: set[str] = {start}
    ordered: list[str] = []
    frontier: list[str] = [start]

    def _chunks(seq: list[str], size: int) -> list[list[str]]:
        return [seq[i:i+size] for i in range(0, len(seq), size)]

    SQLITE_IN_CHUNK = 400

    with get_session() as s:
        for _ in range(depth):
            if not frontier or len(ordered) >= limit:
                break
            frontier = list(dict.fromkeys(frontier))
            nxt: list[str] = []
            stop = False
            for chunk in _chunks(frontier, SQLITE_IN_CHUNK):
                if direction == "in":
                    rows = s.exec(
                        select(FileEdge.src_path)
                        .where(FileEdge.project_id == project_id, FileEdge.dst_path.in_(chunk))
                        .order_by(FileEdge.src_path)
                    ).all()
                else:
                    rows = s.exec(
                        select(FileEdge.dst_path)
                        .where(FileEdge.project_id == project_id, FileEdge.src_path.in_(chunk))
                        .order_by(FileEdge.dst_path)
                    ).all()
                for row in rows:
                    val = row[0] if isinstance(row, (tuple, list)) else row
                    if not isinstance(val, str) or not val:
                        continue
                    if val in visited:
                        continue
                    visited.add(val)
                    ordered.append(val)
                    nxt.append(val)
                    if len(ordered) >= limit:
                        stop = True
                        break
                if stop:
                    break
            frontier = nxt
    return ordered[:limit]


_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

def _fts_query_from_substring(q: str, *, max_tokens: int = 12) -> str | None:
    tokens = [t for t in _FTS_TOKEN_RE.findall(q or "") if t]
    if not tokens:
        return None
    tokens = tokens[: max(1, int(max_tokens))]
    esc = []
    for t in tokens:
        esc.append(t.replace('"', '""'))
    return " AND ".join([f'"{t}"' for t in esc if t])


def _tool_definitions(max_file_chars: int) -> list[dict]:
    max_file_chars = max(200, min(int(max_file_chars), 50_000))
    tools = [
        {
            "type": "function",
            "name": "plan_retrieval",
            "description": "Provide a structured retrieval plan before using other tools.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "goal": {"type": "string"},
                    "hypotheses": {"type": "array", "items": {"type": "string"}},
                    "search_steps": {"type": "array", "items": {"type": "string"}},
                    "read_steps": {"type": "array", "items": {"type": "string"}},
                    "candidate_ranking": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "item": {"type": "string"},
                                "reason": {"type": "string"},
                                "score": {"type": "number"},
                                "rank": {"type": "integer"},
                            },
                            "required": ["item", "reason"],
                            "anyOf": [{"required": ["score"]}, {"required": ["rank"]}],
                        },
                    },
                },
                "required": ["goal", "hypotheses", "search_steps", "read_steps", "candidate_ranking"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_file",
            "description": "Read a text file under the project root. Use when you need exact code. Prefer get_contract first if exports are enough.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Path relative to project root"},
                    "max_chars": {"type": ["integer", "null"], "minimum": 200, "maximum": max_file_chars},
                },
                "required": ["path", "max_chars"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_file_lines",
            "description": "Read a line-range from a text file under the project root (precise snippet).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Path relative to project root"},
                    "start_line": {"type": "integer", "minimum": 1, "description": "1-based start line"},
                    "end_line": {"type": "integer", "minimum": 1, "description": "1-based end line (inclusive)"},
                    "max_chars": {"type": ["integer", "null"], "minimum": 200, "maximum": max_file_chars},
                },
                "required": ["path", "start_line", "end_line", "max_chars"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_contract",
            "description": "Get a lightweight module contract (language, exports) for a file under project root.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_symbol",
            "description": "Get a symbol definition from the module contract (requires contract v2 with symbols).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "name": {"type": "string", "description": "Symbol name"},
                },
                "required": ["path", "name"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_node",
            "description": "Get graph metrics for a file node (loc, complexity, fan_in/out, status).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"}
                    },
                "required": ["path"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_neighbors",
            "description": "Get inbound/outbound dependency paths from the indexed file graph.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string"},
                    "direction": {"type": "string", "enum": ["in", "out"]},
                    "depth": {"type": ["integer", "null"], "minimum": 0, "maximum": 6},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 2000},
                },
                "required": ["path", "direction", "depth", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_paths",
            "description": "Search indexed file paths by substring (path LIKE %query%).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
                },
                "required": ["query", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_tests",
            "description": "Search test files by standard patterns (tests/, __tests__/, *.spec.*, *.test.*, test_*.py, *_test.*).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": ["string", "null"]},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                },
                "required": ["query", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_tree_outline",
            "description": (
                "Return a tree outline of the project structure without reading file contents. "
                "Useful for a quick overview of folders/files."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prefix": {"type": ["string", "null"], "description": "Optional folder/path prefix to scope the tree"},
                    "max_lines": {"type": ["integer", "null"], "minimum": 100, "maximum": 2000},
                    "max_depth": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
                },
                "required": ["prefix", "max_lines", "max_depth"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "project_summary",
            "description": "Get project-level summary facts (counts, hotspots, hubs by fan-in, module map).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_symbols",
            "description": (
                "Search symbols and exports from module contracts. Faster and more precise than search_text "
                "for navigating definitions and exports."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "description": "Symbol name to search for"},
                    "exported_only": {"type": ["boolean", "null"], "description": "Only return exported symbols"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500, "default": 100},
                    "match": {"type": ["string", "null"], "enum": ["exact", "contains", "prefix"]},
                    "case_sensitive": {"type": ["boolean", "null"], "default": False},
                },
                "required": ["query", "exported_only", "limit", "match", "case_sensitive"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_text",
            "description": (
                "Search for a substring in indexed project files and return small snippets with locations. "
                "Use to quickly find symbol usage before fetching full files."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "description": "Substring to search for"},
                    "prefix": {"type": ["string", "null"], "description": "Optional path prefix filter (folder)"},
                    "case_sensitive": {"type": ["boolean", "null"], "description": "Case-sensitive match"},
                    "max_files": {"type": ["integer", "null"], "minimum": 1, "maximum": 2000},
                    "max_matches": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                    "context_chars": {"type": ["integer", "null"], "minimum": 40, "maximum": 400},
                },
                "required": ["query", "prefix", "case_sensitive", "max_files", "max_matches", "context_chars"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_semantic",
            "description": (
                "Semantic search over indexed file chunks using embeddings. "
                "Returns best-matching paths with snippets."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "description": "Natural-language query"},
                    "max_results": {"type": ["integer", "null"], "minimum": 1, "maximum": 200},
                    "prefix": {"type": ["string", "null"], "description": "Optional path prefix filter (folder)"},
                },
                "required": ["query", "max_results", "prefix"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_routes",
            "description": "Search backend FastAPI routes indexed from scan (method/path/handler/source).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "description": "Substring to search in route path or handler name (empty = all)"},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter (GET/POST/...)"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                },
                "required": ["query", "method", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "search_api_calls",
            "description": "Search frontend HTTP calls (axios/fetch) indexed from scan.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string", "description": "Substring to search in call path (empty = all)"},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                },
                "required": ["query", "method", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "route_usages",
            "description": "Find frontend calls that likely hit a backend route by template-compatibility (supports {param} and {param:path}).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Backend route path (full) or a substring to search routes"},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter"},
                    "route_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
                    "call_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 50},
                },
                "required": ["path", "method", "route_limit", "call_limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "suggest_endpoint_location",
            "description": "Suggest where to implement a new backend endpoint (best matching backend/app/api/*.py and router instance).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Desired backend path, e.g. /api/projects/{project_id}/foo"},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
                },
                "required": ["path", "method", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "suggest_frontend_client",
            "description": "Suggest frontend API wrapper for a backend route (file/module/function and TS snippet).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Backend path (can be full or partial)."},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter."},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                },
                "required": ["path", "method", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "impact_route_change",
            "description": (
                "Analyze impact of changing a backend route path/method on indexed frontend calls. "
                "Matches by template-compatibility (supports {param} and {param:path})."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "old_path": {"type": "string", "description": "Current external route path (full), e.g. /api/projects/{project_id}/scan"},
                    "new_path": {"type": "string", "description": "New external route path (full), e.g. /api/projects/{project_id}/export"},
                    "old_method": {"type": ["string", "null"], "description": "Optional old method (GET/POST/...)"},
                    "new_method": {"type": ["string", "null"], "description": "Optional new method (GET/POST/...)"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                },
                "required": ["old_path", "new_path", "old_method", "new_method", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "api_coverage_summary",
            "description": "Compute backend↔frontend API coverage summary using indexed routes/calls (includes include_router resolution).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prefix": {"type": ["string", "null"], "description": "Optional path prefix filter (default: /api)"},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter"},
                    "limit_examples": {"type": ["integer", "null"], "minimum": 0, "maximum": 50},
                },
                "required": ["prefix", "method", "limit_examples"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "unmatched_routes",
            "description": "List backend routes that do not match any frontend calls (template-based matching, includes include_router).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prefix": {"type": ["string", "null"], "description": "Optional path prefix filter (default: /api)"},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                },
                "required": ["prefix", "method", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "unmatched_calls",
            "description": "List frontend HTTP calls that do not match any backend routes (template-based matching, includes include_router).",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prefix": {"type": ["string", "null"], "description": "Optional path prefix filter (default: /api)"},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter"},
                    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                },
                "required": ["prefix", "method", "limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "compare_api_contract",
            "description": (
                "Compare backend route request/response contract with matching frontend calls and TS types "
                "(best-effort, based on indexed contracts/types)."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Backend path (full or partial)."},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter."},
                    "route_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                    "call_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 50},
                },
                "required": ["path", "method", "route_limit", "call_limit"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "suggest_contract_fix",
            "description": (
                "Generate minimal unified diffs to fix frontend wrapper/types to match backend API contract "
                "(based on compare_api_contract + indexed TS types). Best-effort, additive changes."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Backend route path (full or partial)."},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter."},
                    "route_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                    "call_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                    "max_patches": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
                },
                "required": ["path", "method", "route_limit", "call_limit", "max_patches"],
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "suggest_api_fix",
            "description": (
                "Generate a single multi-file unified diff that fixes frontend wrapper/types AND (optionally) backend literal dict responses "
                "to align contracts. Backend changes are additive and only apply to literal `return {...}` dicts."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {"type": "string", "description": "Backend route path (full or partial)."},
                    "method": {"type": ["string", "null"], "description": "Optional HTTP method filter."},
                    "route_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 3},
                    "call_limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                    "include_backend_response": {"type": ["boolean", "null"], "description": "If true: add missing response keys to backend literal dict returns."},
                    "max_files": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
                },
                "required": ["path", "method", "route_limit", "call_limit", "include_backend_response", "max_files"],
            },
            "strict": True,
        },
    ]

    for t in tools:
        if not isinstance(t, dict):
            continue
        if t.get("type") != "function" or t.get("strict") is not True:
            continue
        params = t.get("parameters")
        if not isinstance(params, dict):
            continue
        props = params.get("properties")
        if not isinstance(props, dict):
            continue
        if "reason" not in props:
            props["reason"] = {"type": ["string", "null"], "description": "Optional reason for tool call"}
        req = params.get("required")
        if isinstance(req, list):
            params["required"] = [k for k in req if isinstance(k, str) and k in props]

    return tools

def _clamp_int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        x = int(v)
    except Exception:
        x = int(default)
    return max(lo, min(hi, x))

def _clamp_float(v: Any, default: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except Exception:
        x = float(default)
    if x != x:
        x = float(default)
    return max(lo, min(hi, x))

def _tool_ok(data: dict) -> dict:
    if not isinstance(data, dict):
        raise TypeError("tool data must be a dict")
    return {"ok": True, "data": data, "error": None}

def _tool_error(code: str, message: str, details: dict | None = None) -> dict:
    details_out = details if isinstance(details, dict) and details else None
    return {
        "ok": False,
        "data": None,
        "error": {"code": str(code), "message": str(message), "details": details_out},
    }

def _tool_get_file(project_id: int, root: Path, meta: AgenticMeta, args: dict, *, max_file_chars: int) -> dict:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        return _tool_error("bad_args", "path is required")
    max_file_chars = max(200, min(int(max_file_chars), 50_000))
    max_chars = _clamp_int(args.get("max_chars"), max_file_chars, 200, 50_000)
    max_chars = min(max_chars, max_file_chars)
    try:
        abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    except Exception as e:
        return _tool_error("invalid_path", str(e))
    if not abs_path.exists():
        return _tool_error("not_found", "path not found", {"path": rel_norm})
    if not abs_path.is_file():
        return _tool_error("not_a_file", "path is not a file", {"path": rel_norm})
    try:
        with abs_path.open(encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
    except Exception as e:
        return _tool_error("read_failed", "failed to read file", {"path": rel_norm, "reason": str(e)})
    truncated = len(text) > max_chars
    text = text[:max_chars]
    meta.full_file_paths.add(rel_norm)
    return _tool_ok({"path": rel_norm, "content": text, "truncated": truncated, "max_chars": max_chars})

def _tool_get_file_lines(project_id: int, root: Path, meta: AgenticMeta, args: dict, *, max_file_chars: int) -> dict:
    path = args.get("path")
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if not isinstance(path, str) or not path.strip():
        return _tool_error("bad_args", "path is required")
    try:
        s_ln = int(start_line)
        e_ln = int(end_line)
    except Exception:
        return _tool_error("bad_args", "start_line/end_line must be integers")
    if s_ln < 1 or e_ln < 1 or e_ln < s_ln:
        return _tool_error("bad_args", "invalid line range")
    max_file_chars = max(200, min(int(max_file_chars), 50_000))
    max_chars = _clamp_int(args.get("max_chars"), max_file_chars, 200, 50_000)
    max_chars = min(max_chars, max_file_chars)
    try:
        abs_path, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    except Exception as e:
        return _tool_error("invalid_path", str(e))
    if not abs_path.exists():
        return _tool_error("not_found", "path not found", {"path": rel_norm})
    if not abs_path.is_file():
        return _tool_error("not_a_file", "path is not a file", {"path": rel_norm})
    try:
        with abs_path.open(encoding="utf-8", errors="replace") as f:
            buffer: list[str] = []
            for line_num, line in enumerate(f, start=1):
                if line_num < s_ln:
                    continue
                buffer.append(line)
                if line_num >= e_ln:
                    break
    except Exception as e:
        return _tool_error("read_failed", "failed to read file", {"path": rel_norm, "reason": str(e)})
    snippet = "".join(buffer)
    truncated = len(snippet) > max_chars
    if truncated:
        snippet = snippet[:max_chars]
    meta.full_file_paths.add(rel_norm)
    return _tool_ok(
        {
            "path": rel_norm,
            "start_line": s_ln,
            "end_line": e_ln,
            "content": snippet,
            "truncated": truncated,
            "max_chars": max_chars,
        }
    )

def _tool_get_contract(project_id: int, root: Path, meta: AgenticMeta, args: dict) -> dict:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        return _tool_error("bad_args", "path is required")
    try:
        _abs, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    except Exception as e:
        return _tool_error("invalid_path", str(e))
    try:
        contract = get_or_build_contract(project_id, root, rel_norm)
    except Exception as e:
        return _tool_error("contract_failed", "failed to build contract", {"path": rel_norm, "reason": str(e)})
    meta.full_file_paths.add(rel_norm)
    if not isinstance(contract, dict):
        return _tool_error("contract_failed", "contract is not a dict", {"path": rel_norm})
    return _tool_ok(contract)

def _tool_get_symbol(project_id: int, root: Path, meta: AgenticMeta, args: dict) -> dict:
    path = args.get("path")
    name = args.get("name")
    if not isinstance(path, str) or not path.strip():
        return _tool_error("bad_args", "path is required")
    if not isinstance(name, str) or not name.strip():
        return _tool_error("bad_args", "name is required")
    try:
        _abs, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    except Exception as e:
        return _tool_error("invalid_path", str(e))
    try:
        c = get_or_build_contract(project_id, root, rel_norm)
    except Exception as e:
        return _tool_error("contract_failed", "failed to build contract", {"path": rel_norm, "reason": str(e)})
    meta.full_file_paths.add(rel_norm)
    if not isinstance(c, dict):
        return _tool_error("contract_failed", "contract is not a dict", {"path": rel_norm})
    syms = c.get("symbols")
    if not isinstance(syms, list):
        return _tool_error("no_symbols", "contract has no symbols (need contract v2)", {"path": rel_norm})
    needle = name.strip()
    for item in syms:
        if isinstance(item, dict) and str(item.get("name") or "") == needle:
            return _tool_ok({"path": rel_norm, "symbol": item})
    return _tool_error("not_found", "symbol not found", {"path": rel_norm, "name": needle})

def _tool_get_node(project_id: int, root: Path, args: dict) -> dict:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        return _tool_error("bad_args", "path is required")
    try:
        _abs, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    except Exception as e:
        return _tool_error("invalid_path", str(e))
    with get_session() as s:
        n = s.exec(
            select(FileNode).where(FileNode.project_id == project_id, FileNode.path == rel_norm)
        ).first()
    if not n:
        return _tool_error("not_found", "node not found", {"path": rel_norm})
    return _tool_ok(
        {
            "path": n.path,
            "language": n.language,
            "loc": n.loc,
            "complexity": n.complexity,
            "fan_in": n.fan_in,
            "fan_out": n.fan_out,
            "scc_id": n.scc_id,
            "status": n.status,
        }
    )


def _tool_get_neighbors(project_id: int, root: Path, args: dict) -> dict:
    path = args.get("path")
    direction = args.get("direction")
    depth = _clamp_int(args.get("depth"), 1, 0, 6)
    limit = _clamp_int(args.get("limit"), 200, 1, 2000)
    if not isinstance(path, str) or not path.strip():
        return _tool_error("bad_args", "path is required")
    if direction not in ("in", "out"):
        return _tool_error("bad_args", "direction must be 'in' or 'out'")
    try:
        _abs, rel_norm = resolve_under_root(root, path, max_length=settings.max_rel_path_chars)
    except Exception as e:
        return _tool_error("invalid_path", str(e))
    neigh = _neighbors_limited(project_id, rel_norm, direction=direction, depth=depth, limit=limit)
    return _tool_ok(
        {"path": rel_norm, "direction": direction, "depth": depth, "neighbors": neigh, "count": len(neigh)}
    )


def _tool_search_paths(project_id: int, args: dict) -> dict:
    query = args.get("query")
    limit = _clamp_int(args.get("limit"), 20, 1, 100)
    if not isinstance(query, str) or not query.strip():
        return _tool_error("bad_args", "query is required")
    rows = search_nodes(project_id, query.strip(), limit=limit)
    return _tool_ok({"query": query.strip(), "limit": limit, "results": rows})

def _tool_search_tests(project_id: int, args: dict) -> dict:
    query = args.get("query")
    query_norm = ""
    if isinstance(query, str) and query.strip():
        query_norm = query.strip()
    limit = _clamp_int(args.get("limit"), 50, 1, 500)

    patterns = [
        "tests/%",
        "%/tests/%",
        "__tests__/%",
        "%/__tests__/%",
        "%.spec.%",
        "%.test.%",
        "test\\_%.py",
        "%/test\\_%.py",
        "%\\_test.%",
    ]
    cond = None
    for pattern in patterns:
        clause = FileNode.path.like(pattern, escape="\\")
        cond = clause if cond is None else (cond | clause)
    if query_norm:
        like = f"%{query_norm}%"
        cond = cond & FileNode.path.like(like)

    with get_session() as s:
        rows = s.exec(
            select(FileNode.path, FileNode.language, FileNode.fan_in, FileNode.fan_out)
            .where(FileNode.project_id == project_id, cond)
            .order_by(FileNode.path.asc())
            .limit(int(limit))
        ).all()

    results: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, (tuple, list)):
            path, lang, fi, fo = row[0], row[1], row[2], row[3]
        else:
            path = getattr(row, "path", "")
            lang = getattr(row, "language", "")
            fi = getattr(row, "fan_in", 0)
            fo = getattr(row, "fan_out", 0)
        if not isinstance(path, str) or not path:
            continue
        try:
            fi_val = int(fi or 0)
        except Exception:
            fi_val = 0
        try:
            fo_val = int(fo or 0)
        except Exception:
            fo_val = 0
        results.append(
            {
                "path": path,
                "language": lang,
                "fan_in": fi_val,
                "fan_out": fo_val,
            }
        )

    return _tool_ok({"query": query_norm, "limit": int(limit), "results": results})


def _tool_search_symbols(project_id: int, args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return _tool_error("bad_args", "query is required")
    needle = query.strip()
    match = args.get("match")
    match_mode = match if isinstance(match, str) and match in ("exact", "prefix", "contains") else None
    if match_mode is None:
        match_mode = "contains"

    case_sensitive_raw = args.get("case_sensitive")
    case_sensitive = bool(case_sensitive_raw) if case_sensitive_raw is not None else False

    exported_only = args.get("exported_only") is True

    limit = _clamp_int(args.get("limit"), 100, 1, 500)

    def _cmp_val(val: str) -> str:
        return val if case_sensitive else val.lower()

    needle_cmp = _cmp_val(needle)

    def _match_type(name: str) -> str | None:
        if not name:
            return None
        name_cmp = _cmp_val(name)
        if name_cmp == needle_cmp:
            return "exact"
        if name_cmp.startswith(needle_cmp):
            return "prefix"
        if needle_cmp in name_cmp:
            return "contains"
        return None

    def _allow_match(match_type: str) -> bool:
        if match_mode == "exact":
            return match_type == "exact"
        if match_mode == "prefix":
            return match_type in ("exact", "prefix")
        if match_mode == "contains":
            return match_type in ("exact", "prefix", "contains")
        return False

    rows: list[ModuleContract] = []
    with get_session() as s:
        rows = s.exec(
            select(ModuleContract)
            .where(ModuleContract.project_id == project_id)
            .order_by(ModuleContract.path.asc())
        ).all()

    results: list[dict[str, Any]] = []
    for row in rows:
        try:
            contract = json.loads(row.contract_json)
        except Exception:
            continue
        if not isinstance(contract, dict):
            continue
        path = str(row.path or contract.get("path") or "")
        if not path:
            continue

        symbol_names: set[str] = set()
        symbols = contract.get("symbols")
        if isinstance(symbols, list):
            for item in symbols:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "")
                if not name:
                    continue
                symbol_names.add(name)
                match_type = _match_type(name)
                if not match_type:
                    continue
                if not _allow_match(match_type):
                    continue
                exported = bool(item.get("exported"))
                if exported_only and not exported:
                    continue
                results.append(
                    {
                        "path": path,
                        "name": name,
                        "kind": item.get("kind") if item.get("kind") is not None else None,
                        "signature": item.get("signature") if item.get("signature") is not None else None,
                        "start_line": item.get("start_line") if item.get("start_line") is not None else None,
                        "end_line": item.get("end_line") if item.get("end_line") is not None else None,
                        "exported": exported,
                        "source": "symbol",
                        "_match": match_type,
                    }
                )

        exports = contract.get("exports")
        if isinstance(exports, list):
            for exp in exports:
                name = str(exp or "")
                if not name or name in symbol_names:
                    continue
                match_type = _match_type(name)
                if not match_type:
                    continue
                if not _allow_match(match_type):
                    continue
                results.append(
                    {
                        "path": path,
                        "name": name,
                        "kind": None,
                        "signature": None,
                        "start_line": None,
                        "end_line": None,
                        "exported": True,
                        "source": "export",
                        "_match": match_type,
                    }
                )

    match_rank = {"exact": 0, "prefix": 1, "contains": 2}
    results.sort(
        key=lambda r: (
            match_rank.get(r.get("_match"), 99),
            0 if r.get("exported") else 1,
            str(r.get("path") or ""),
            str(r.get("name") or ""),
        )
    )
    results = results[:limit]
    for item in results:
        item.pop("_match", None)

    return _tool_ok(
        {
            "query": needle,
            "match": match_mode,
            "case_sensitive": bool(case_sensitive),
            "exported_only": bool(exported_only),
            "limit": int(limit),
            "count": len(results),
            "results": results,
        }
    )


def _tool_get_tree_outline(project_id: int, args: dict) -> dict:
    prefix = args.get("prefix")
    prefix_norm = ""
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")

    max_lines = _clamp_int(args.get("max_lines"), 1200, 100, 2000)
    max_depth_raw = args.get("max_depth")
    max_depth = None
    if max_depth_raw is not None:
        max_depth = _clamp_int(max_depth_raw, 10, 1, 20)

    with get_session() as s:
        q = select(FileNode.path).where(FileNode.project_id == project_id)
        if prefix_norm:
            like = f"{prefix_norm}/%"
            q = q.where((FileNode.path == prefix_norm) | (FileNode.path.like(like)))
        q = q.order_by(FileNode.path.asc())
        rows = s.exec(q).all()

    paths: list[str] = []
    for row in rows:
        p = row[0] if isinstance(row, (tuple, list)) else row
        if not isinstance(p, str) or not p:
            continue
        if max_depth is not None and len(p.split("/")) > max_depth:
            continue
        paths.append(p)

    outline = _tree_outline(paths, max_lines=max_lines)
    return _tool_ok(
        {
            "lines": outline.get("lines", []),
            "truncated": bool(outline.get("truncated")),
            "max_lines": int(outline.get("max_lines", max_lines)),
        }
    )


def _tool_project_summary(project_id: int, root: Path, args: dict) -> dict:
    with get_session() as s:
        nodes = s.exec(
            select(FileNode.path, FileNode.language, FileNode.loc, FileNode.complexity, FileNode.fan_in, FileNode.fan_out, FileNode.status)
            .where(FileNode.project_id == project_id)
            .order_by(FileNode.path)
        ).all()
    if not nodes:
        return _tool_error("not_indexed", "Project is not indexed. Run scan first.")
    summary = _compute_project_summary_facts(nodes)
    return _tool_ok(
        {
            "counts": summary["counts"],
            "hotspots": summary["hotspots"],
            "hubs_by_fan_in": summary["hubs_by_fan_in"],
            "module_map": summary["module_map"],
            "truncation": {
                "hotspots": bool(summary["hotspots_truncated"]),
                "hubs_by_fan_in": bool(summary["hubs_by_fan_in_truncated"]),
                "module_map": bool(summary["module_map_truncated"]),
            },
        }
    )


def _tool_search_text(project_id: int, root: Path, args: dict, *, max_file_chars: int) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return _tool_error("bad_args", "query is required")
    needle = query.strip()

    prefix = args.get("prefix")
    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    case_sensitive_raw = args.get("case_sensitive")
    case_sensitive = bool(case_sensitive_raw) if case_sensitive_raw is not None else False

    max_files = _clamp_int(args.get("max_files"), 200, 1, 2000)
    max_matches = _clamp_int(args.get("max_matches"), 50, 1, 500)
    context_chars = _clamp_int(args.get("context_chars"), 160, 40, 400)

    # Cap per-file read for search to avoid heavy IO (second pass limited by max_file_chars/SEARCH_INDEX_MAX_CHARS).
    scan_max_chars = max(200, min(int(max_file_chars), 50_000))
    index_scan_max_chars = min(SEARCH_INDEX_MAX_CHARS, scan_max_chars)

    paths: list[str] = []

    fts_query = _fts_query_from_substring(needle)
    if fts_query:
        try:
            sql = "SELECT path FROM filetext_fts WHERE filetext_fts MATCH :q AND project_id = :pid"
            params: dict[str, Any] = {"q": fts_query, "pid": int(project_id)}
            if prefix_norm:
                params["prefix"] = prefix_norm
                params["like"] = f"{prefix_norm}/%"
                sql += " AND (path = :prefix OR path LIKE :like)"
            sql += " ORDER BY bm25(filetext_fts) LIMIT :lim"
            params["lim"] = int(max_files)
            with get_session() as s:
                rows = s.execute(sa_text(sql), params).all()
            for row in rows:
                p = row[0] if isinstance(row, (tuple, list)) else row
                if isinstance(p, str) and p:
                    paths.append(p)
        except Exception:
            paths = []

    if not paths:
        with get_session() as s:
            q = select(FileNode.path).where(FileNode.project_id == project_id)
            if prefix_norm:
                like = f"{prefix_norm}/%"
                q = q.where((FileNode.path.like(like)) | (FileNode.path == prefix_norm))
            q = q.order_by(FileNode.fan_in.desc(), FileNode.path.asc()).limit(int(max_files))
            rows = s.exec(q).all()
        for row in rows:
            p = row[0] if isinstance(row, (tuple, list)) else row
            if isinstance(p, str) and p:
                paths.append(p)

    if not case_sensitive:
        needle_cmp = needle.lower()
    else:
        needle_cmp = needle

    matches: list[dict] = []
    scanned = 0
    matched_files: set[str] = set()
    truncated_files = 0

    for p in paths:
        if len(matches) >= max_matches:
            break
        try:
            abs_path, rel_norm = resolve_under_root(root, p, max_length=settings.max_rel_path_chars)
        except Exception:
            continue
        if not abs_path.exists() or not abs_path.is_file():
            continue
        try:
            with abs_path.open("r", encoding="utf-8", errors="replace") as f:
                text = f.read(int(scan_max_chars) + 1)
        except Exception:
            continue
        scanned += 1
        truncated_initial = len(text) > scan_max_chars
        if truncated_initial:
            text = text[:scan_max_chars]

        def _search_text(payload: str, *, truncated_flag: bool) -> bool:
            haystack = payload if case_sensitive else payload.lower()
            start_idx = 0
            found_any = False
            while True:
                if len(matches) >= max_matches:
                    break
                idx = haystack.find(needle_cmp, start_idx)
                if idx == -1:
                    break
                found_any = True
                matched_files.add(rel_norm)

                # Line/col (1-based)
                line = payload.count("\n", 0, idx) + 1
                last_nl = payload.rfind("\n", 0, idx)
                col = (idx - (last_nl + 1)) + 1 if last_nl != -1 else idx + 1

                half = max(10, context_chars // 2)
                s0 = max(0, idx - half)
                e0 = min(len(payload), idx + len(needle) + half)
                snippet = payload[s0:e0]

                matches.append(
                    {
                        "path": rel_norm,
                        "line": int(line),
                        "col": int(col),
                        "snippet": snippet,
                        "truncated_file": bool(truncated_flag),
                    }
                )

                step = max(1, len(needle_cmp))
                start_idx = idx + step
            return found_any

        truncated = truncated_initial
        matched = _search_text(text, truncated_flag=truncated)

        if truncated_initial and not matched and scan_max_chars < index_scan_max_chars:
            try:
                with abs_path.open("r", encoding="utf-8", errors="replace") as f:
                    text = f.read(int(index_scan_max_chars) + 1)
            except Exception:
                continue
            truncated = len(text) > index_scan_max_chars
            if truncated:
                text = text[:index_scan_max_chars]
            matched = _search_text(text, truncated_flag=truncated)

        if truncated:
            truncated_files += 1

    return _tool_ok(
        {
            "query": needle,
            "prefix": prefix_norm or "",
            "case_sensitive": bool(case_sensitive),
            "max_files": int(max_files),
            "max_matches": int(max_matches),
            "context_chars": int(context_chars),
            "scan_max_chars_per_file": int(scan_max_chars),
            "scanned_files": int(scanned),
            "matched_files": int(len(matched_files)),
            "truncated_files": int(truncated_files),
            "matches": matches,
        }
    )


def _tool_search_semantic(project_id: int, root: Path, args: dict, *, max_file_chars: int) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return _tool_error("bad_args", "query is required")

    prefix = args.get("prefix")
    prefix_norm: str | None = None
    if isinstance(prefix, str) and prefix.strip():
        prefix_norm = prefix.strip().replace("\\", "/").strip("/")
        if not prefix_norm:
            prefix_norm = None

    max_results = None
    if args.get("max_results") is not None:
        max_results = _clamp_int(
            args.get("max_results"),
            int(settings.embeddings_search_max_results),
            1,
            int(settings.embeddings_search_max_results),
        )

    semantic = search_semantic(
        project_id,
        root,
        query,
        max_results=max_results,
        prefix=prefix_norm,
    )
    results = semantic.get("results") if isinstance(semantic, dict) else None
    if isinstance(semantic, dict) and ("error" in semantic or not results):
        reason = ""
        if isinstance(semantic, dict):
            meta = semantic.get("meta")
            if isinstance(meta, dict):
                reason = str(meta.get("reason") or "")
            if not reason:
                reason = str(semantic.get("error") or "no_results")
        fallback_args: dict[str, Any] = {"query": query, "prefix": prefix_norm}
        if args.get("max_matches") is not None:
            fallback_args["max_matches"] = args.get("max_matches")
        if args.get("context_chars") is not None:
            fallback_args["context_chars"] = args.get("context_chars")
        text_result = _tool_search_text(project_id, root, fallback_args, max_file_chars=max_file_chars)
        if not text_result.get("ok"):
            return text_result
        text_out = text_result["data"]
        meta = text_out.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        meta["fallback_used"] = True
        meta["reason"] = reason
        text_out["meta"] = meta
        return _tool_ok(text_out)

    meta = semantic.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    meta["fallback_used"] = False
    semantic["meta"] = meta
    if not isinstance(semantic, dict):
        return _tool_error("semantic_failed", "semantic search returned invalid response")
    return _tool_ok(semantic)


def _tool_search_routes(project_id: int, args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str):
        query = ""
    query = query.strip()
    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    limit = _clamp_int(args.get("limit"), 50, 1, 500)

    try:
        with get_session() as s:
            q = select(ApiRoute).where(ApiRoute.project_id == project_id)
            if method_norm:
                q = q.where(ApiRoute.method == method_norm)
            if query:
                like = f"%{query}%"
                q = q.where((ApiRoute.path.like(like)) | (ApiRoute.handler_name.like(like)) | (ApiRoute.source_path.like(like)))
            q = q.order_by(ApiRoute.path.asc(), ApiRoute.method.asc()).limit(int(limit))
            rows = s.exec(q).all()
    except Exception as e:
        return _tool_error("db_error", "failed to query routes", {"reason": str(e)})

    out = [
        {
            "method": r.method,
            "path": r.path,
            "source_path": r.source_path,
            "handler_name": r.handler_name,
            "lineno": int(r.lineno or 0),
            "decorator": r.decorator,
        }
        for r in rows
    ]
    return _tool_ok({"query": query, "method": method_norm, "limit": int(limit), "count": len(out), "routes": out})


def _tool_search_api_calls(project_id: int, args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str):
        query = ""
    query = query.strip()
    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    limit = _clamp_int(args.get("limit"), 50, 1, 500)

    try:
        with get_session() as s:
            q = select(ApiCall).where(ApiCall.project_id == project_id)
            if method_norm:
                q = q.where(ApiCall.method == method_norm)
            if query:
                like = f"%{query}%"
                q = q.where((ApiCall.path.like(like)) | (ApiCall.source_path.like(like)))
            q = q.order_by(ApiCall.path.asc(), ApiCall.method.asc()).limit(int(limit))
            rows = s.exec(q).all()
    except Exception as e:
        return _tool_error("db_error", "failed to query api calls", {"reason": str(e)})

    out = [
        {
            "method": c.method,
            "path": c.path,
            "source_path": c.source_path,
            "lineno": int(c.lineno or 0),
            "client": c.client,
        }
        for c in rows
    ]
    return _tool_ok({"query": query, "method": method_norm, "limit": int(limit), "count": len(out), "calls": out})


def _tool_route_usages(project_id: int, args: dict) -> dict:
    path_q = args.get("path")
    if not isinstance(path_q, str) or not path_q.strip():
        return _tool_error("bad_args", "path is required")
    path_q = path_q.strip()
    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    route_limit = _clamp_int(args.get("route_limit"), 5, 1, 20)
    call_limit = _clamp_int(args.get("call_limit"), 12, 1, 50)

    # 1) candidate routes
    try:
        with get_session() as s:
            q = select(ApiRoute).where(ApiRoute.project_id == project_id)
            if method_norm:
                q = q.where(ApiRoute.method == method_norm)
            # exact first, then like
            exact = s.exec(q.where(ApiRoute.path == path_q).limit(int(route_limit))).all()
            routes = list(exact)
            if not routes:
                like = f"%{path_q}%"
                routes = s.exec(q.where(ApiRoute.path.like(like)).order_by(ApiRoute.path.asc()).limit(int(route_limit))).all()
    except Exception as e:
        return _tool_error("db_error", "failed to query routes", {"reason": str(e)})

    if not routes:
        return _tool_ok({"path": path_q, "method": method_norm, "routes_found": 0, "routes": []})

    prefix_map = _compute_prefix_map(project_id)
    results: list[dict] = []

    # 2) for each route, find compatible frontend calls
    for r in routes:
        inst = (str(r.decorator or "").split(".", 1)[0] if isinstance(r.decorator, str) else "") or ""
        node_key = (str(r.source_path or ""), inst)
        candidate_prefixes = prefix_map.get(node_key) or [""]

        # Expand route into possible full paths (include_router chains)
        full_variants: list[tuple[str, list[str]]] = []
        for pfx in candidate_prefixes:
            full_path = _join(pfx, str(r.path or ""))
            toks = split_skeleton(backend_path_skeleton(full_path))
            # keep even empty toks via fallback below; but prefer non-empty for matching
            if toks:
                full_variants.append((full_path, toks))

        if not full_variants:
            full_path = _join("", str(r.path or ""))
            full_variants = [(full_path, split_skeleton(backend_path_skeleton(full_path)))]

        # Use the "best" variant for initial prefix filtering (max static prefix)
        best_variant = full_variants[0]
        best_static_len = -1
        for full_path, toks in full_variants:
            static_len = 0
            for tok in toks:
                if tok in ("{}", "{*}"):
                    break
                static_len += 1
            if static_len > best_static_len:
                best_static_len = static_len
                best_variant = (full_path, toks)

        route_tokens = best_variant[1] if isinstance(best_variant[1], list) else []

        # use static prefix to narrow candidates
        static_prefix_parts: list[str] = []
        for tok in route_tokens:
            if tok in ("{}", "{*}"):
                break
            static_prefix_parts.append(tok)
        prefix_str = "/" + "/".join(static_prefix_parts) if static_prefix_parts else ""

        candidate_limit = min(2000, max(200, call_limit * 80))
        try:
            with get_session() as s:
                qc = select(ApiCall).where(ApiCall.project_id == project_id)
                # Prefer method match for HTTP; do not force it for WEBSOCKET routes.
                r_method = str(r.method or "").upper()
                if r_method and r_method != "WEBSOCKET":
                    qc = qc.where(ApiCall.method == r_method)
                if prefix_str:
                    qc = qc.where(ApiCall.path.like(prefix_str + "%"))
                call_rows = s.exec(
                    qc.order_by(ApiCall.path.asc(), ApiCall.source_path.asc(), ApiCall.lineno.asc()).limit(int(candidate_limit))
                ).all()
        except Exception as e:
            results.append(
                {
                    "route": {
                        "method": r.method,
                        "path": r.path,
                        "source_path": r.source_path,
                        "handler_name": r.handler_name,
                        "lineno": int(r.lineno or 0),
                        "decorator": r.decorator,
                    },
                    "error": "db_error",
                    "message": str(e),
                }
            )
            continue

        best_by_call: dict[tuple[str, int, str, str], dict] = {}
        for c in call_rows:
            call_tokens = split_skeleton(str(c.path_skeleton or ""))
            if not call_tokens:
                continue

            best_score = -1
            best_full = ""
            for full_path, rtoks in full_variants:
                if not patterns_compatible(rtoks, call_tokens):
                    continue
                sc = static_match_score(rtoks, call_tokens)
                if sc > best_score:
                    best_score = sc
                    best_full = full_path

            if best_score < 0:
                continue

            key = (str(c.source_path or ""), int(c.lineno or 0), str(c.path or ""), str(c.method or ""))
            prev = best_by_call.get(key)
            if (prev is None) or (int(prev.get("score", -1)) < best_score):
                best_by_call[key] = {
                    "method": str(c.method or "").upper(),
                    "path": str(c.path or ""),
                    "source_path": str(c.source_path or ""),
                    "lineno": int(c.lineno or 0),
                    "client": str(c.client or ""),
                    "score": int(best_score),
                    "matched_full_route_path": best_full,
                }

        matches = list(best_by_call.values())
        matches.sort(
            key=lambda x: (
                -int(x.get("score", 0)),
                str(x.get("path") or ""),
                str(x.get("source_path") or ""),
                int(x.get("lineno") or 0),
            )
        )
        truncated = len(matches) > call_limit
        matches_out = matches[:call_limit]

        results.append(
            {
                "route": {
                    "method": str(r.method or ""),
                    "path": str(r.path or ""),
                    "source_path": str(r.source_path or ""),
                    "handler_name": str(r.handler_name or ""),
                    "lineno": int(r.lineno or 0),
                    "decorator": str(r.decorator or ""),
                },
                "resolved_full_paths": [fp for fp, _ in full_variants],
                "matches_total": len(matches),
                "matches_truncated": bool(truncated),
                "matches": matches_out,
            }
        )

    return _tool_ok(
        {
            "path": path_q,
            "method": method_norm,
            "routes_found": len(results),
            "route_limit": int(route_limit),
            "call_limit": int(call_limit),
            "routes": results,
        }
    )


def _normalize_http_path(p: str) -> str:
    s = (p or "").strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        m = re.search(r"^https?://[^/]+(?P<path>/.*)$", s)
        if m:
            s = m.group("path")
    if not s.startswith("/"):
        s = "/" + s
    return s

def _prefix_norm(prefix: str | None, default: str = "/api") -> str:
    p = (prefix or "").strip()
    if not p:
        p = default
    if not p.startswith("/"):
        p = "/" + p
    if p != "/" and p.endswith("/"):
        p = p.rstrip("/")
    return p

def _method_norm(m: str | None) -> str:
    if isinstance(m, str) and m.strip():
        return m.strip().upper()
    return ""

def _prefix_key_from_segments(segs: list[str], k: int = 3) -> str:
    if not segs:
        return ""
    kk = max(1, min(int(k), 6))
    return "/".join(segs[:kk])

def _static_prefix_segs_from_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for t in tokens:
        if t in ("{}", "{*}"):
            break
        if t:
            out.append(t)
    return out

def _candidate_keys_from_path(path_norm: str) -> list[str]:
    parts = [x for x in (path_norm or "").split("/") if x]
    keys: list[str] = []
    for k in (3, 2, 1):
        key = _prefix_key_from_segments(parts, k=k)
        if key and key not in keys:
            keys.append(key)
    return keys

def _candidate_keys_from_static_prefix(tokens: list[str]) -> list[str]:
    segs = _static_prefix_segs_from_tokens(tokens)
    keys: list[str] = []
    for k in (3, 2, 1):
        key = _prefix_key_from_segments(segs, k=k)
        if key and key not in keys:
            keys.append(key)
    return keys

def _build_call_index(project_id: int, *, prefix: str, method_filter: str = "") -> tuple[list[ApiCall], dict[str, dict[str, list[dict]]]]:
    # returns (calls, index[method][key] = list of {id, tokens, path_norm, source_path, lineno, path})
    MAX_CALLS = 50_000
    with get_session() as s:
        q = select(ApiCall).where(ApiCall.project_id == project_id)
        if method_filter:
            q = q.where(ApiCall.method == method_filter)
        rows = s.exec(q.order_by(ApiCall.source_path.asc(), ApiCall.lineno.asc()).limit(int(MAX_CALLS))).all()

    idx: dict[str, dict[str, list[dict]]] = {}
    filtered: list[ApiCall] = []
    for c in rows:
        pnorm = _normalize_http_path(str(c.path or ""))
        if not pnorm:
            continue
        if prefix and not pnorm.startswith(prefix):
            continue
        tokens = split_skeleton(str(c.path_skeleton or ""))
        if not tokens:
            continue
        m = str(c.method or "").upper()
        if not m:
            continue
        filtered.append(c)
        keys = _candidate_keys_from_path(pnorm)
        if not keys:
            keys = [""]
        for k in keys:
            idx.setdefault(m, {}).setdefault(k, []).append(
                {
                    "id": int(getattr(c, "id", 0) or 0),
                    "tokens": tokens,
                    "path_norm": pnorm,
                    "path": str(c.path or ""),
                    "source_path": str(c.source_path or ""),
                    "lineno": int(c.lineno or 0),
                    "client": str(c.client or ""),
                }
            )
    return filtered, idx

def _build_route_patterns(
    project_id: int,
    *,
    prefix: str,
    method_filter: str = "",
) -> tuple[list[ApiRoute], dict[int, list[dict]], dict[str, dict[str, list[dict]]]]:
    # returns (routes, patterns_by_route_id, pattern_index[method][key] = list of patterns)
    MAX_ROUTES = 50_000
    prefix_map = _compute_prefix_map(project_id)

    # included set: (child_source_path, child_instance)
    with get_session() as s:
        inc_rows = s.exec(
            select(ApiInclude.child_source_path, ApiInclude.child_instance).where(ApiInclude.project_id == project_id)
        ).all()
    included: set[tuple[str, str]] = set()
    for row in inc_rows:
        if isinstance(row, (tuple, list)) and len(row) >= 2:
            cs, ci = row[0], row[1]
        else:
            continue
        if isinstance(cs, str) and cs and isinstance(ci, str) and ci:
            included.add((cs, ci))

    with get_session() as s:
        q = select(ApiRoute).where(ApiRoute.project_id == project_id)
        if method_filter:
            q = q.where(ApiRoute.method == method_filter)
        routes = s.exec(q.order_by(ApiRoute.source_path.asc(), ApiRoute.lineno.asc()).limit(int(MAX_ROUTES))).all()

    patterns_by_route: dict[int, list[dict]] = {}
    pindex: dict[str, dict[str, list[dict]]] = {}

    for r in routes:
        rid = int(getattr(r, "id", 0) or 0)
        method = str(r.method or "").upper()
        if not method:
            continue
        if prefix and not str(prefix).strip():
            pass
        # Determine instance name from decorator base (e.g. "router.get" -> "router")
        inst = ""
        if isinstance(r.decorator, str) and "." in r.decorator:
            inst = r.decorator.split(".", 1)[0]
        inst = inst or ""

        source_path = str(r.source_path or "")
        # Reachability heuristic: included somewhere OR instance is "app"
        reachable = bool((source_path, inst) in included) or (inst == "app")
        prefs = prefix_map.get((source_path, inst)) if reachable else None
        if not prefs:
            prefs = [""]

        local_path = str(r.path or "")
        if not local_path.startswith("/"):
            local_path = "/" + local_path if local_path else "/"

        variants: list[dict] = []
        for pfx in prefs:
            full_path = _join(pfx, local_path)
            if prefix and not full_path.startswith(prefix):
                continue
            skel = backend_path_skeleton(full_path)
            tokens = split_skeleton(skel)
            if not tokens:
                continue
            static_keys = _candidate_keys_from_static_prefix(tokens) or [""]
            variants.append(
                {
                    "route_id": rid,
                    "method": method,
                    "source_path": source_path,
                    "handler_name": str(r.handler_name or ""),
                    "lineno": int(r.lineno or 0),
                    "decorator": str(r.decorator or ""),
                    "local_path": str(r.path or ""),
                    "full_path": full_path,
                    "skeleton": skel,
                    "tokens": tokens,
                    "reachable": bool(reachable),
                    "static_keys": static_keys,
                }
            )
            for k in static_keys:
                pindex.setdefault(method, {}).setdefault(k, []).append(variants[-1])

        if variants:
            patterns_by_route[rid] = variants

    return routes, patterns_by_route, pindex

def _call_matches_any_pattern(call_tokens: list[str], candidates: list[dict]) -> bool:
    for p in candidates:
        rtoks = p.get("tokens") or []
        if isinstance(rtoks, list) and patterns_compatible(rtoks, call_tokens):
            return True
    return False

def _pattern_matches_any_call(pattern_tokens: list[str], candidates: list[dict]) -> bool:
    for c in candidates:
        ctoks = c.get("tokens") or []
        if isinstance(ctoks, list) and patterns_compatible(pattern_tokens, ctoks):
            return True
    return False

def _compute_api_coverage(project_id: int, *, prefix: str, method_filter: str = "") -> dict:
    calls, call_index = _build_call_index(project_id, prefix=prefix, method_filter=method_filter)
    routes, patterns_by_route, pattern_index = _build_route_patterns(project_id, prefix=prefix, method_filter=method_filter)

    # matched calls
    matched_call_ids: set[int] = set()
    for c in calls:
        cid = int(getattr(c, "id", 0) or 0)
        m = str(c.method or "").upper()
        pnorm = _normalize_http_path(str(c.path or ""))
        ctoks = split_skeleton(str(c.path_skeleton or ""))
        if not ctoks or not m or not pnorm:
            continue
        keys = _candidate_keys_from_path(pnorm) or [""]
        candidates: list[dict] = []
        for k in keys:
            candidates.extend(pattern_index.get(m, {}).get(k, []))
        if candidates and _call_matches_any_pattern(ctoks, candidates):
            matched_call_ids.add(cid)

    # matched routes (any variant matches any call)
    matched_route_ids: set[int] = set()
    for r in routes:
        rid = int(getattr(r, "id", 0) or 0)
        variants = patterns_by_route.get(rid) or []
        if not variants:
            continue
        ok = False
        for v in variants:
            method = str(v.get("method") or "")
            vtoks = v.get("tokens") or []
            if not method or not isinstance(vtoks, list) or not vtoks:
                continue
            # gather call candidates by keys
            candidates_calls: list[dict] = []
            for k in (v.get("static_keys") or [""]):
                candidates_calls.extend(call_index.get(method, {}).get(k, []))
            # fallback: allow broader match if no keyed candidates
            if not candidates_calls:
                candidates_calls = call_index.get(method, {}).get("", [])
            if candidates_calls and _pattern_matches_any_call(vtoks, candidates_calls):
                ok = True
                break
        if ok:
            matched_route_ids.add(rid)

    return {
        "prefix": prefix,
        "method_filter": method_filter,
        "routes": routes,
        "calls": calls,
        "matched_route_ids": matched_route_ids,
        "matched_call_ids": matched_call_ids,
        "patterns_by_route": patterns_by_route,
    }

def _tool_api_coverage_summary(project_id: int, args: dict) -> dict:
    prefix = _prefix_norm(args.get("prefix"), default="/api")
    method_filter = _method_norm(args.get("method"))
    limit_examples = _clamp_int(args.get("limit_examples"), 10, 0, 50)

    cov = _compute_api_coverage(project_id, prefix=prefix, method_filter=method_filter)
    routes: list[ApiRoute] = cov["routes"]
    calls: list[ApiCall] = cov["calls"]
    matched_routes: set[int] = cov["matched_route_ids"]
    matched_calls: set[int] = cov["matched_call_ids"]
    patterns_by_route: dict[int, list[dict]] = cov["patterns_by_route"]

    total_routes = len(routes)
    total_calls = len(calls)
    unmatched_routes_ids = [int(getattr(r, "id", 0) or 0) for r in routes if int(getattr(r, "id", 0) or 0) not in matched_routes]
    unmatched_calls_ids = [int(getattr(c, "id", 0) or 0) for c in calls if int(getattr(c, "id", 0) or 0) not in matched_calls]

    examples_routes: list[dict] = []
    if limit_examples > 0:
        for r in routes:
            rid = int(getattr(r, "id", 0) or 0)
            if rid in matched_routes:
                continue
            vars = patterns_by_route.get(rid) or []
            examples_routes.append(
                {
                    "method": str(r.method or ""),
                    "local_path": str(r.path or ""),
                    "source_path": str(r.source_path or ""),
                    "handler_name": str(r.handler_name or ""),
                    "lineno": int(r.lineno or 0),
                    "resolved_full_paths": [v.get("full_path") for v in vars[:5] if isinstance(v, dict)],
                    "reachable_hint": any(bool(v.get("reachable")) for v in vars if isinstance(v, dict)),
                }
            )
            if len(examples_routes) >= limit_examples:
                break

    examples_calls: list[dict] = []
    if limit_examples > 0:
        for c in calls:
            cid = int(getattr(c, "id", 0) or 0)
            if cid in matched_calls:
                continue
            examples_calls.append(
                {
                    "method": str(c.method or ""),
                    "path": str(c.path or ""),
                    "source_path": str(c.source_path or ""),
                    "lineno": int(c.lineno or 0),
                    "client": str(c.client or ""),
                }
            )
            if len(examples_calls) >= limit_examples:
                break

    return _tool_ok(
        {
            "prefix": prefix,
            "method_filter": method_filter,
            "counts": {
                "routes_total": total_routes,
                "calls_total": total_calls,
                "routes_matched": int(len(matched_routes)),
                "routes_unmatched": int(len(unmatched_routes_ids)),
                "calls_matched": int(len(matched_calls)),
                "calls_unmatched": int(len(unmatched_calls_ids)),
            },
            "examples": {
                "unmatched_routes": examples_routes,
                "unmatched_calls": examples_calls,
                "examples_limit": int(limit_examples),
            },
            "notes": (
                "Matching is template-based. For backend routes, include_router resolution is best-effort. "
                "Routes may be legitimately server-only; unmatched does not always mean a bug."
            ),
        }
    )

def _tool_unmatched_routes(project_id: int, args: dict) -> dict:
    prefix = _prefix_norm(args.get("prefix"), default="/api")
    method_filter = _method_norm(args.get("method"))
    limit = _clamp_int(args.get("limit"), 100, 1, 500)

    cov = _compute_api_coverage(project_id, prefix=prefix, method_filter=method_filter)
    routes: list[ApiRoute] = cov["routes"]
    matched_routes: set[int] = cov["matched_route_ids"]
    patterns_by_route: dict[int, list[dict]] = cov["patterns_by_route"]

    out: list[dict] = []
    for r in routes:
        rid = int(getattr(r, "id", 0) or 0)
        if rid in matched_routes:
            continue
        vars = patterns_by_route.get(rid) or []
        resolved = [v.get("full_path") for v in vars if isinstance(v, dict) and isinstance(v.get("full_path"), str)]
        resolved = list(dict.fromkeys([x for x in resolved if x]))
        reachable_hint = any(bool(v.get("reachable")) for v in vars if isinstance(v, dict))
        # small scaffold hint
        full_for_hint = resolved[0] if resolved else str(r.path or "")
        try:
            tpl = build_frontend_snippet(str(r.method or "GET"), str(full_for_hint), handler_name=str(r.handler_name or ""))
            scaffold = {
                "path_template": tpl.get("path_template"),
                "function_name": tpl.get("function_name"),
                "uses_encodePath": bool(tpl.get("uses_encodePath")),
                "suggested_file": suggest_frontend_module_file(str(full_for_hint)),
            }
        except Exception:
            scaffold = {}

        out.append(
            {
                "method": str(r.method or ""),
                "local_path": str(r.path or ""),
                "resolved_full_paths": resolved[:5],
                "source_path": str(r.source_path or ""),
                "handler_name": str(r.handler_name or ""),
                "lineno": int(r.lineno or 0),
                "decorator": str(r.decorator or ""),
                "reachable_hint": bool(reachable_hint),
                "frontend_scaffold_hint": scaffold,
            }
        )
        if len(out) >= limit:
            break

    return _tool_ok(
        {"prefix": prefix, "method_filter": method_filter, "count": len(out), "limit": int(limit), "routes": out}
    )

def _tool_unmatched_calls(project_id: int, args: dict) -> dict:
    prefix = _prefix_norm(args.get("prefix"), default="/api")
    method_filter = _method_norm(args.get("method"))
    limit = _clamp_int(args.get("limit"), 100, 1, 500)

    cov = _compute_api_coverage(project_id, prefix=prefix, method_filter=method_filter)
    calls: list[ApiCall] = cov["calls"]
    matched_calls: set[int] = cov["matched_call_ids"]

    out: list[dict] = []
    for c in calls:
        cid = int(getattr(c, "id", 0) or 0)
        if cid in matched_calls:
            continue
        out.append(
            {
                "method": str(c.method or ""),
                "path": str(c.path or ""),
                "path_skeleton": str(c.path_skeleton or ""),
                "source_path": str(c.source_path or ""),
                "lineno": int(c.lineno or 0),
                "client": str(c.client or ""),
            }
        )
        if len(out) >= limit:
            break

    return _tool_ok(
        {"prefix": prefix, "method_filter": method_filter, "count": len(out), "limit": int(limit), "calls": out}
    )


def _join(prefix: str, path: str) -> str:
    pfx = (prefix or "").strip()
    pth = (path or "").strip()
    if not pfx:
        return pth if pth.startswith("/") else ("/" + pth if pth else "/")
    if not pfx.startswith("/"):
        pfx = "/" + pfx
    if pfx.endswith("/") and pfx != "/":
        pfx = pfx.rstrip("/")
    if not pth:
        return pfx
    if not pth.startswith("/"):
        pth = "/" + pth
    if pfx == "/":
        return pth
    return pfx + pth


def _compute_prefix_map(project_id: int) -> dict[tuple[str, str], list[str]]:
    edges: dict[tuple[str, str], list[tuple[tuple[str, str], str]]] = {}
    nodes: set[tuple[str, str]] = set()
    child_set: set[tuple[str, str]] = set()

    with get_session() as s:
        rows = s.exec(select(ApiInclude).where(ApiInclude.project_id == project_id)).all()
    for inc in rows:
        ps = str(inc.parent_source_path or "")
        pi = str(inc.parent_instance or "")
        cs = str(inc.child_source_path or "")
        ci = str(inc.child_instance or "")
        if not ps or not pi or not cs or not ci:
            continue
        parent = (ps, pi)
        child = (cs, ci)
        pref = str(inc.prefix or "")
        nodes.add(parent)
        nodes.add(child)
        child_set.add(child)
        edges.setdefault(parent, []).append((child, pref))

    roots = [n for n in nodes if n not in child_set]
    if not roots:
        roots = list(nodes)

    prefixes: dict[tuple[str, str], list[str]] = {r: [""] for r in roots}
    MAX_DEPTH = 8
    queue: list[tuple[tuple[str, str], str, int]] = [(r, "", 0) for r in roots]
    seen_states: set[tuple[tuple[str, str], str, int]] = set()

    while queue:
        node, cur_pref, depth = queue.pop(0)
        if depth > MAX_DEPTH:
            continue
        nxt_edges = edges.get(node) or []
        for child, add_pref in nxt_edges:
            new_pref = _join(cur_pref, add_pref)
            lst = prefixes.setdefault(child, [])
            if new_pref not in lst:
                lst.append(new_pref)
                if len(lst) > 12:
                    lst[:] = lst[:12]
            st = (child, new_pref, depth + 1)
            if st in seen_states:
                continue
            seen_states.add(st)
            queue.append((child, new_pref, depth + 1))

    return prefixes


def _tool_suggest_endpoint_location(project_id: int, args: dict) -> dict:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        return _tool_error("bad_args", "path is required")
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path

    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    limit = _clamp_int(args.get("limit"), 8, 1, 20)

    # heuristic: reuse existing module file where similar routes exist
    like = f"%{path.split('/', 3)[2]}%" if path.startswith("/api/") and len(path.split("/")) > 2 else "%"

    with get_session() as s:
        q = select(ApiRoute.source_path, ApiRoute.decorator, ApiRoute.path).where(ApiRoute.project_id == project_id)
        if method_norm:
            q = q.where(ApiRoute.method == method_norm)
        # prefer exact prefix match when /api/<module>
        if path.startswith("/api/"):
            parts = [x for x in path.split("/") if x]
            if len(parts) >= 2:
                mod = parts[1]
                pref = f"/api/{mod}"
                q = q.where(ApiRoute.path.like(pref + "%"))
        else:
            q = q.where(ApiRoute.path.like(like))
        rows = s.exec(q).all()

    counts: dict[str, int] = {}
    routers_by_file: dict[str, set[str]] = {}
    sample_paths: dict[str, list[str]] = {}

    for row in rows:
        if isinstance(row, (tuple, list)) and len(row) >= 3:
            src, deco, pth = row[0], row[1], row[2]
        else:
            src, deco, pth = "", "", ""
        if not isinstance(src, str) or not src:
            continue
        counts[src] = counts.get(src, 0) + 1
        base = ""
        if isinstance(deco, str) and "." in deco:
            base = deco.split(".", 1)[0]
        if base:
            routers_by_file.setdefault(src, set()).add(base)
        if isinstance(pth, str) and pth:
            sample_paths.setdefault(src, [])
            if len(sample_paths[src]) < 5:
                sample_paths[src].append(pth)

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]
    candidates: list[dict] = []

    # include coverage hint: is this router included anywhere?
    with get_session() as s:
        inc_rows = s.exec(select(ApiInclude.child_source_path, ApiInclude.child_instance).where(ApiInclude.project_id == project_id)).all()
    included = set()
    for r in inc_rows:
        if isinstance(r, (tuple, list)) and len(r) >= 2:
            cs, ci = r[0], r[1]
        else:
            continue
        if isinstance(cs, str) and cs and isinstance(ci, str) and ci:
            included.add((cs, ci))

    for src, cnt in ranked:
        routers = sorted(list(routers_by_file.get(src, set())))
        cov = []
        for rname in routers:
            cov.append({"router": rname, "included_somewhere": (src, rname) in included})
        candidates.append(
            {
                "source_path": src,
                "score": int(cnt),
                "router_instances": routers,
                "include_coverage": cov,
                "sample_routes": sample_paths.get(src, []),
            }
        )

    return _tool_ok({"path": path, "method": method_norm, "candidates": candidates, "count": len(candidates)})


def _tool_suggest_frontend_client(project_id: int, root: Path, args: dict) -> dict:
    path_q = args.get("path")
    if not isinstance(path_q, str) or not path_q.strip():
        return _tool_error("bad_args", "path is required")
    path_q = path_q.strip()
    if not path_q.startswith("/"):
        path_q = "/" + path_q
    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    limit = _clamp_int(args.get("limit"), 5, 1, 10)

    # Find candidate routes (cheap prefilter by tokens)
    tokens = [t for t in path_q.split("/") if t and not t.startswith("{")]
    needle = tokens[-1] if tokens else path_q
    like = f"%{needle}%"

    with get_session() as s:
        q = select(ApiRoute).where(ApiRoute.project_id == project_id)
        if method_norm:
            q = q.where(ApiRoute.method == method_norm)
        q = q.where(ApiRoute.path.like(like)).order_by(ApiRoute.path.asc()).limit(200)
        routes = s.exec(q).all()

    if not routes:
        return _tool_ok(
            {
                "path": path_q,
                "method": method_norm,
                "matched": None,
                "note": "No matching backend routes found. Run Scan or adjust query.",
            }
        )

    prefix_map = _compute_prefix_map(project_id)
    query_tokens = split_skeleton(backend_path_skeleton(path_q))

    best = None
    best_score = -1
    best_full = ""
    for r in routes:
        inst = (str(r.decorator or "").split(".", 1)[0] if isinstance(r.decorator, str) else "") or ""
        node_key = (str(r.source_path or ""), inst)
        prefs = prefix_map.get(node_key) or [""]
        for pfx in prefs:
            full_path = _join(pfx, str(r.path or ""))
            rtoks = split_skeleton(backend_path_skeleton(full_path))
            if not patterns_compatible(query_tokens, rtoks):
                continue
            sc = static_match_score(query_tokens, rtoks)
            if sc > best_score:
                best_score = sc
                best = r
                best_full = full_path

    if best is None:
        # fallback: just use first route record as-is
        best = routes[0]
        best_full = str(best.path or "")

    # Build TS snippet
    method_eff = str(best.method or "").upper() or (method_norm or "GET")
    handler_name = str(best.handler_name or "")
    snippet_info = build_frontend_snippet(method_eff, best_full, handler_name=handler_name)

    suggested_file = suggest_frontend_module_file(best_full)
    file_exists = False
    try:
        abs_p, rel_norm = resolve_under_root(root, suggested_file, max_length=settings.max_rel_path_chars)
        file_exists = abs_p.exists() and abs_p.is_file()
    except Exception:
        file_exists = False

    return _tool_ok(
        {
            "input": {"path": path_q, "method": method_norm},
            "matched_route": {
                "method": method_eff,
                "path": str(best.path or ""),
                "source_path": str(best.source_path or ""),
                "handler_name": handler_name,
                "lineno": int(best.lineno or 0),
                "decorator": str(best.decorator or ""),
            },
            "resolved_full_path": best_full,
            "frontend": {
                "suggested_file": suggested_file,
                "file_exists": bool(file_exists),
                "function_name": snippet_info.get("function_name"),
                "uses_encodePath": bool(snippet_info.get("uses_encodePath")),
                "path_template": snippet_info.get("path_template"),
                "path_params": snippet_info.get("path_params"),
                "snippet": snippet_info.get("snippet"),
                "note": (
                    "Snippet is a scaffold. To apply, modify the suggested file and export it from frontend/src/api/index.ts if needed."
                ),
            },
        }
    )

def _tool_impact_route_change(project_id: int, args: dict) -> dict:
    old_path = args.get("old_path")
    new_path = args.get("new_path")
    if not isinstance(old_path, str) or not old_path.strip():
        return _tool_error("bad_args", "old_path is required")
    if not isinstance(new_path, str) or not new_path.strip():
        return _tool_error("bad_args", "new_path is required")
    old_path = old_path.strip()
    new_path = new_path.strip()
    if not old_path.startswith("/"):
        old_path = "/" + old_path
    if not new_path.startswith("/"):
        new_path = "/" + new_path

    old_method = args.get("old_method")
    new_method = args.get("new_method")
    old_m = (str(old_method).strip().upper() if isinstance(old_method, str) and old_method.strip() else "")
    new_m = (str(new_method).strip().upper() if isinstance(new_method, str) and new_method.strip() else "")
    limit = _clamp_int(args.get("limit"), 200, 1, 500)

    old_skel = backend_path_skeleton(old_path)
    new_skel = backend_path_skeleton(new_path)
    old_tokens = split_skeleton(old_skel)
    new_tokens = split_skeleton(new_skel)

    # narrow candidate calls by static prefix of old path
    static_prefix_parts: list[str] = []
    for tok in old_tokens:
        if tok in ("{}", "{*}"):
            break
        static_prefix_parts.append(tok)
    prefix_str = "/" + "/".join(static_prefix_parts) if static_prefix_parts else ""

    candidate_limit = 5000
    try:
        with get_session() as s:
            q = select(ApiCall).where(ApiCall.project_id == project_id)
            if old_m:
                q = q.where(ApiCall.method == old_m)
            if prefix_str:
                q = q.where(ApiCall.path.like(prefix_str + "%"))
            calls = s.exec(q.order_by(ApiCall.source_path.asc(), ApiCall.lineno.asc()).limit(int(candidate_limit))).all()
    except Exception as e:
        return _tool_error("db_error", "failed to query api calls", {"reason": str(e)})

    impacted: list[dict] = []
    matched_old = 0
    still_ok = 0
    needs_path = 0
    needs_method = 0
    needs_both = 0

    for c in calls:
        call_tokens = split_skeleton(str(c.path_skeleton or ""))
        if not call_tokens:
            continue

        # old match must hold (and method filter already applied if old_m)
        if not patterns_compatible(old_tokens, call_tokens):
            continue

        matched_old += 1
        call_m = str(c.method or "").upper()
        matches_new = patterns_compatible(new_tokens, call_tokens)
        method_ok = True
        if new_m:
            method_ok = (call_m == new_m)

        score_old = static_match_score(old_tokens, call_tokens)
        score_new = static_match_score(new_tokens, call_tokens) if matches_new else 0

        if matches_new and method_ok:
            status = "still_ok"
            still_ok += 1
        elif matches_new and not method_ok:
            status = "method_update_needed"
            needs_method += 1
        elif (not matches_new) and method_ok:
            status = "path_update_needed"
            needs_path += 1
        else:
            status = "path_and_method_update_needed"
            needs_both += 1

        impacted.append(
            {
                "status": status,
                "call": {
                    "method": call_m,
                    "path": str(c.path or ""),
                    "source_path": str(c.source_path or ""),
                    "lineno": int(c.lineno or 0),
                    "client": str(c.client or ""),
                },
                "scores": {"old": int(score_old), "new": int(score_new)},
            }
        )

    impacted.sort(
        key=lambda x: (
            x["status"] != "path_and_method_update_needed",
            x["status"] != "path_update_needed",
            x["status"] != "method_update_needed",
            -int(x.get("scores", {}).get("old", 0)),
            str(x.get("call", {}).get("source_path") or ""),
            int(x.get("call", {}).get("lineno") or 0),
        )
    )
    truncated = len(impacted) > limit
    impacted_out = impacted[:limit]

    # recommended template for the new path (for frontend wrapper)
    try:
        method_for_tpl = new_m or old_m or "GET"
        tpl_info = build_frontend_snippet(method_for_tpl, new_path, handler_name=None)
        tpl_hint = {
            "method": method_for_tpl,
            "path_template": tpl_info.get("path_template"),
            "uses_encodePath": bool(tpl_info.get("uses_encodePath")),
            "path_params": tpl_info.get("path_params"),
        }
    except Exception:
        tpl_hint = {}

    return _tool_ok(
        {
            "input": {"old_path": old_path, "new_path": new_path, "old_method": old_m, "new_method": new_m},
            "skeletons": {"old": old_skel, "new": new_skel},
            "counts": {
                "candidate_calls_scanned": int(len(calls)),
                "calls_matching_old": int(matched_old),
                "still_ok": int(still_ok),
                "needs_path_update": int(needs_path),
                "needs_method_update": int(needs_method),
                "needs_path_and_method_update": int(needs_both),
                "returned": int(len(impacted_out)),
                "truncated": bool(truncated),
                "limit": int(limit),
            },
            "new_frontend_template_hint": tpl_hint,
            "impacted_calls": impacted_out,
        }
    )

def _validate_tool_result(name: str, result: Any) -> dict:
    if not isinstance(result, dict):
        raise RuntimeError(f"Tool {name} returned non-dict result")
    for key in ("ok", "data", "error"):
        if key not in result:
            raise RuntimeError(f"Tool {name} result missing key '{key}'")
    ok = result.get("ok")
    if not isinstance(ok, bool):
        raise RuntimeError(f"Tool {name} result has non-bool ok")
    if ok:
        if not isinstance(result.get("data"), dict):
            raise RuntimeError(f"Tool {name} ok result missing data dict")
        if result.get("error") is not None:
            raise RuntimeError(f"Tool {name} ok result must have error=None")
        return result
    if result.get("data") is not None:
        raise RuntimeError(f"Tool {name} error result must have data=None")
    err = result.get("error")
    if not isinstance(err, dict):
        raise RuntimeError(f"Tool {name} error result missing error dict")
    if not isinstance(err.get("code"), str) or not err.get("code"):
        raise RuntimeError(f"Tool {name} error result missing error.code")
    if not isinstance(err.get("message"), str) or not err.get("message"):
        raise RuntimeError(f"Tool {name} error result missing error.message")
    return result

def _dispatch_tool(project_id: int, root: Path, meta: AgenticMeta, name: str, args: dict, *, max_file_chars: int) -> dict:
    if name == "plan_retrieval":
        meta.retrieval_plan = dict(args) if isinstance(args, dict) else None
        return _validate_tool_result(name, _tool_ok({"stored": True}))
    plan_ready = bool(meta.retrieval_plan) or any(
        entry.get("name") == "plan_retrieval" and entry.get("status") == "ok"
        for entry in meta.tool_trace
        if isinstance(entry, dict)
    )
    if not plan_ready:
        return _validate_tool_result(
            name,
            _tool_error("policy_violation", "Перед использованием инструментов нужно вызвать plan_retrieval."),
        )
    if name == "get_file":
        allowed = any(
            entry.get("name") in ("search_paths", "search_symbols", "search_text", "search_semantic")
            and entry.get("status") == "ok"
            for entry in meta.tool_trace
            if isinstance(entry, dict)
        )
        if not allowed:
            return _validate_tool_result(
                name,
                _tool_error(
                    "policy_violation",
                    "Перед get_file нужно выполнить search_paths, search_symbols, search_text или search_semantic.",
                ),
            )
        return _validate_tool_result(name, _tool_get_file(project_id, root, meta, args, max_file_chars=max_file_chars))
    if name == "get_file_lines":
        return _validate_tool_result(name, _tool_get_file_lines(project_id, root, meta, args, max_file_chars=max_file_chars))
    if name == "get_contract":
        return _validate_tool_result(name, _tool_get_contract(project_id, root, meta, args))
    if name == "get_symbol":
        return _validate_tool_result(name, _tool_get_symbol(project_id, root, meta, args))
    if name == "get_node":
        return _validate_tool_result(name, _tool_get_node(project_id, root, args))
    if name == "get_neighbors":
        return _validate_tool_result(name, _tool_get_neighbors(project_id, root, args))
    if name == "search_paths":
        return _validate_tool_result(name, _tool_search_paths(project_id, args))
    if name == "search_tests":
        return _validate_tool_result(name, _tool_search_tests(project_id, args))
    if name == "search_symbols":
        return _validate_tool_result(name, _tool_search_symbols(project_id, args))
    if name == "get_tree_outline":
        return _validate_tool_result(name, _tool_get_tree_outline(project_id, args))
    if name == "project_summary":
        return _validate_tool_result(name, _tool_project_summary(project_id, root, args))
    if name == "search_text":
        return _validate_tool_result(name, _tool_search_text(project_id, root, args, max_file_chars=max_file_chars))
    if name == "search_semantic":
        return _validate_tool_result(name, _tool_search_semantic(project_id, root, args, max_file_chars=max_file_chars))
    if name == "search_routes":
        return _validate_tool_result(name, _tool_search_routes(project_id, args))
    if name == "search_api_calls":
        return _validate_tool_result(name, _tool_search_api_calls(project_id, args))
    if name == "route_usages":
        return _validate_tool_result(name, _tool_route_usages(project_id, args))
    if name == "suggest_endpoint_location":
        return _validate_tool_result(name, _tool_suggest_endpoint_location(project_id, args))
    if name == "suggest_frontend_client":
        return _validate_tool_result(name, _tool_suggest_frontend_client(project_id, root, args))
    if name == "impact_route_change":
        return _validate_tool_result(name, _tool_impact_route_change(project_id, args))
    if name == "api_coverage_summary":
        return _validate_tool_result(name, _tool_api_coverage_summary(project_id, args))
    if name == "unmatched_routes":
        return _validate_tool_result(name, _tool_unmatched_routes(project_id, args))
    if name == "unmatched_calls":
        return _validate_tool_result(name, _tool_unmatched_calls(project_id, args))
    if name == "compare_api_contract":
        return _validate_tool_result(name, _tool_compare_api_contract(project_id, root, args))
    if name == "suggest_contract_fix":
        return _validate_tool_result(name, _tool_suggest_contract_fix(project_id, root, meta, args))
    if name == "suggest_api_fix":
        return _validate_tool_result(name, _tool_suggest_api_fix(project_id, root, meta, args))
    return _validate_tool_result(name, _tool_error("unknown_tool", f"Unknown tool: {name}"))


def _ts_type_to_py_literal(ts_type: str) -> str:
    t = (ts_type or "").strip()
    if not t:
        return "None"
    # union: prefer first non-null/undefined
    parts = [p.strip() for p in t.split("|") if p.strip()]
    parts2 = [p for p in parts if p not in ("null", "undefined", "void")]
    base = parts2[0] if parts2 else ""
    b = base.lower()
    if "string" in b:
        return '""'
    if "number" in b or "bigint" in b:
        return "0"
    if "boolean" in b:
        return "False"
    if b.endswith("[]") or b.startswith("array<"):
        return "[]"
    if b.startswith("record<") or b.startswith("{") or b.endswith("}"):
        return "{}"
    return "None"


def _tool_suggest_api_fix(project_id: int, root: Path, meta: AgenticMeta, args: dict) -> dict:
    path_q = args.get("path")
    if not isinstance(path_q, str) or not path_q.strip():
        return _tool_error("bad_args", "path is required")
    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    route_limit = _clamp_int(args.get("route_limit"), 1, 1, 3)
    call_limit = _clamp_int(args.get("call_limit"), 3, 1, 5)
    include_backend = bool(args.get("include_backend_response")) if args.get("include_backend_response") is not None else True
    max_files = _clamp_int(args.get("max_files"), 12, 1, 20)

    report_result = _tool_compare_api_contract(
        project_id, root, {"path": path_q, "method": method_norm or None, "route_limit": route_limit, "call_limit": call_limit}
    )
    if not report_result.get("ok"):
        return report_result
    report = report_result["data"]
    if not isinstance(report.get("routes"), list) or not report["routes"]:
        return _tool_ok(
            {"input": {"path": path_q, "method": method_norm}, "patch_unified_diff": "", "files": [], "notes": ["no_routes_or_calls_found"]}
        )

    # In-memory file edit buffers
    orig: dict[str, str] = {}
    cur: dict[str, str] = {}
    notes: list[str] = []
    reasons: dict[str, list[str]] = {}

    def ensure_loaded(rel_path: str) -> str | None:
        if not isinstance(rel_path, str) or not rel_path.strip():
            return None
        rp = rel_path.strip()
        if rp in cur:
            return rp
        rr = _read_text_under_root(root, rp)
        if not rr:
            notes.append(f"file_not_readable:{rp}")
            return None
        rel_norm, _abs, txt = rr
        orig[rel_norm] = txt
        cur[rel_norm] = txt
        meta.full_file_paths.add(rel_norm)
        return rel_norm

    def mark_reason(path: str, reason: str) -> None:
        if not path:
            return
        reasons.setdefault(path, [])
        if reason not in reasons[path]:
            reasons[path].append(reason)

    # For backend response patches: accumulate per (backend_file, handler) keys->literal
    backend_acc: dict[tuple[str, str], dict[str, str]] = {}

    # Iterate compare report
    for ritem in report["routes"]:
        if not isinstance(ritem, dict):
            continue
        route = ritem.get("route")
        if not isinstance(route, dict):
            continue
        r_method = str(route.get("method") or "").upper() or (method_norm or "GET")
        r_src = str(route.get("source_path") or "")
        r_handler = str(route.get("handler_name") or "")

        fcalls = ritem.get("frontend_calls")
        if not isinstance(fcalls, list):
            continue

        for f in fcalls:
            if not isinstance(f, dict):
                continue
            call = f.get("call")
            meta_obj = f.get("meta")
            comp = f.get("comparison")
            if not isinstance(call, dict):
                continue
            c_src = str(call.get("source_path") or "")
            c_method = str(call.get("method") or "").upper() or r_method

            wrapper_name = ""
            wrapper_body_type = ""
            wrapper_resp_type = ""
            if isinstance(meta_obj, dict):
                wrapper_name = str(meta_obj.get("wrapper_name") or "")
                wrapper_body_type = str(meta_obj.get("wrapper_body_type") or "")
                wrapper_resp_type = str(meta_obj.get("wrapper_response_type") or "")

            # ---- FRONTEND wrapper fix (path params + path template)
            missing_pp = []
            if isinstance(comp, dict):
                missing_pp = comp.get("path_params_missing_in_wrapper") or []
            if missing_pp and wrapper_name and c_src:
                # Use resolved full path for template if present, else local route path
                full_path = ""
                rfp = ritem.get("resolved_full_paths")
                if isinstance(rfp, list) and rfp and isinstance(rfp[0], str):
                    full_path = str(rfp[0] or "").strip()
                if not full_path:
                    full_path = str(route.get("path") or "")

                tpl = str(build_frontend_snippet(r_method, full_path, handler_name=wrapper_name).get("path_template") or "")
                add_params = []
                for pp in missing_pp:
                    if not isinstance(pp, dict):
                        continue
                    fe = str(pp.get("frontend_expected") or "").strip()
                    be = str(pp.get("backend") or "").strip()
                    nm = fe or be
                    if not nm:
                        continue
                    ts_type = "number" if (be.lower().endswith("id") or be.lower() == "id" or nm.lower().endswith("id")) else "string"
                    add_params.append({"name": nm, "type": ts_type})

                fp = ensure_loaded(c_src)
                if fp:
                    new_txt, changed, warns = ts_patch_wrapper_function(
                        cur[fp],
                        fn_name=wrapper_name,
                        http_method=c_method,
                        new_path_literal=tpl,
                        add_params=add_params,
                    )
                    if changed:
                        cur[fp] = new_txt
                        mark_reason(fp, "frontend_wrapper_path_params_and_template")
                    if warns:
                        notes.extend([f"wrapper:{wrapper_name}:{w}" for w in warns])

            # ---- FRONTEND body type fix (missing required fields)
            body = comp.get("body") if isinstance(comp, dict) else None
            if isinstance(body, dict) and wrapper_body_type:
                missing_body = body.get("missing_in_frontend") if isinstance(body.get("missing_in_frontend"), list) else []
                if missing_body:
                    with get_session() as s:
                        td = s.exec(
                            select(TsTypeDef).where(TsTypeDef.project_id == project_id, TsTypeDef.name == wrapper_body_type)
                        ).first()
                    if td and isinstance(td.source_path, str) and td.source_path:
                        fp = ensure_loaded(td.source_path)
                        if fp:
                            new_txt, changed, _status = ts_add_fields_to_typedef(
                                cur[fp],
                                wrapper_body_type,
                                [{"name": k, "type": ""} for k in missing_body if isinstance(k, str) and k],
                                optional=False,
                            )
                            if changed:
                                cur[fp] = new_txt
                                mark_reason(fp, f"frontend_body_type_add_missing:{wrapper_body_type}")
                    else:
                        notes.append(f"typedef_not_found_for_body_type:{wrapper_body_type}")

            # ---- FRONTEND response type fix (backend keys missing in TS)
            resp = comp.get("response") if isinstance(comp, dict) else None
            if isinstance(resp, dict) and wrapper_resp_type:
                missing_resp = resp.get("missing_in_frontend") if isinstance(resp.get("missing_in_frontend"), list) else []
                if missing_resp:
                    with get_session() as s:
                        td = s.exec(
                            select(TsTypeDef).where(TsTypeDef.project_id == project_id, TsTypeDef.name == wrapper_resp_type)
                        ).first()
                    if td and isinstance(td.source_path, str) and td.source_path:
                        fp = ensure_loaded(td.source_path)
                        if fp:
                            new_txt, changed, _status = ts_add_fields_to_typedef(
                                cur[fp],
                                wrapper_resp_type,
                                [{"name": k, "type": ""} for k in missing_resp if isinstance(k, str) and k],
                                optional=True,
                            )
                            if changed:
                                cur[fp] = new_txt
                                mark_reason(fp, f"frontend_response_type_add_missing_optional:{wrapper_resp_type}")
                    else:
                        notes.append(f"typedef_not_found_for_response_type:{wrapper_resp_type}")

            # ---- BACKEND response fix (frontend expects extra keys not present in backend)
            if include_backend and isinstance(resp, dict) and r_src and r_handler:
                extra_front = resp.get("extra_in_frontend") if isinstance(resp.get("extra_in_frontend"), list) else []
                if extra_front:
                    # get field types from TS response typedef if possible
                    field_types: dict[str, str] = {}
                    if wrapper_resp_type:
                        with get_session() as s:
                            td = s.exec(
                                select(TsTypeDef).where(TsTypeDef.project_id == project_id, TsTypeDef.name == wrapper_resp_type)
                            ).first()
                        if td and isinstance(td.fields_json, str):
                            try:
                                flds = json.loads(td.fields_json or "[]")
                            except Exception:
                                flds = []
                            if isinstance(flds, list):
                                for fld in flds:
                                    if isinstance(fld, dict):
                                        nm = str(fld.get("name") or "")
                                        tp = str(fld.get("type") or "")
                                        if nm:
                                            field_types[nm] = tp

                    key = (r_src, r_handler)
                    acc = backend_acc.setdefault(key, {})
                    for k in extra_front:
                        if not isinstance(k, str) or not k:
                            continue
                        lit = _ts_type_to_py_literal(field_types.get(k, ""))
                        acc.setdefault(k, lit)

        # cap file count (best-effort)
        if len(cur) >= max_files:
            notes.append("max_files_reached")
            break
    # Apply backend patches
    if include_backend:
        for (src, handler), keys_map in backend_acc.items():
            fp = ensure_loaded(src)
            if not fp:
                continue
            new_txt, changed, warns = py_add_keys_to_function_return_dicts(
                cur[fp], function_name=handler, keys_to_add=keys_map
            )
            if changed:
                cur[fp] = new_txt
                mark_reason(fp, f"backend_response_add_missing_keys_in_return_dicts:{handler}")
            else:
                if warns:
                    notes.extend([f"backend:{handler}:{w}" for w in warns])
                else:
                    notes.append(f"backend:{handler}:no_changes")

    # Build diffs
    diffs: list[str] = []
    files: list[dict] = []
    for fp, old_txt in orig.items():
        new_txt = cur.get(fp, old_txt)
        if new_txt != old_txt:
            d = _unified_diff(fp, old_txt, new_txt)
            if d.strip():
                diffs.append(d)
                files.append({"path": fp, "reasons": reasons.get(fp, [])})

    patch_text = "\n".join([d.rstrip("\n") for d in diffs]).strip() + ("\n" if diffs else "")

    return _tool_ok(
        {
            "input": {
                "path": path_q,
                "method": method_norm,
                "route_limit": int(route_limit),
                "call_limit": int(call_limit),
                "include_backend_response": bool(include_backend),
                "max_files": int(max_files),
            },
            "files_modified": files,
            "patch_unified_diff": patch_text,
            "notes": notes[:200],
        }
    )

def _read_text_under_root(root: Path, rel_path: str) -> tuple[str, str, str] | None:
    try:
        abs_p, rel_norm = resolve_under_root(root, rel_path, max_length=settings.max_rel_path_chars)
    except Exception:
        return None
    if not abs_p.exists() or not abs_p.is_file():
        return None
    try:
        txt = abs_p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return (rel_norm, str(abs_p), txt)


def _tool_suggest_contract_fix(project_id: int, root: Path, meta: AgenticMeta, args: dict) -> dict:
    # 1) Get compare report
    path_q = args.get("path")
    if not isinstance(path_q, str) or not path_q.strip():
        return _tool_error("bad_args", "path is required")
    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    route_limit = _clamp_int(args.get("route_limit"), 1, 1, 5)
    call_limit = _clamp_int(args.get("call_limit"), 3, 1, 10)
    max_patches = _clamp_int(args.get("max_patches"), 10, 1, 20)

    report_result = _tool_compare_api_contract(
        project_id, root, {"path": path_q, "method": method_norm or None, "route_limit": route_limit, "call_limit": call_limit}
    )
    if not report_result.get("ok"):
        return report_result
    report = report_result["data"]
    if not isinstance(report.get("routes"), list) or not report["routes"]:
        return _tool_ok({"input": {"path": path_q, "method": method_norm}, "patches": [], "notes": ["no_routes_or_calls_found"]})

    patches: list[dict] = []
    notes: list[str] = []

    # helper to add patch with dedupe
    seen_patch_paths: set[str] = set()

    def add_patch(path: str, diff: str, reason: str) -> None:
        nonlocal patches
        if not path or not diff.strip():
            return
        key = f"{path}:{reason}"
        if key in seen_patch_paths:
            return
        seen_patch_paths.add(key)
        patches.append({"path": path, "reason": reason, "patch_unified_diff": diff})

    # 2) Iterate routes & calls
    for ritem in report["routes"]:
        if not isinstance(ritem, dict):
            continue
        route = ritem.get("route")
        if not isinstance(route, dict):
            continue
        resolved_full_paths = ritem.get("resolved_full_paths")
        full_path = ""
        if isinstance(resolved_full_paths, list) and resolved_full_paths:
            fp0 = resolved_full_paths[0]
            if isinstance(fp0, str) and fp0.strip():
                full_path = fp0.strip()
        if not full_path:
            # fallback to local
            full_path = str(route.get("path") or "")

        r_method = str(route.get("method") or "").upper() or (method_norm or "GET")

        # For each frontend call meta
        fcalls = ritem.get("frontend_calls")
        if not isinstance(fcalls, list):
            continue
        for f in fcalls:
            if not isinstance(f, dict):
                continue
            call = f.get("call")
            meta_obj = f.get("meta")
            comp = f.get("comparison")
            if not isinstance(call, dict):
                continue
            c_src = str(call.get("source_path") or "")
            c_line = int(call.get("lineno") or 0)
            c_method = str(call.get("method") or "").upper()
            wrapper_name = ""
            wrapper_body_type = ""
            wrapper_resp_type = ""
            if isinstance(meta_obj, dict):
                wrapper_name = str(meta_obj.get("wrapper_name") or "")
                wrapper_body_type = str(meta_obj.get("wrapper_body_type") or "")
                wrapper_resp_type = str(meta_obj.get("wrapper_response_type") or "")

            # ---- A) Patch wrapper (signature + path template) when path params missing
            missing_pp = []
            if isinstance(comp, dict):
                missing_pp = comp.get("path_params_missing_in_wrapper") or []
            if missing_pp and wrapper_name and c_src:
                # build recommended template literal for full_path
                snippet = build_frontend_snippet(r_method, full_path, handler_name=wrapper_name)
                tpl = str(snippet.get("path_template") or "")
                # infer param types
                add_params = []
                for pp in missing_pp:
                    if not isinstance(pp, dict):
                        continue
                    fe = str(pp.get("frontend_expected") or "").strip()
                    be = str(pp.get("backend") or "").strip()
                    nm = fe or be
                    if not nm:
                        continue
                    ts_type = "number" if (be.lower().endswith("id") or be.lower() == "id" or fe.lower().endswith("id")) else "string"
                    add_params.append({"name": nm, "type": ts_type})

                rr = _read_text_under_root(root, c_src)
                if rr:
                    rel_norm, _abs, old_txt = rr
                    meta.full_file_paths.add(rel_norm)
                    new_txt, changed, warns = ts_patch_wrapper_function(
                        old_txt,
                        fn_name=wrapper_name,
                        http_method=c_method or r_method,
                        new_path_literal=tpl,
                        add_params=add_params,
                    )
                    if changed:
                        diff = _unified_diff(rel_norm, old_txt, new_txt)
                        add_patch(rel_norm, diff, "frontend_wrapper_fix_path_params_and_template")
                    if warns:
                        notes.extend([f"wrapper:{wrapper_name}:{w}" for w in warns])
                else:
                    notes.append(f"wrapper_source_not_readable:{c_src}")

            # ---- B) Patch TS body type (request) when backend required fields missing in frontend
            body = {}
            if isinstance(comp, dict) and isinstance(comp.get("body"), dict):
                body = comp["body"]
            if body and wrapper_body_type:
                missing_body = body.get("missing_in_frontend") if isinstance(body.get("missing_in_frontend"), list) else []
                backend_fields = body.get("backend_fields") if isinstance(body.get("backend_fields"), list) else []
                if missing_body and backend_fields:
                    # locate typedef
                    with get_session() as s:
                        td = s.exec(
                            select(TsTypeDef).where(TsTypeDef.project_id == project_id, TsTypeDef.name == wrapper_body_type)
                        ).first()
                    if td and isinstance(td.source_path, str) and td.source_path:
                        rr = _read_text_under_root(root, td.source_path)
                        if rr:
                            rel_norm, _abs, old_txt = rr
                            meta.full_file_paths.add(rel_norm)
                            # add missing as REQUIRED for request (optional=False)
                            new_txt, changed, _status = ts_add_fields_to_typedef(
                                old_txt,
                                wrapper_body_type,
                                [{"name": k, "type": ""} for k in missing_body if isinstance(k, str) and k],
                                optional=False,
                            )
                            if changed:
                                diff = _unified_diff(rel_norm, old_txt, new_txt)
                                add_patch(rel_norm, diff, "frontend_body_type_add_missing_fields")
                        else:
                            notes.append(f"typedef_source_not_readable:{td.source_path}")
                    else:
                        notes.append(f"typedef_not_found_for_body_type:{wrapper_body_type}")

            # ---- C) Patch TS response type (response) when backend response keys missing in frontend type
            resp = {}
            if isinstance(comp, dict) and isinstance(comp.get("response"), dict):
                resp = comp["response"]
            if resp and wrapper_resp_type:
                missing_resp = resp.get("missing_in_frontend") if isinstance(resp.get("missing_in_frontend"), list) else []
                if missing_resp:
                    with get_session() as s:
                        td = s.exec(
                            select(TsTypeDef).where(TsTypeDef.project_id == project_id, TsTypeDef.name == wrapper_resp_type)
                        ).first()
                    if td and isinstance(td.source_path, str) and td.source_path:
                        rr = _read_text_under_root(root, td.source_path)
                        if rr:
                            rel_norm, _abs, old_txt = rr
                            meta.full_file_paths.add(rel_norm)
                            # add missing as OPTIONAL for response (optional=True)
                            new_txt, changed, _status = ts_add_fields_to_typedef(
                                old_txt,
                                wrapper_resp_type,
                                [{"name": k, "type": ""} for k in missing_resp if isinstance(k, str) and k],
                                optional=True,
                            )
                            if changed:
                                diff = _unified_diff(rel_norm, old_txt, new_txt)
                                add_patch(rel_norm, diff, "frontend_response_type_add_missing_keys_optional")
                        else:
                            notes.append(f"typedef_source_not_readable:{td.source_path}")
                    else:
                        notes.append(f"typedef_not_found_for_response_type:{wrapper_resp_type}")

            if len(patches) >= max_patches:
                break
        if len(patches) >= max_patches:
            break

    # combine patches if multiple for same file (optional; keep simple: return as list)
    truncated = len(patches) > max_patches
    patches = patches[:max_patches]

    return _tool_ok(
        {
            "input": {
                "path": path_q,
                "method": method_norm,
                "route_limit": route_limit,
                "call_limit": call_limit,
                "max_patches": max_patches,
            },
            "patches": patches,
            "notes": notes[:100],
            "truncated": bool(truncated),
        }
    )

def _load_ts_typedefs_by_name(project_id: int, names: list[str]) -> dict[str, dict]:
    wanted = [n for n in (names or []) if isinstance(n, str) and n.strip()]
    if not wanted:
        return {}
    wanted = list(dict.fromkeys(wanted))[:200]
    out: dict[str, dict] = {}
    with get_session() as s:
        rows = s.exec(
            select(TsTypeDef).where(TsTypeDef.project_id == project_id, TsTypeDef.name.in_(wanted))
        ).all()
    for r in rows:
        nm = str(r.name or "")
        if not nm:
            continue
        try:
            fields = json.loads(r.fields_json or "[]")
        except Exception:
            fields = []
        out[nm] = {
            "name": nm,
            "kind": str(r.kind or ""),
            "source_path": str(r.source_path or ""),
            "fields": fields if isinstance(fields, list) else [],
        }
    return out


def _tool_compare_api_contract(project_id: int, root: Path, args: dict) -> dict:
    path_q = args.get("path")
    if not isinstance(path_q, str) or not path_q.strip():
        return _tool_error("bad_args", "path is required")
    path_q = path_q.strip()
    method = args.get("method")
    method_norm = (str(method).strip().upper() if isinstance(method, str) and method.strip() else "")
    route_limit = _clamp_int(args.get("route_limit"), 3, 1, 10)
    call_limit = _clamp_int(args.get("call_limit"), 10, 1, 50)

    # Reuse route_usages logic to find best matching routes + frontend calls
    ru_result = _tool_route_usages(
        project_id,
        {"path": path_q, "method": method_norm or None, "route_limit": route_limit, "call_limit": call_limit},
    )
    if not ru_result.get("ok"):
        return ru_result
    ru = ru_result["data"]
    routes = ru.get("routes") if isinstance(ru, dict) else None
    if not isinstance(routes, list) or not routes:
        return _tool_ok(
            {"input": {"path": path_q, "method": method_norm}, "routes": [], "note": "No routes found. Ensure Scan ran and path query is correct."}
        )

    result_routes: list[dict] = []

    for item in routes:
        if not isinstance(item, dict):
            continue
        route_info = item.get("route")
        if not isinstance(route_info, dict):
            continue

        r_method = str(route_info.get("method") or "")
        r_local = str(route_info.get("path") or "")
        r_src = str(route_info.get("source_path") or "")
        r_handler = str(route_info.get("handler_name") or "")
        r_line = int(route_info.get("lineno") or 0)

        # Load backend contract from DB; fallback to on-the-fly parse
        backend_contract: dict | None = None
        with get_session() as s:
            row = s.exec(
                select(ApiRouteContract).where(
                    ApiRouteContract.project_id == project_id,
                    ApiRouteContract.method == r_method,
                    ApiRouteContract.path == r_local,
                    ApiRouteContract.source_path == r_src,
                    ApiRouteContract.handler_name == r_handler,
                    ApiRouteContract.lineno == r_line,
                )
            ).first()
        if row and isinstance(row.contract_json, str) and row.contract_json.strip():
            try:
                backend_contract = json.loads(row.contract_json)
            except Exception:
                backend_contract = None
        if backend_contract is None:
            # on the fly
            try:
                abs_p, rel_norm = resolve_under_root(root, r_src, max_length=settings.max_rel_path_chars)
                txt = abs_p.read_text(encoding="utf-8", errors="replace")
                backend_contract = build_backend_contract_for_route(
                    txt,
                    {"method": r_method, "path": r_local, "handler_name": r_handler, "source_path": r_src, "lineno": r_line},
                )
            except Exception as e:
                backend_contract = {"version": 1, "warnings": [f"contract_build_failed:{e}"]}

        # Backend facets
        bp = backend_contract.get("path_params") if isinstance(backend_contract, dict) else []
        bq = backend_contract.get("query_params") if isinstance(backend_contract, dict) else []
        bb = backend_contract.get("body") if isinstance(backend_contract, dict) else None
        br = backend_contract.get("response") if isinstance(backend_contract, dict) else {}

        path_params = bp if isinstance(bp, list) else []
        body_fields = []
        body_type_name = ""
        if isinstance(bb, dict):
            body_type_name = str(bb.get("type_name") or "")
            model = bb.get("model")
            if isinstance(model, dict) and isinstance(model.get("fields"), list):
                body_fields = model["fields"]

        resp_keys = []
        if isinstance(br, dict) and isinstance(br.get("keys"), list):
            resp_keys = [str(x) for x in br.get("keys") if isinstance(x, str)]

        # frontend matches + call meta + comparisons
        matches = item.get("matches")
        if not isinstance(matches, list):
            matches = []

        type_names: list[str] = []
        metas: list[dict] = []
        for m in matches:
            if not isinstance(m, dict):
                continue
            c_method = str(m.get("method") or "")
            c_path = str(m.get("path") or "")
            c_src = str(m.get("source_path") or "")
            c_line = int(m.get("lineno") or 0)

            with get_session() as s:
                cm = s.exec(
                    select(ApiCallMeta).where(
                        ApiCallMeta.project_id == project_id,
                        ApiCallMeta.method == c_method,
                        ApiCallMeta.path == c_path,
                        ApiCallMeta.source_path == c_src,
                        ApiCallMeta.lineno == c_line,
                    )
                ).first()
            meta = {
                "call": {
                    "method": c_method,
                    "path": c_path,
                    "source_path": c_src,
                    "lineno": c_line,
                    "client": str(m.get("client") or ""),
                },
                "meta": {},
                "comparison": {},
            }
            if cm:
                try:
                    params = json.loads(cm.wrapper_params_json or "[]")
                except Exception:
                    params = []
                try:
                    body_keys = json.loads(cm.body_keys_json or "[]")
                except Exception:
                    body_keys = []

                resp_t = str(cm.wrapper_response_type or "")
                body_t = str(cm.wrapper_body_type or "")
                if resp_t:
                    type_names.append(resp_t)
                if body_t:
                    type_names.append(body_t)

                meta["meta"] = {
                    "wrapper_name": str(cm.wrapper_name or ""),
                    "wrapper_params": params if isinstance(params, list) else [],
                    "wrapper_response_type": resp_t,
                    "wrapper_body_type": body_t,
                    "body_keys": body_keys if isinstance(body_keys, list) else [],
                }
            metas.append(meta)

        type_defs = _load_ts_typedefs_by_name(project_id, type_names)

        # Now compute comparisons per meta record
        for meta in metas:
            mobj = meta.get("meta") if isinstance(meta.get("meta"), dict) else {}
            wparams = mobj.get("wrapper_params") if isinstance(mobj.get("wrapper_params"), list) else []
            wparam_names = set()
            for p in wparams:
                if isinstance(p, dict):
                    nm = str(p.get("name") or "")
                    if nm and nm != "<destructured>":
                        wparam_names.add(nm)

            # Path params
            missing_path_params = []
            for pp in path_params:
                if not isinstance(pp, dict):
                    continue
                nm = str(pp.get("name") or "")
                if not nm:
                    continue
                # frontend is camelCase in this repo; accept both
                camel = nm
                # simple snake_to_camel-ish
                if "_" in nm:
                    parts = [x for x in nm.split("_") if x]
                    if parts:
                        camel = parts[0].lower() + "".join([x[:1].upper() + x[1:] for x in parts[1:]])
                if camel not in wparam_names and nm not in wparam_names:
                    missing_path_params.append({"backend": nm, "frontend_expected": camel})

            # Body compare
            backend_body_fields = [str(f.get("name") or "") for f in body_fields if isinstance(f, dict)]
            backend_body_fields = [x for x in backend_body_fields if x]

            frontend_body_keys = []
            if isinstance(mobj.get("body_keys"), list):
                frontend_body_keys = [str(x) for x in mobj["body_keys"] if isinstance(x, str)]
            # If no literal keys, use typedef fields if body type is known
            body_t = str(mobj.get("wrapper_body_type") or "")
            if (not frontend_body_keys) and body_t and body_t in type_defs:
                flds = type_defs[body_t].get("fields") or []
                if isinstance(flds, list):
                    frontend_body_keys = [str(x.get("name") or "") for x in flds if isinstance(x, dict)]
                    frontend_body_keys = [x for x in frontend_body_keys if x]

            missing_body = []
            extra_body = []
            if backend_body_fields and frontend_body_keys:
                bset = set(backend_body_fields)
                fset = set(frontend_body_keys)
                missing_body = sorted(bset - fset)
                extra_body = sorted(fset - bset)

            # Response compare
            resp_t = str(mobj.get("wrapper_response_type") or "")
            frontend_resp_keys = []
            if resp_t and resp_t in type_defs:
                flds = type_defs[resp_t].get("fields") or []
                if isinstance(flds, list):
                    frontend_resp_keys = [str(x.get("name") or "") for x in flds if isinstance(x, dict)]
                    frontend_resp_keys = [x for x in frontend_resp_keys if x]

            missing_resp = []
            extra_resp = []
            if resp_keys and frontend_resp_keys:
                bset = set(resp_keys)
                fset = set(frontend_resp_keys)
                missing_resp = sorted(bset - fset)
                extra_resp = sorted(fset - bset)

            meta["comparison"] = {
                "path_params_missing_in_wrapper": missing_path_params,
                "body": {
                    "backend_body_type": body_type_name,
                    "backend_fields": backend_body_fields,
                    "frontend_body_type": body_t,
                    "frontend_keys": frontend_body_keys,
                    "missing_in_frontend": missing_body,
                    "extra_in_frontend": extra_body,
                    "note": (
                        "Body comparison is best-effort. If frontend sends an inline object with computed keys, it may not be detected."
                    ),
                },
                "response": {
                    "backend_keys": resp_keys,
                    "frontend_response_type": resp_t,
                    "frontend_keys": frontend_resp_keys,
                    "missing_in_frontend": missing_resp,
                    "extra_in_frontend": extra_resp,
                    "note": (
                        "Response comparison uses literal dict keys in backend returns and TS object type fields."
                    ),
                },
            }

        result_routes.append(
            {
                "route": route_info,
                "resolved_full_paths": item.get("resolved_full_paths") if isinstance(item.get("resolved_full_paths"), list) else [],
                "backend_contract": backend_contract,
                "frontend_calls": metas,
            }
        )

    return _tool_ok(
        {
            "input": {"path": path_q, "method": method_norm, "route_limit": int(route_limit), "call_limit": int(call_limit)},
            "routes": result_routes,
            "notes": (
                "This is a best-effort static comparison. It does not execute code, and it cannot fully infer dynamic bodies/responses. "
                "Run Scan after changes to refresh indexes."
            ),
        }
    )


def _seed_context(project_id: int, root: Path, target_rel: str, depth: int, *, max_file_chars: int) -> dict:
    abs_target, target_norm = resolve_under_root(root, target_rel, max_length=settings.max_rel_path_chars)
    target_text = ""
    try:
        target_text = abs_target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        target_text = ""
    max_file_chars = max(200, min(int(max_file_chars), 50_000))
    if len(target_text) > max_file_chars:
        target_text = target_text[:max_file_chars]

    contract = {}
    try:
        contract = get_or_build_contract(project_id, root, target_norm)
    except Exception:
        contract = {}

    node = None
    with get_session() as s:
        node = s.exec(
            select(FileNode).where(FileNode.project_id == project_id, FileNode.path == target_norm)
        ).first()
    node_metrics = (
        {
            "path": node.path,
            "language": node.language,
            "loc": node.loc,
            "complexity": node.complexity,
            "fan_in": node.fan_in,
            "fan_out": node.fan_out,
            "scc_id": node.scc_id,
            "status": node.status,
        }
        if node
        else {}
    )

    routes_in_file: list[dict] = []
    calls_in_file: list[dict] = []
    try:
        with get_session() as s:
            rr = s.exec(
                select(ApiRoute.method, ApiRoute.path, ApiRoute.handler_name, ApiRoute.lineno)
                .where(ApiRoute.project_id == project_id, ApiRoute.source_path == target_norm)
                .order_by(ApiRoute.path.asc())
                .limit(20)
            ).all()
            for row in rr:
                if isinstance(row, (tuple, list)) and len(row) >= 4:
                    routes_in_file.append({"method": row[0], "path": row[1], "handler_name": row[2], "lineno": int(row[3] or 0)})

            cc = s.exec(
                select(ApiCall.method, ApiCall.path, ApiCall.client, ApiCall.lineno)
                .where(ApiCall.project_id == project_id, ApiCall.source_path == target_norm)
                .order_by(ApiCall.path.asc())
                .limit(20)
            ).all()
            for row in cc:
                if isinstance(row, (tuple, list)) and len(row) >= 4:
                    calls_in_file.append({"method": row[0], "path": row[1], "client": row[2], "lineno": int(row[3] or 0)})
    except Exception:
        routes_in_file = []
        calls_in_file = []

    out_depth = max(0, min(depth, 6))
    in_depth = max(0, min(depth, 2))
    outbound = _neighbors_limited(project_id, target_norm, direction="out", depth=out_depth, limit=200)
    inbound = _neighbors_limited(project_id, target_norm, direction="in", depth=in_depth, limit=200)

    return {
        "target_path": target_norm,
        "target_file": {"path": target_norm, "content": target_text, "max_chars": max_file_chars},
        "target_contract": contract,
        "target_node": node_metrics,
        "api_hint": {
            "routes_in_file": routes_in_file,
            "calls_in_file": calls_in_file,
            "note": "Use search_routes/search_api_calls/route_usages for project-wide API mapping.",
        },
        "graph_hint": {
            "inbound": inbound,
            "outbound": outbound,
            "in_depth": in_depth,
            "out_depth": out_depth,
            "note": "Lists are truncated hints. Use get_neighbors() to expand.",
        },
    }


def _agentic_json_call(
    *,
    model: str,
    self_check_model: str | None,
    schema: dict,
    project_id: int,
    root: Path,
    seed: dict,
    user_prompt: str,
    reasoning_effort: str | None,
    evidence_mode: bool,
    instructions: str | None = None,
    max_calls: int | None = None,
    max_total_tool_output_chars: int | None = None,
    max_file_chars: int | None = None,
    temperature: float | None = None,
    allow_self_check_retry: bool = True,
) -> tuple[dict, AgenticMeta]:
    client = get_openai_client()
    fmt = _normalize_responses_json_schema(schema)
    srv_calls = int(settings.llm_agentic_max_calls)
    srv_total = int(settings.llm_agentic_max_total_tool_output_chars)
    srv_file = int(settings.llm_agentic_max_file_chars)
    srv_temp = float(settings.llm_agentic_temperature)

    eff_calls = min(_clamp_int(max_calls, srv_calls, 1, 100), srv_calls)
    eff_total = min(_clamp_int(max_total_tool_output_chars, srv_total, 2_000, 1_000_000), srv_total)
    eff_file = min(_clamp_int(max_file_chars, srv_file, 200, 50_000), srv_file)
    eff_temp = _clamp_int(int(10 * _clamp_float(temperature, srv_temp, 0.0, 2.0)), int(10 * srv_temp), 0, 20) / 10.0

    tools = _tool_definitions(eff_file)
    meta = AgenticMeta()
    tool_cache: dict[str, dict] = {}

    tool_rules = (
        "Tooling rules:\n"
        "- First call plan_retrieval before using any other tool.\n"
        "- Use tools sparingly. Prefer get_contract before get_file.\n"
        "- For definition/export lookups, use search_symbols first (faster and more precise). If no results, fall back to search_text.\n"
        "- Prefer search_semantic for conceptual queries; if no results, use search_text.\n"
        "- Prefer search_text to locate occurrences before fetching many files.\n"
        "- When locating or updating relevant tests, use search_tests to find test files by standard patterns.\n"
        "- Use get_file only after search_paths, search_symbols, search_text, or search_semantic for the current task.\n"
        "- Never assume missing code; fetch it.\n"
        "- Keep changes minimal; for fixes, only propose changes you can justify from retrieved context.\n"
        "- For FIX responses, tests must be a non-empty list of concrete tests or manual verification steps; missing tests are not allowed.\n"
    )
    if evidence_mode:
        tool_rules += (
            "- In evidence mode, every output must cite concrete file paths and line ranges; "
            "use get_file_lines when possible.\n"
        )

    input_list: list[Any] = [
        {"role": "user", "content": f"{tool_rules}\nUser prompt:\n{user_prompt}\n\nSeed context (JSON):\n{json.dumps(seed, ensure_ascii=False)}"}
    ]

    max_calls_budget = eff_calls
    max_total_chars_budget = eff_total

    def _apply_search_budget(
        args: dict[str, Any],
        *,
        remaining_budget: int,
        max_total_budget: int,
        adjust_text: bool,
        adjust_semantic: bool,
    ) -> None:
        if max_total_budget <= 0:
            return
        ratio = min(1.0, max(0.0, remaining_budget / max_total_budget))
        if adjust_text:
            base_max_matches = _clamp_int(args.get("max_matches"), 50, 1, 500)
            base_context_chars = _clamp_int(args.get("context_chars"), 160, 40, 400)
            min_matches = 5
            min_context_chars = 60
            args["max_matches"] = max(min_matches, int(round(base_max_matches * ratio)))
            args["context_chars"] = max(min_context_chars, int(round(base_context_chars * ratio)))
        if adjust_semantic:
            base_max_results = _clamp_int(
                args.get("max_results"),
                int(settings.embeddings_search_max_results),
                1,
                int(settings.embeddings_search_max_results),
            )
            min_results = 3
            args["max_results"] = max(min_results, int(round(base_max_results * ratio)))

    def _truncate_tool_output(name: str, out: dict, *, remaining_budget: int) -> tuple[dict, bool]:
        if not isinstance(out, dict):
            return {"truncated_due_to_budget": True}, True
        payload = out
        if out.get("ok") is True and isinstance(out.get("data"), dict):
            payload = out["data"]

        def mark_truncated(payload: dict) -> None:
            payload["truncated_due_to_budget"] = True
            meta = payload.get("meta")
            if isinstance(meta, dict):
                meta["truncated_due_to_budget"] = True

        def shrink_snippets(items: list[dict], max_len: int) -> bool:
            changed = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                for key in ("snippet", "text", "content"):
                    val = item.get(key)
                    if isinstance(val, str) and len(val) > max_len:
                        item[key] = val[:max_len]
                        changed = True
            return changed

        truncated = False
        attempts = 0
        while True:
            out_str = json.dumps(out, ensure_ascii=False)
            if len(out_str) <= remaining_budget:
                if truncated:
                    mark_truncated(payload)
                return out, truncated
            if attempts >= 6:
                break
            attempts += 1
            changed = False
            if isinstance(payload.get("matches"), list):
                changed = shrink_snippets(payload["matches"], max(40, 160 // (attempts + 1))) or changed
                if len(payload["matches"]) > 5:
                    payload["matches"] = payload["matches"][: max(5, len(payload["matches"]) // 2)]
                    changed = True
            if isinstance(payload.get("results"), list):
                changed = shrink_snippets(payload["results"], max(60, 200 // (attempts + 1))) or changed
                if len(payload["results"]) > 3:
                    payload["results"] = payload["results"][: max(3, len(payload["results"]) // 2)]
                    changed = True
            if not changed:
                break
            truncated = True

        minimized = {"truncated_due_to_budget": True}
        mark_truncated(minimized)
        return minimized, True

    while True:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions if instructions is not None else SYSTEM_INSTRUCTIONS,
            "input": input_list,
            "tools": tools,
            "text": {"format": fmt},
            "store": bool(settings.openai_store),
            "parallel_tool_calls": False,
        }
        if supports_temperature(model):
            kwargs["temperature"] = float(eff_temp)
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
            for k in ("prompt_cache_key", "prompt_cache_retention", "store", "temperature", "parallel_tool_calls"):
                if k in msg:
                    kwargs.pop(k, None)
            resp = client.responses.create(**kwargs)
        except openai.APIError as e:
            status = getattr(e, "status_code", None)
            if status is not None:
                raise RuntimeError(f"OpenAI API error (HTTP {status}): {e}") from e
            raise RuntimeError(f"OpenAI API error: {e}") from e
        except Exception as e:
            raise RuntimeError(f"OpenAI request failed: {e}") from e

        out_items = getattr(resp, "output", None)
        if isinstance(out_items, list) and out_items:
            input_list += out_items

        function_calls: list[tuple[str, str, str]] = []
        if isinstance(out_items, list):
            for item in out_items:
                item_type = getattr(item, "type", None) if not isinstance(item, dict) else item.get("type")
                if item_type != "function_call":
                    continue
                name = getattr(item, "name", None) if not isinstance(item, dict) else item.get("name")
                call_id = getattr(item, "call_id", None) if not isinstance(item, dict) else item.get("call_id")
                arguments = getattr(item, "arguments", None) if not isinstance(item, dict) else item.get("arguments")
                if not isinstance(name, str) or not isinstance(call_id, str):
                    continue
                if not isinstance(arguments, str) or not arguments.strip():
                    arguments = "{}"
                function_calls.append((name, call_id, arguments))

        if not function_calls:
            result = _parse_model_json(resp)
            if evidence_mode:
                sources = result.get("sources") if isinstance(result, dict) else None
                missing_sources = not isinstance(sources, list) or len(sources) == 0
                if missing_sources:
                    if allow_self_check_retry:
                        retry_prompt = (
                            f"{user_prompt}\n\n"
                            "Evidence mode requires sources with file paths and line ranges. "
                            "Include non-empty sources and use get_file_lines when possible."
                        )
                        return _agentic_json_call(
                            model=model,
                            self_check_model=self_check_model,
                            schema=schema,
                            project_id=project_id,
                            root=root,
                            seed=seed,
                            user_prompt=retry_prompt,
                            reasoning_effort=reasoning_effort,
                            evidence_mode=evidence_mode,
                            instructions=instructions,
                            max_calls=max_calls,
                            max_total_tool_output_chars=max_total_tool_output_chars,
                            max_file_chars=max_file_chars,
                            temperature=temperature,
                            allow_self_check_retry=False,
                        )
                    raise RuntimeError("Evidence mode requires non-empty sources in the response")
            check_model = self_check_model or model
            try:
                self_check = _run_self_check(
                    client=client,
                    model=check_model,
                    user_prompt=user_prompt,
                    seed=seed,
                    response_payload=result,
                )
            except Exception as exc:
                meta.self_check_ok = None
                meta.self_check_notes = [f"self_check_error: {exc}"]
                meta.self_check_missing_context = []
                return (result, meta)

            ok = bool(self_check.get("ok") is True)
            issues = self_check.get("issues")
            missing_context = self_check.get("missing_context")
            meta.self_check_ok = ok
            meta.self_check_notes = list(issues) if isinstance(issues, list) else []
            meta.self_check_missing_context = (
                list(missing_context) if isinstance(missing_context, list) else []
            )

            if not ok and allow_self_check_retry:
                extra_sections: list[str] = []
                if meta.self_check_missing_context:
                    extra_sections.append(
                        "Missing context:\n- " + "\n- ".join(meta.self_check_missing_context)
                    )
                if meta.self_check_notes:
                    extra_sections.append(
                        "Issues:\n- " + "\n- ".join(meta.self_check_notes)
                    )
                extra_prompt = "Self-check обнаружил проблемы. Используй инструменты, чтобы собрать недостающий контекст."
                if extra_sections:
                    extra_prompt = f"{extra_prompt}\n\n" + "\n\n".join(extra_sections)
                retry_prompt = f"{user_prompt}\n\n{extra_prompt}"
                return _agentic_json_call(
                    model=model,
                    self_check_model=self_check_model,
                    schema=schema,
                    project_id=project_id,
                    root=root,
                    seed=seed,
                    user_prompt=retry_prompt,
                    reasoning_effort=reasoning_effort,
                    evidence_mode=evidence_mode,
                    instructions=instructions,
                    max_calls=max_calls,
                    max_total_tool_output_chars=max_total_tool_output_chars,
                    max_file_chars=max_file_chars,
                    temperature=temperature,
                    allow_self_check_retry=False,
                )

            return (result, meta)

        for name, call_id, arguments in function_calls:
            meta.tool_calls += 1
            if meta.tool_calls > max_calls_budget:
                raise RuntimeError(f"Agentic tool call limit exceeded: {max_calls_budget}")
            try:
                args_raw = json.loads(arguments)
                if not isinstance(args_raw, dict):
                    args_raw = {}
            except Exception:
                args_raw = {}

            args: dict[str, Any] = dict(args_raw)

            remaining_budget = max(0, max_total_chars_budget - meta.total_tool_output_chars)
            if remaining_budget <= 0:
                meta.tool_trace.append(
                    {
                        "name": name,
                        "args": args,
                        "reason": args.get("reason"),
                        "cache_hit": False,
                        "response_chars": 0,
                        "response_bytes": 0,
                        "duration_ms": 0,
                        "status": "budget_exhausted",
                        "truncated_due_to_budget": False,
                    }
                )
                input_list.append(
                    {"role": "system", "content": "Agentic tool output budget exhausted"}
                )
                break
            if name == "search_text":
                _apply_search_budget(
                    args,
                    remaining_budget=remaining_budget,
                    max_total_budget=max_total_chars_budget,
                    adjust_text=True,
                    adjust_semantic=False,
                )
            elif name == "search_semantic":
                _apply_search_budget(
                    args,
                    remaining_budget=remaining_budget,
                    max_total_budget=max_total_chars_budget,
                    adjust_text=True,
                    adjust_semantic=True,
                )

            args_for_cache = {k: v for k, v in args.items() if k != "reason"}
            cache_key = f"{name}:{json.dumps(args_for_cache, sort_keys=True, ensure_ascii=False)}"
            cache_hit = cache_key in tool_cache
            start = None if cache_hit else time.perf_counter()
            try:
                if cache_hit:
                    meta.cache_hits += 1
                    out = tool_cache[cache_key]
                else:
                    out = _dispatch_tool(project_id, root, meta, name, args, max_file_chars=eff_file)
                    if isinstance(out, dict):
                        err = out.get("error") if isinstance(out, dict) else None
                        err_code = err.get("code") if isinstance(err, dict) else None
                        if err_code != "policy_violation":
                            tool_cache[cache_key] = out
            except Exception:
                duration_ms = 0.0
                if start is not None:
                    duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
                meta.tool_trace.append(
                    {
                        "name": name,
                        "args": args,
                        "reason": args.get("reason"),
                        "cache_hit": cache_hit,
                        "response_chars": 0,
                        "response_bytes": 0,
                        "duration_ms": duration_ms,
                        "status": "error",
                        "truncated_due_to_budget": False,
                    }
                )
                raise

            out_str = json.dumps(out, ensure_ascii=False)
            response_bytes = len(out_str.encode("utf-8"))
            truncated_due_to_budget = False
            if remaining_budget >= 0 and len(out_str) > remaining_budget:
                out, truncated_due_to_budget = _truncate_tool_output(
                    name, out, remaining_budget=remaining_budget
                )
                out_str = json.dumps(out, ensure_ascii=False)
                response_bytes = len(out_str.encode("utf-8"))
            response_chars = len(out_str)
            duration_ms = 0.0
            if start is not None:
                duration_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
            ok_result = bool(out.get("ok") is True)
            status = "ok" if ok_result else "error"
            err_info = out.get("error") if isinstance(out, dict) else None
            err_code = err_info.get("code") if isinstance(err_info, dict) else None
            err_message = err_info.get("message") if isinstance(err_info, dict) else None
            meta.tool_trace.append(
                {
                    "name": name,
                    "args": args,
                    "reason": args.get("reason"),
                    "cache_hit": cache_hit,
                    "response_chars": response_chars,
                    "response_bytes": response_bytes,
                    "duration_ms": duration_ms,
                    "status": status,
                    "truncated_due_to_budget": truncated_due_to_budget,
                    "error_code": err_code,
                    "error_message": err_message,
                }
            )
            meta.total_tool_output_chars += response_chars
            input_list.append(
                {"type": "function_call_output", "call_id": call_id, "output": out_str}
            )


def analyze_agentic(
    project_id: int,
    root: Path,
    target_rel: str,
    *,
    depth: int,
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    instructions: str | None = None,
    max_calls: int | None = None,
    max_total_tool_output_chars: int | None = None,
    max_file_chars: int | None = None,
    temperature: float | None = None,
    evidence_mode: bool,
) -> tuple[dict, AgenticMeta]:
    seed = _seed_context(project_id, root, target_rel, depth=depth, max_file_chars=max_file_chars or settings.llm_agentic_max_file_chars)
    return _agentic_json_call(
        model=policy.analysis_model,
        self_check_model=policy.analysis_model,
        schema=ANALYZE_SCHEMA,
        project_id=project_id,
        root=root,
        seed=seed,
        user_prompt=f"Task: ANALYZE\n{user_prompt}",
        reasoning_effort=policy.analysis_effort,
        evidence_mode=evidence_mode,
        instructions=instructions,
        max_calls=max_calls,
        max_total_tool_output_chars=max_total_tool_output_chars,
        max_file_chars=max_file_chars,
        temperature=temperature,
    )


def evolve_agentic(
    project_id: int,
    root: Path,
    target_rel: str,
    *,
    depth: int,
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    instructions: str | None = None,
    max_calls: int | None = None,
    max_total_tool_output_chars: int | None = None,
    max_file_chars: int | None = None,
    temperature: float | None = None,
    evidence_mode: bool,
) -> tuple[dict, AgenticMeta]:
    seed = _seed_context(project_id, root, target_rel, depth=depth, max_file_chars=max_file_chars or settings.llm_agentic_max_file_chars)
    return _agentic_json_call(
        model=policy.analysis_model,
        self_check_model=policy.analysis_model,
        schema=ANALYZE_SCHEMA,
        project_id=project_id,
        root=root,
        seed=seed,
        user_prompt=(
            "Task: EVOLVE\nFind evolution points (domain/business logic), API bottlenecks, change hotspots.\n"
            + user_prompt
        ),
        reasoning_effort=policy.analysis_effort,
        evidence_mode=evidence_mode,
        instructions=instructions,
        max_calls=max_calls,
        max_total_tool_output_chars=max_total_tool_output_chars,
        max_file_chars=max_file_chars,
        temperature=temperature,
    )


def fix_agentic(
    project_id: int,
    root: Path,
    target_rel: str,
    *,
    depth: int,
    user_prompt: str,
    policy: ModelPolicy = DEFAULT_POLICY,
    instructions: str | None = None,
    max_calls: int | None = None,
    max_total_tool_output_chars: int | None = None,
    max_file_chars: int | None = None,
    temperature: float | None = None,
    evidence_mode: bool,
) -> tuple[dict, AgenticMeta]:
    seed = _seed_context(project_id, root, target_rel, depth=depth, max_file_chars=max_file_chars or settings.llm_agentic_max_file_chars)
    return _agentic_json_call(
        model=policy.patch_model,
        self_check_model=policy.analysis_model,
        schema=FIX_SCHEMA,
        project_id=project_id,
        root=root,
        seed=seed,
        user_prompt=(
            "Task: FIX\nReturn minimal safe unified diff in patch_unified_diff.\n"
            + user_prompt
        ),
        reasoning_effort=policy.patch_effort,
        evidence_mode=evidence_mode,
        instructions=instructions,
        max_calls=max_calls,
        max_total_tool_output_chars=max_total_tool_output_chars,
        max_file_chars=max_file_chars,
        temperature=temperature,
    )
