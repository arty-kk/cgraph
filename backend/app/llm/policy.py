#backend/app/llm/policy.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from ..config import settings

@dataclass(frozen=True)
class ModelPolicy:
    triage_model: str = settings.triage_model
    analysis_model: str = settings.analysis_model
    patch_model: str = settings.patch_model

    triage_effort: str = settings.reasoning_effort_triage
    analysis_effort: str = settings.reasoning_effort_analysis
    patch_effort: str = settings.reasoning_effort_patch

DEFAULT_POLICY = ModelPolicy()


class ProfileName(str, Enum):
    ARCHITECT = "architect"
    SURGICAL = "surgical"
    INCIDENT = "incident"


@dataclass(frozen=True)
class ProfileParams:
    instructions: str | None
    temperature: float | None
    max_calls: int | None
    max_total_tool_output_chars: int | None
    max_file_chars: int | None
    depth_min: int | None
    depth_max: int | None
    default_depth: int | None


SURGICAL_INSTRUCTIONS = (
    "Ты — CGRAPH: хирургический режим. Твоя цель — точечные изменения с минимальным радиусом влияния.\n"
    "Правила:\n"
    "- Сохраняй текущие контракты и поведение, если пользователь не требует обратного.\n"
    "- Избегай широких правок и предположений; запрашивай только нужный контекст.\n"
    "- Для фикса: предложи минимальный unified diff и конкретные проверки.\n"
)

INCIDENT_INSTRUCTIONS = (
    "Ты — CGRAPH: режим инцидента. Твоя цель — быстрое и безопасное восстановление работоспособности.\n"
    "Правила:\n"
    "- Приоритет: локализация проблемы, минимизация риска, обратимость изменений.\n"
    "- Предлагай краткий план диагностики и минимальный безопасный diff.\n"
    "- Указывай проверки/шаги валидации и возможные риски.\n"
)


PROFILE_PARAMS: dict[ProfileName, ProfileParams] = {
    ProfileName.ARCHITECT: ProfileParams(
        instructions=None,
        temperature=None,
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
        max_calls=12,
        max_total_tool_output_chars=60_000,
        max_file_chars=8_000,
        depth_min=0,
        depth_max=2,
        default_depth=1,
    ),
    ProfileName.INCIDENT: ProfileParams(
        instructions=INCIDENT_INSTRUCTIONS,
        temperature=0.2,
        max_calls=40,
        max_total_tool_output_chars=140_000,
        max_file_chars=16_000,
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
