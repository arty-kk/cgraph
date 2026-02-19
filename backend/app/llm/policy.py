# backend/app/llm/policy.py
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from ..config import settings
from .routing_thresholds import resolve_routing_thresholds_async


@dataclass(frozen=True)
class ModelPolicy:
    triage_model: str = settings.triage_model
    analysis_model: str = settings.analysis_model
    patch_model: str = settings.patch_model
    verifier_model: str = settings.analysis_model

    triage_effort: str = settings.reasoning_effort_triage
    analysis_effort: str = settings.reasoning_effort_analysis
    patch_effort: str = settings.reasoning_effort_patch
    verifier_effort: str = "low"


DEFAULT_POLICY = ModelPolicy()


def _parse_model_pool(value: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[|,]", str(value or ""))]
    return [p for p in parts if p]


def _select_model_from_pool(
    pool: list[str],
    complexity_coeff: float,
    *,
    threshold_low: float,
    threshold_mid: float,
    threshold_high: float,
) -> str:
    if not pool:
        return ""
    if len(pool) == 1:
        return pool[0]
    low = float(threshold_low)
    mid = float(threshold_mid)
    high = float(threshold_high)

    if len(pool) == 2:
        return pool[1] if complexity_coeff >= mid else pool[0]
    if complexity_coeff >= high:
        return pool[-1]
    if complexity_coeff >= low:
        return pool[1]
    return pool[0]


def _resolve_verifier_effort(
    task_kind: str | None,
    eff_complexity: float,
    prompt_factor: float,
    *,
    threshold_low: float,
    threshold_high: float,
) -> str:
    edge_case = bool(
        task_kind == "fix" and (eff_complexity >= threshold_high or prompt_factor >= 0.8)
    )
    if edge_case:
        return "high"
    if eff_complexity >= threshold_low:
        return "medium"
    return "low"


async def resolve_runtime_policy_async(
    *,
    task_kind: str | None,
    complexity_coeff: float,
    prompt_len: int,
) -> ModelPolicy:
    triage_pool = _parse_model_pool(settings.triage_model)
    analysis_pool = _parse_model_pool(settings.analysis_model)
    patch_pool = _parse_model_pool(settings.patch_model)

    prompt_factor = min(1.0, max(0.0, prompt_len / max(1, int(settings.max_prompt_chars))))
    triage_complexity = 1.0 + prompt_factor
    task_bias = 0.15 if task_kind == "fix" else 0.0
    eff_complexity = max(1.0, min(2.0, float(complexity_coeff) + task_bias))
    threshold_low, threshold_mid, threshold_high = await resolve_routing_thresholds_async()

    triage_model = (
        _select_model_from_pool(
            triage_pool,
            triage_complexity,
            threshold_low=threshold_low,
            threshold_mid=threshold_mid,
            threshold_high=threshold_high,
        )
        or settings.triage_model
    )
    analysis_model = (
        _select_model_from_pool(
            analysis_pool,
            eff_complexity,
            threshold_low=threshold_low,
            threshold_mid=threshold_mid,
            threshold_high=threshold_high,
        )
        or settings.analysis_model
    )
    patch_model = (
        _select_model_from_pool(
            patch_pool,
            eff_complexity,
            threshold_low=threshold_low,
            threshold_mid=threshold_mid,
            threshold_high=threshold_high,
        )
        or settings.patch_model
    )

    verifier_model = (
        _select_model_from_pool(
            analysis_pool,
            min(threshold_mid, eff_complexity),
            threshold_low=threshold_low,
            threshold_mid=threshold_mid,
            threshold_high=threshold_high,
        )
        or settings.analysis_model
    )
    verifier_effort = _resolve_verifier_effort(
        task_kind,
        eff_complexity,
        prompt_factor,
        threshold_low=threshold_low,
        threshold_high=threshold_high,
    )

    return ModelPolicy(
        triage_model=triage_model,
        analysis_model=analysis_model,
        patch_model=patch_model,
        verifier_model=verifier_model,
        triage_effort=settings.reasoning_effort_triage,
        analysis_effort=settings.reasoning_effort_analysis,
        patch_effort=settings.reasoning_effort_patch,
        verifier_effort=verifier_effort,
    )


class ProfileName(str, Enum):
    ARCHITECT = "architect"
    SURGICAL = "surgical"
    INCIDENT = "incident"


@dataclass(frozen=True)
class ProfileParams:
    instructions: str | None
    temperature: float | None
    reasoning_effort: str | None
    max_calls: int | None
    max_total_tool_output_chars: int | None
    max_file_chars: int | None
    depth_min: int | None
    depth_max: int | None
    default_depth: int | None


SURGICAL_INSTRUCTIONS = (
    "Ты — StubGraph: хирургический режим. Твоя цель — точечные изменения с минимальным "
    "радиусом влияния.\n"
    "Правила:\n"
    "- Сохраняй текущие контракты и поведение, если пользователь не требует обратного.\n"
    "- Избегай широких правок и предположений; запрашивай только нужный контекст.\n"
    "- Для фикса: предложи минимальный unified diff и конкретные проверки.\n"
)

INCIDENT_INSTRUCTIONS = (
    "Ты — StubGraph: режим инцидента. Твоя цель — быстрое и безопасное восстановление "
    "работоспособности.\n"
    "Правила:\n"
    "- Приоритет: локализация проблемы, минимизация риска, обратимость изменений.\n"
    "- Предлагай краткий план диагностики и минимальный безопасный diff.\n"
    "- Указывай проверки/шаги валидации и возможные риски.\n"
)


PROFILE_PARAMS: dict[ProfileName, ProfileParams] = {
    ProfileName.ARCHITECT: ProfileParams(
        instructions=None,
        temperature=None,
        reasoning_effort=None,
        max_calls=None,
        max_total_tool_output_chars=None,
        max_file_chars=None,
        depth_min=0,
        depth_max=6,
        default_depth=None,
    ),
    ProfileName.SURGICAL: ProfileParams(
        instructions=SURGICAL_INSTRUCTIONS,
        temperature=0.0,
        reasoning_effort=None,
        max_calls=12,
        max_total_tool_output_chars=2_000_000,
        max_file_chars=200_000,
        depth_min=0,
        depth_max=2,
        default_depth=1,
    ),
    ProfileName.INCIDENT: ProfileParams(
        instructions=INCIDENT_INSTRUCTIONS,
        temperature=0.2,
        reasoning_effort=None,
        max_calls=40,
        max_total_tool_output_chars=2_000_000,
        max_file_chars=200_000,
        depth_min=0,
        depth_max=4,
        default_depth=2,
    ),
}


DEFAULT_PROFILE = ProfileName.ARCHITECT


def resolve_profile(profile: ProfileName | str | None) -> ProfileParams:
    if profile is None:
        return PROFILE_PARAMS[DEFAULT_PROFILE]
    if isinstance(profile, ProfileName):
        return PROFILE_PARAMS[profile]
    try:
        name = ProfileName(profile)
    except ValueError as exc:
        raise ValueError(f"Unknown profile: {profile}") from exc
    return PROFILE_PARAMS[name]
