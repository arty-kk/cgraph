#backend/app/llm/policy.py
from __future__ import annotations

from dataclasses import dataclass
from ..config import settings

@dataclass(frozen=True)
class ModelPolicy:
    triage_model: str = settings.model_triage
    analysis_model: str = settings.model_analysis
    patch_model: str = settings.model_patch

    triage_effort: str = settings.reasoning_effort_triage
    analysis_effort: str = settings.reasoning_effort_analysis
    patch_effort: str = settings.reasoning_effort_patch

DEFAULT_POLICY = ModelPolicy()
