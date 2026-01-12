#backend/app/llm/policy.py
from __future__ import annotations

from dataclasses import dataclass
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
