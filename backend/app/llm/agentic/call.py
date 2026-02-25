from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import openai
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...infra.external_io_runtime import run_openai_io_async
from ..client import get_async_openai_client
from ..model_caps import supports_reasoning, supports_temperature
from ..orchestrator import SYSTEM_INSTRUCTIONS
from ..usage import extract_usage, merge_usage
from .dispatch import _clamp_float, _clamp_int, _dispatch_tool_async
from .schema import _normalize_responses_json_schema, _parse_model_json
from .self_check import _run_self_check_async
from .tools import _tool_definitions
from .types import AgenticMeta


def _has_valid_sources_structure(result: dict[str, Any]) -> tuple[bool, str]:
    sources = result.get("sources")
    if not isinstance(sources, list) or len(sources) == 0:
        return False, "empty sources"

    for item in sources:
        if not isinstance(item, dict):
            return False, "invalid sources"

        path = item.get("path")
        start_line = item.get("start_line")
        end_line = item.get("end_line")

        if not isinstance(path, str) or not path.strip():
            return False, "invalid sources"
        if not isinstance(start_line, int) or start_line < 1:
            return False, "invalid sources"
        if not isinstance(end_line, int) or end_line < 1:
            return False, "invalid sources"
        if end_line < start_line:
            return False, "invalid sources"

    return True, ""


async def _agentic_json_call_async(
    *,
    session: AsyncSession,
    model: str,
    self_check_model: str | None,
    self_check_reasoning_effort: str | None,
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
    allow_evidence_retry: bool = True,
) -> tuple[dict, AgenticMeta]:
    client = get_async_openai_client()
    fmt = _normalize_responses_json_schema(schema)
    srv_calls = int(settings.llm_agentic_max_calls)
    srv_total = int(settings.llm_agentic_max_total_tool_output_chars)
    srv_file = int(settings.llm_agentic_max_file_chars)
    srv_temp = float(settings.llm_agentic_temperature)

    eff_calls = min(_clamp_int(max_calls, srv_calls, 1, 100), srv_calls)
    eff_total = min(_clamp_int(max_total_tool_output_chars, srv_total, 1, 2_000_000), srv_total)
    eff_file = min(_clamp_int(max_file_chars, srv_file, 1, 200_000), srv_file)
    eff_temp = (
        _clamp_int(
            int(10 * _clamp_float(temperature, srv_temp, 0.0, 2.0)), int(10 * srv_temp), 0, 20
        )
        / 10.0
    )

    tools = _tool_definitions(eff_file)
    fs_ops_limit = max(1, min(int(settings.llm_agentic_fs_ops_concurrency), 128))
    meta = AgenticMeta(
        fs_ops_semaphore=asyncio.Semaphore(fs_ops_limit),
    )
    tool_cache: dict[str, dict] = {}

    def _apply_usage_to_meta(usage: dict[str, int | None]) -> None:
        current = {
            "prompt_tokens": meta.prompt_tokens,
            "completion_tokens": meta.completion_tokens,
            "total_tokens": meta.total_tokens,
        }
        merged = merge_usage(current, usage)
        meta.prompt_tokens = merged.get("prompt_tokens")
        meta.completion_tokens = merged.get("completion_tokens")
        meta.total_tokens = merged.get("total_tokens")

    tool_rules = (
        "Tooling rules:\n"
        "- First call plan_retrieval before using any other tool.\n"
        "- Use tools sparingly. Prefer get_contract before get_file.\n"
        "- For definition/export lookups, use search_symbols first (faster and more precise). "
        "If no results, fall back to search_text.\n"
        "- Prefer search_semantic for conceptual queries; if no results, use search_text.\n"
        "- Prefer search_text to locate occurrences before fetching many files.\n"
        "- When locating or updating relevant tests, use search_tests "
        "to find test files by standard patterns.\n"
        "- Use get_file only after search_paths, search_symbols, search_text, or "
        "search_semantic for the current task.\n"
        "- Never assume missing code; fetch it.\n"
        "- Keep changes minimal; for fixes, only propose changes you can justify from retrieved "
        "context.\n"
        "- For FIX responses, tests must be a non-empty list of concrete tests or manual "
        "verification steps; missing tests are not allowed.\n"
    )
    if evidence_mode:
        tool_rules += (
            "- In evidence mode, every output must cite concrete file paths and line ranges; "
            "use get_file_lines when possible.\n"
        )

    input_list: list[Any] = [
        {
            "role": "user",
            "content": (
                f"{tool_rules}\nUser prompt:\n{user_prompt}\n\nSeed context (JSON):\n"
                f"{json.dumps(seed, ensure_ascii=False)}"
            ),
        }
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
                changed = (
                    shrink_snippets(payload["matches"], max(40, 160 // (attempts + 1))) or changed
                )
                if len(payload["matches"]) > 5:
                    payload["matches"] = payload["matches"][: max(5, len(payload["matches"]) // 2)]
                    changed = True
            if isinstance(payload.get("results"), list):
                changed = (
                    shrink_snippets(payload["results"], max(60, 200 // (attempts + 1))) or changed
                )
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

        async def _responses_create_async() -> Any:
            async with asyncio.timeout(float(settings.openai_timeout_seconds)):
                return await run_openai_io_async(
                    lambda: client.responses.create(**kwargs),
                    kind="long",
                )

        try:
            resp = await _responses_create_async()
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
            resp = await _responses_create_async()
        except asyncio.CancelledError:
            raise
        except openai.APIError as e:
            status = getattr(e, "status_code", None)
            if status is not None:
                raise RuntimeError(f"OpenAI API error (HTTP {status}): {e}") from e
            raise RuntimeError(f"OpenAI API error: {e}") from e
        except Exception as e:
            raise RuntimeError(f"OpenAI request failed: {e}") from e

        _apply_usage_to_meta(extract_usage(resp))

        out_items = getattr(resp, "output", None)
        if isinstance(out_items, list) and out_items:
            input_list += out_items

        function_calls: list[tuple[str, str, str]] = []
        if isinstance(out_items, list):
            for item in out_items:
                item_type = (
                    getattr(item, "type", None) if not isinstance(item, dict) else item.get("type")
                )
                if item_type != "function_call":
                    continue
                name = (
                    getattr(item, "name", None) if not isinstance(item, dict) else item.get("name")
                )
                call_id = (
                    getattr(item, "call_id", None)
                    if not isinstance(item, dict)
                    else item.get("call_id")
                )
                arguments = (
                    getattr(item, "arguments", None)
                    if not isinstance(item, dict)
                    else item.get("arguments")
                )
                if not isinstance(name, str) or not isinstance(call_id, str):
                    continue
                if not isinstance(arguments, str) or not arguments.strip():
                    arguments = "{}"
                function_calls.append((name, call_id, arguments))

        if not function_calls:
            result = _parse_model_json(resp)
            if evidence_mode:
                valid_sources, sources_validation_reason = _has_valid_sources_structure(result)
                if not valid_sources:
                    if allow_evidence_retry:
                        retry_prompt = (
                            f"{user_prompt}\n\n"
                            f"Evidence validation error: {sources_validation_reason}. "
                            "Evidence mode requires sources with file paths and line ranges. "
                            "Fix sources format and include non-empty sources with path, "
                            "start_line, end_line. Use get_file_lines when possible."
                        )
                        retry_result, retry_meta = await _agentic_json_call_async(
                            session=session,
                            model=model,
                            self_check_model=self_check_model,
                            self_check_reasoning_effort=self_check_reasoning_effort,
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
                            allow_evidence_retry=False,
                        )
                        merged_retry_usage = merge_usage(
                            {
                                "prompt_tokens": meta.prompt_tokens,
                                "completion_tokens": meta.completion_tokens,
                                "total_tokens": meta.total_tokens,
                            },
                            {
                                "prompt_tokens": retry_meta.prompt_tokens,
                                "completion_tokens": retry_meta.completion_tokens,
                                "total_tokens": retry_meta.total_tokens,
                            },
                        )
                        retry_meta.prompt_tokens = merged_retry_usage.get("prompt_tokens")
                        retry_meta.completion_tokens = merged_retry_usage.get(
                            "completion_tokens"
                        )
                        retry_meta.total_tokens = merged_retry_usage.get("total_tokens")
                        return retry_result, retry_meta
                    raise RuntimeError(
                        "Evidence mode requires valid non-empty sources in the response"
                    )
            check_model = self_check_model or model
            try:
                self_check = await _run_self_check_async(
                    client=client,
                    model=check_model,
                    reasoning_effort=self_check_reasoning_effort,
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
                    extra_sections.append("Issues:\n- " + "\n- ".join(meta.self_check_notes))
                extra_prompt = (
                    "Self-check обнаружил проблемы. Используй инструменты, чтобы собрать "
                    "недостающий контекст."
                )
                if extra_sections:
                    extra_prompt = f"{extra_prompt}\n\n" + "\n\n".join(extra_sections)
                retry_prompt = f"{user_prompt}\n\n{extra_prompt}"
                retry_result, retry_meta = await _agentic_json_call_async(
                    session=session,
                    model=model,
                    self_check_model=self_check_model,
                    self_check_reasoning_effort=self_check_reasoning_effort,
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
                    allow_evidence_retry=allow_evidence_retry,
                )
                merged_retry_usage = merge_usage(
                    {
                        "prompt_tokens": meta.prompt_tokens,
                        "completion_tokens": meta.completion_tokens,
                        "total_tokens": meta.total_tokens,
                    },
                    {
                        "prompt_tokens": retry_meta.prompt_tokens,
                        "completion_tokens": retry_meta.completion_tokens,
                        "total_tokens": retry_meta.total_tokens,
                    },
                )
                retry_meta.prompt_tokens = merged_retry_usage.get("prompt_tokens")
                retry_meta.completion_tokens = merged_retry_usage.get("completion_tokens")
                retry_meta.total_tokens = merged_retry_usage.get("total_tokens")
                return retry_result, retry_meta

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
                    out = await _dispatch_tool_async(
                        session,
                        project_id,
                        root,
                        meta,
                        name,
                        args,
                        max_file_chars=eff_file,
                    )
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
