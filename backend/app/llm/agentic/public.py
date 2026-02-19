from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..policy import DEFAULT_POLICY, ModelPolicy
from ..schemas import ANALYZE_SCHEMA, FIX_SCHEMA
from .call import _agentic_json_call_async
from .context import _seed_context_async
from .types import AgenticMeta


async def analyze_agentic_async(
    session: AsyncSession,
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
    reasoning_effort: str | None = None,
    evidence_mode: bool,
    allow_self_check_retry: bool = True,
    allow_evidence_retry: bool = True,
) -> tuple[dict, AgenticMeta]:
    seed = await _seed_context_async(
        session,
        project_id,
        root,
        target_rel,
        depth=depth,
        max_file_chars=max_file_chars or settings.llm_agentic_max_file_chars,
    )
    eff_reasoning_effort = (
        reasoning_effort if reasoning_effort is not None else policy.analysis_effort
    )
    return await _agentic_json_call_async(
        session=session,
        model=policy.analysis_model,
        self_check_model=policy.verifier_model,
        self_check_reasoning_effort=policy.verifier_effort,
        schema=ANALYZE_SCHEMA,
        project_id=project_id,
        root=root,
        seed=seed,
        user_prompt=f"Task: ANALYZE\n{user_prompt}",
        reasoning_effort=eff_reasoning_effort,
        evidence_mode=evidence_mode,
        instructions=instructions,
        max_calls=max_calls,
        max_total_tool_output_chars=max_total_tool_output_chars,
        max_file_chars=max_file_chars,
        temperature=temperature,
        allow_self_check_retry=allow_self_check_retry,
        allow_evidence_retry=allow_evidence_retry,
    )


async def evolve_agentic_async(
    session: AsyncSession,
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
    reasoning_effort: str | None = None,
    evidence_mode: bool,
    allow_self_check_retry: bool = True,
    allow_evidence_retry: bool = True,
) -> tuple[dict, AgenticMeta]:
    seed = await _seed_context_async(
        session,
        project_id,
        root,
        target_rel,
        depth=depth,
        max_file_chars=max_file_chars or settings.llm_agentic_max_file_chars,
    )
    eff_reasoning_effort = (
        reasoning_effort if reasoning_effort is not None else policy.analysis_effort
    )
    return await _agentic_json_call_async(
        session=session,
        model=policy.analysis_model,
        self_check_model=policy.verifier_model,
        self_check_reasoning_effort=policy.verifier_effort,
        schema=ANALYZE_SCHEMA,
        project_id=project_id,
        root=root,
        seed=seed,
        user_prompt=(
            "Task: EVOLVE\nFind evolution points (domain/business logic), API bottlenecks, "
            "change hotspots.\n"
            + user_prompt
        ),
        reasoning_effort=eff_reasoning_effort,
        evidence_mode=evidence_mode,
        instructions=instructions,
        max_calls=max_calls,
        max_total_tool_output_chars=max_total_tool_output_chars,
        max_file_chars=max_file_chars,
        temperature=temperature,
        allow_self_check_retry=allow_self_check_retry,
        allow_evidence_retry=allow_evidence_retry,
    )


async def fix_agentic_async(
    session: AsyncSession,
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
    reasoning_effort: str | None = None,
    evidence_mode: bool,
    allow_self_check_retry: bool = True,
    allow_evidence_retry: bool = True,
) -> tuple[dict, AgenticMeta]:
    seed = await _seed_context_async(
        session,
        project_id,
        root,
        target_rel,
        depth=depth,
        max_file_chars=max_file_chars or settings.llm_agentic_max_file_chars,
    )
    eff_reasoning_effort = reasoning_effort if reasoning_effort is not None else policy.patch_effort
    return await _agentic_json_call_async(
        session=session,
        model=policy.patch_model,
        self_check_model=policy.verifier_model,
        self_check_reasoning_effort=policy.verifier_effort,
        schema=FIX_SCHEMA,
        project_id=project_id,
        root=root,
        seed=seed,
        user_prompt=(
            "Task: FIX\nReturn minimal safe unified diff in patch_unified_diff.\n" + user_prompt
        ),
        reasoning_effort=eff_reasoning_effort,
        evidence_mode=evidence_mode,
        instructions=instructions,
        max_calls=max_calls,
        max_total_tool_output_chars=max_total_tool_output_chars,
        max_file_chars=max_file_chars,
        temperature=temperature,
        allow_self_check_retry=allow_self_check_retry,
        allow_evidence_retry=allow_evidence_retry,
    )
