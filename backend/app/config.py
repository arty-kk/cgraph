#backend/app/config.py
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")

    db_dir: Path = Field(default=Path.home() / ".code-surgeon", alias="CODESURGEON_DB_DIR")
    default_depth: int = Field(default=1, alias="CODESURGEON_DEFAULT_DEPTH")

    model_triage: str = Field(default="gpt-5-nano", alias="CODESURGEON_MODEL_TRIAGE")
    model_analysis: str = Field(default="gpt-5-mini", alias="CODESURGEON_MODEL_ANALYSIS")
    model_patch: str = Field(default="gpt-5", alias="CODESURGEON_MODEL_PATCH")

    reasoning_effort_triage: str = Field(default="minimal", alias="CODESURGEON_REASONING_EFFORT_TRIAGE")
    reasoning_effort_analysis: str = Field(default="medium", alias="CODESURGEON_REASONING_EFFORT_ANALYSIS")
    reasoning_effort_patch: str = Field(default="medium", alias="CODESURGEON_REASONING_EFFORT_PATCH")

    compute_scc: bool = Field(default=True, alias="CODESURGEON_COMPUTE_SCC")
    scc_max_nodes: int = Field(default=4000, alias="CODESURGEON_SCC_MAX_NODES")
    scc_max_edges: int = Field(default=20000, alias="CODESURGEON_SCC_MAX_EDGES")

settings = Settings()
settings.db_dir.mkdir(parents=True, exist_ok=True)
