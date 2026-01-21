#backend/app/config.py
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        alias="CGRAPH_CORS_ALLOW_ORIGINS",
    )

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    # OpenAI Responses API stores responses by default; for codebases this is often undesirable.
    openai_store: bool = Field(default=False, alias="CGRAPH_OPENAI_STORE")
    # Prompt caching is opt-in (privacy/correctness trade-off).
    openai_prompt_cache_key: str | None = Field(default=None, alias="CGRAPH_OPENAI_PROMPT_CACHE_KEY")
    openai_prompt_cache_retention: str | None = Field(default=None, alias="CGRAPH_OPENAI_PROMPT_CACHE_RETENTION")
    
    db_dir: Path = Field(default=Path.home() / ".CGRAPH", alias="CGRAPH_DB_DIR")
    default_depth: int = Field(default=1, alias="CGRAPH_DEFAULT_DEPTH")
    max_root_path_chars: int = Field(default=500, alias="CGRAPH_MAX_ROOT_PATH_CHARS")
    max_rel_path_chars: int = Field(default=1024, alias="CGRAPH_MAX_REL_PATH_CHARS")
    max_prompt_chars: int = Field(default=8000, alias="CGRAPH_MAX_PROMPT_CHARS")

    # Patch application guardrails
    patch_require_in_context: bool = Field(default=True, alias="CGRAPH_PATCH_REQUIRE_IN_CONTEXT")
    patch_allow_new_files: bool = Field(default=False, alias="CGRAPH_PATCH_ALLOW_NEW_FILES")

    triage_model: str = Field(default="gpt-5-nano", alias="CGRAPH_MODEL_TRIAGE")
    analysis_model: str = Field(default="gpt-5-nano", alias="CGRAPH_MODEL_ANALYSIS")
    patch_model: str = Field(default="gpt-5-nano", alias="CGRAPH_MODEL_PATCH")

    reasoning_effort_triage: str = Field(default="low", alias="CGRAPH_REASONING_EFFORT_TRIAGE")
    reasoning_effort_analysis: str = Field(default="medium", alias="CGRAPH_REASONING_EFFORT_ANALYSIS")
    reasoning_effort_patch: str = Field(default="high", alias="CGRAPH_REASONING_EFFORT_PATCH")

    compute_scc: bool = Field(default=True, alias="CGRAPH_COMPUTE_SCC")
    scc_max_nodes: int = Field(default=4000, alias="CGRAPH_SCC_MAX_NODES")
    scc_max_edges: int = Field(default=20000, alias="CGRAPH_SCC_MAX_EDGES")

    openai_timeout_seconds: float = Field(default=30.0, alias="CGRAPH_OPENAI_TIMEOUT_SECONDS")
    openai_max_retries: int = Field(default=3, alias="CGRAPH_OPENAI_MAX_RETRIES")

    embeddings_enabled: bool = Field(default=False, alias="CGRAPH_EMBEDDINGS_ENABLED")
    embeddings_model: str = Field(default="text-embedding-3-small", alias="CGRAPH_EMBEDDINGS_MODEL")
    embeddings_chunk_size: int = Field(default=1500, alias="CGRAPH_EMBEDDINGS_CHUNK_SIZE")
    embeddings_chunk_overlap: int = Field(default=200, alias="CGRAPH_EMBEDDINGS_CHUNK_OVERLAP")
    embeddings_max_file_chars: int = Field(default=200_000, alias="CGRAPH_EMBEDDINGS_MAX_FILE_CHARS")

    # Agentic tool-based retrieval (LLM chooses which context to fetch)
    llm_agentic_retrieval: bool = Field(default=True, alias="CGRAPH_LLM_AGENTIC_RETRIEVAL")
    llm_agentic_max_calls: int = Field(default=100, alias="CGRAPH_LLM_AGENTIC_MAX_CALLS")
    llm_agentic_max_total_tool_output_chars: int = Field(
        default=180_000, alias="CGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS"
    )
    llm_agentic_max_file_chars: int = Field(default=24_000, alias="CGRAPH_LLM_AGENTIC_MAX_FILE_CHARS")
    llm_agentic_temperature: float = Field(default=0.0, alias="CGRAPH_LLM_AGENTIC_TEMPERATURE")

    go_build_tags: str = Field(default="", alias="CGRAPH_GO_BUILD_TAGS")
    go_include_unexported_symbols: bool = Field(
        default=False, alias="CGRAPH_GO_INCLUDE_UNEXPORTED_SYMBOLS"
    )

    def cors_origins(self) -> list[str]:
        raw = (self.cors_allow_origins or "").strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    @model_validator(mode="after")
    def _validate_limits(self) -> "Settings":
        if self.default_depth < 0:
            raise ValueError("CGRAPH_DEFAULT_DEPTH должен быть неотрицательным")
        if self.max_root_path_chars <= 0:
            raise ValueError("Лимит длины пути до корня должен быть положительным")
        if self.max_rel_path_chars <= 0:
            raise ValueError("Лимит длины относительного пути должен быть положительным")
        if self.max_prompt_chars <= 0:
            raise ValueError("Лимит длины промпта должен быть положительным")
        if self.scc_max_nodes < 0 or self.scc_max_edges < 0:
            raise ValueError("Параметры SCC должны быть неотрицательными")
        if self.openai_timeout_seconds <= 0:
            raise ValueError("Таймаут OpenAI должен быть положительным")
        if self.openai_max_retries < 0:
            raise ValueError("Количество ретраев OpenAI не может быть отрицательным")
        if self.embeddings_chunk_size <= 0:
            raise ValueError("CGRAPH_EMBEDDINGS_CHUNK_SIZE должен быть положительным")
        if self.embeddings_chunk_overlap < 0:
            raise ValueError("CGRAPH_EMBEDDINGS_CHUNK_OVERLAP должен быть неотрицательным")
        if self.embeddings_chunk_overlap >= self.embeddings_chunk_size:
            raise ValueError("CGRAPH_EMBEDDINGS_CHUNK_OVERLAP должен быть меньше размера чанка")
        if self.embeddings_max_file_chars <= 0:
            raise ValueError("CGRAPH_EMBEDDINGS_MAX_FILE_CHARS должен быть положительным")
        if not self.embeddings_model or not self.embeddings_model.strip():
            raise ValueError("CGRAPH_EMBEDDINGS_MODEL должен быть непустым")
        if self.llm_agentic_max_calls <= 0:
            raise ValueError("CGRAPH_LLM_AGENTIC_MAX_CALLS должен быть положительным")
        if self.llm_agentic_max_total_tool_output_chars <= 0:
            raise ValueError("CGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS должен быть положительным")
        if self.llm_agentic_max_file_chars <= 0:
            raise ValueError("CGRAPH_LLM_AGENTIC_MAX_FILE_CHARS должен быть положительным")
        if self.llm_agentic_temperature < 0 or self.llm_agentic_temperature > 2:
            raise ValueError("CGRAPH_LLM_AGENTIC_TEMPERATURE должен быть в диапазоне 0..2")
        return self

settings = Settings()
settings.db_dir.mkdir(parents=True, exist_ok=True)
