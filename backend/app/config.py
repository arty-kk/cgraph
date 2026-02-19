# backend/app/config.py
from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        alias="STUBGRAPH_CORS_ALLOW_ORIGINS",
    )

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    # OpenAI Responses API stores responses by default; for codebases this is often undesirable.
    openai_store: bool = Field(default=False, alias="STUBGRAPH_OPENAI_STORE")
    # Prompt caching is opt-in (privacy/correctness trade-off).
    openai_prompt_cache_key: str | None = Field(
        default=None,
        alias="STUBGRAPH_OPENAI_PROMPT_CACHE_KEY",
    )
    openai_prompt_cache_retention: str | None = Field(
        default=None,
        alias="STUBGRAPH_OPENAI_PROMPT_CACHE_RETENTION",
    )

    storage_backend: str = Field(default="local", alias="STUBGRAPH_STORAGE_BACKEND")
    s3_bucket: str | None = Field(default=None, alias="STUBGRAPH_S3_BUCKET")
    s3_region: str | None = Field(default=None, alias="STUBGRAPH_S3_REGION")
    s3_endpoint_url: str | None = Field(default=None, alias="STUBGRAPH_S3_ENDPOINT_URL")
    s3_access_key_id: str | None = Field(default=None, alias="STUBGRAPH_S3_ACCESS_KEY_ID")
    s3_secret_access_key: str | None = Field(default=None, alias="STUBGRAPH_S3_SECRET_ACCESS_KEY")
    s3_prefix: str | None = Field(default=None, alias="STUBGRAPH_S3_PREFIX")
    s3_signed_url_ttl_seconds: int = Field(
        default=3600,
        alias="STUBGRAPH_S3_SIGNED_URL_TTL_SECONDS",
    )
    patch_retention_days: int = Field(default=7, alias="STUBGRAPH_PATCH_RETENTION_DAYS")
    snapshot_max_bytes: int = Field(default=200_000_000, alias="STUBGRAPH_SNAPSHOT_MAX_BYTES")
    snapshot_max_files: int = Field(default=200_000, alias="STUBGRAPH_SNAPSHOT_MAX_FILES")
    snapshot_max_file_bytes: int = Field(
        default=50_000_000,
        alias="STUBGRAPH_SNAPSHOT_MAX_FILE_BYTES",
    )
    scan_hash_verify_max_file_bytes: int | None = Field(
        default=None,
        alias="STUBGRAPH_SCAN_HASH_VERIFY_MAX_FILE_BYTES",
    )
    snapshot_max_unpacked_bytes: int = Field(
        default=1_000_000_000,
        alias="STUBGRAPH_SNAPSHOT_MAX_UNPACKED_BYTES",
    )
    allow_local_root_path: bool = Field(default=False, alias="STUBGRAPH_ALLOW_LOCAL_ROOT_PATH")

    celery_broker_url: str = Field(
        default="amqp://guest:guest@localhost:5672//",
        alias="STUBGRAPH_CELERY_BROKER_URL",
    )
    celery_queue_default: str = Field(default="medium", alias="STUBGRAPH_CELERY_QUEUE_DEFAULT")

    auth_enabled: bool = Field(default=False, alias="STUBGRAPH_AUTH_ENABLED")
    auth_allow_public_signup: bool = Field(
        default=False,
        alias="STUBGRAPH_AUTH_ALLOW_PUBLIC_SIGNUP",
    )
    auth_password_pepper: str = Field(default="stubgraph", alias="STUBGRAPH_AUTH_PASSWORD_PEPPER")
    auth_session_ttl_hours: int = Field(default=24, alias="STUBGRAPH_AUTH_SESSION_TTL_HOURS")
    auth_api_key_ttl_days: int | None = Field(
        default=None,
        alias="STUBGRAPH_AUTH_API_KEY_TTL_DAYS",
    )

    redis_url: str = Field(default="redis://localhost:6379/0", alias="STUBGRAPH_REDIS_URL")
    cache_enabled: bool = Field(default=True, alias="STUBGRAPH_CACHE_ENABLED")
    cache_default_ttl_seconds: int = Field(default=300, alias="STUBGRAPH_CACHE_DEFAULT_TTL_SECONDS")
    cache_invalidate_batch_size: int = Field(
        default=1000,
        alias="STUBGRAPH_CACHE_INVALIDATE_BATCH_SIZE",
    )
    rate_limit_enabled: bool = Field(default=True, alias="STUBGRAPH_RATE_LIMIT_ENABLED")
    rate_limit_requests_per_minute: int = Field(
        default=600, alias="STUBGRAPH_RATE_LIMIT_REQUESTS_PER_MINUTE"
    )
    trusted_proxy_cidrs: str = Field(default="", alias="STUBGRAPH_TRUSTED_PROXY_CIDRS")
    task_queue_inflight_heavy_limit: int | None = Field(
        default=None, alias="STUBGRAPH_TASK_QUEUE_INFLIGHT_HEAVY_LIMIT"
    )
    task_queue_enqueue_workers: int = Field(
        default=4,
        alias="STUBGRAPH_TASK_QUEUE_ENQUEUE_WORKERS",
    )

    database_url: str = Field(
        default="postgresql+psycopg://stubgraph:stubgraph@localhost:5432/stubgraph",
        alias="STUBGRAPH_DATABASE_URL",
    )
    db_pool_size: int = Field(default=5, alias="STUBGRAPH_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=0, alias="STUBGRAPH_DB_MAX_OVERFLOW")
    db_pool_timeout_seconds: float = Field(
        default=30.0,
        alias="STUBGRAPH_DB_POOL_TIMEOUT_SECONDS",
    )
    db_pool_recycle_seconds: float = Field(
        default=1800.0,
        alias="STUBGRAPH_DB_POOL_RECYCLE_SECONDS",
    )
    db_dir: Path = Field(default=Path.home() / ".StubGraph", alias="STUBGRAPH_DB_DIR")
    default_depth: int = Field(default=1, alias="STUBGRAPH_DEFAULT_DEPTH")
    max_root_path_chars: int = Field(default=500, alias="STUBGRAPH_MAX_ROOT_PATH_CHARS")
    max_rel_path_chars: int = Field(default=1024, alias="STUBGRAPH_MAX_REL_PATH_CHARS")
    max_prompt_chars: int = Field(default=8000, alias="STUBGRAPH_MAX_PROMPT_CHARS")
    project_lock_timeout_seconds: float = Field(
        default=30.0,
        alias="STUBGRAPH_PROJECT_LOCK_TIMEOUT_SECONDS",
    )
    project_lock_poll_interval_seconds: float = Field(
        default=0.25,
        alias="STUBGRAPH_PROJECT_LOCK_POLL_INTERVAL_SECONDS",
    )

    # Patch application guardrails
    patch_require_in_context: bool = Field(default=True, alias="STUBGRAPH_PATCH_REQUIRE_IN_CONTEXT")
    patch_allow_new_files: bool = Field(default=False, alias="STUBGRAPH_PATCH_ALLOW_NEW_FILES")

    triage_model: str = Field(default="gpt-5-nano", alias="STUBGRAPH_MODEL_TRIAGE")
    analysis_model: str = Field(default="gpt-5-nano", alias="STUBGRAPH_MODEL_ANALYSIS")
    patch_model: str = Field(default="gpt-5-nano", alias="STUBGRAPH_MODEL_PATCH")

    reasoning_effort_triage: str = Field(default="low", alias="STUBGRAPH_REASONING_EFFORT_TRIAGE")
    reasoning_effort_analysis: str = Field(
        default="medium",
        alias="STUBGRAPH_REASONING_EFFORT_ANALYSIS",
    )
    reasoning_effort_patch: str = Field(default="high", alias="STUBGRAPH_REASONING_EFFORT_PATCH")

    compute_scc: bool = Field(default=True, alias="STUBGRAPH_COMPUTE_SCC")
    scc_max_nodes: int = Field(default=4000, alias="STUBGRAPH_SCC_MAX_NODES")
    scc_max_edges: int = Field(default=20000, alias="STUBGRAPH_SCC_MAX_EDGES")

    graph_metrics_incremental_max_paths: int = Field(
        default=200, alias="STUBGRAPH_GRAPH_METRICS_INCREMENTAL_MAX_PATHS"
    )
    graph_metrics_incremental_max_component_nodes: int = Field(
        default=2000, alias="STUBGRAPH_GRAPH_METRICS_INCREMENTAL_MAX_COMPONENT_NODES"
    )
    graph_metrics_incremental_max_component_edges: int = Field(
        default=5000, alias="STUBGRAPH_GRAPH_METRICS_INCREMENTAL_MAX_COMPONENT_EDGES"
    )
    graph_metrics_async_node_threshold: int = Field(
        default=6000, alias="STUBGRAPH_GRAPH_METRICS_ASYNC_NODE_THRESHOLD"
    )
    graph_metrics_async_edge_threshold: int = Field(
        default=25000, alias="STUBGRAPH_GRAPH_METRICS_ASYNC_EDGE_THRESHOLD"
    )

    impact_max_nodes: int | None = Field(default=None, alias="STUBGRAPH_IMPACT_MAX_NODES")
    impact_max_depth: int | None = Field(default=None, alias="STUBGRAPH_IMPACT_MAX_DEPTH")

    openai_timeout_seconds: float = Field(
        default=900.0,
        alias="STUBGRAPH_OPENAI_TIMEOUT_SECONDS",
    )
    openai_max_retries: int = Field(default=3, alias="STUBGRAPH_OPENAI_MAX_RETRIES")

    embeddings_enabled: bool = Field(default=False, alias="STUBGRAPH_EMBEDDINGS_ENABLED")
    embeddings_model: str = Field(
        default="text-embedding-3-small",
        alias="STUBGRAPH_EMBEDDINGS_MODEL",
    )
    embeddings_chunk_size: int = Field(default=1500, alias="STUBGRAPH_EMBEDDINGS_CHUNK_SIZE")
    embeddings_chunk_overlap: int = Field(default=200, alias="STUBGRAPH_EMBEDDINGS_CHUNK_OVERLAP")
    embeddings_max_file_chars: int = Field(
        default=200_000,
        alias="STUBGRAPH_EMBEDDINGS_MAX_FILE_CHARS",
    )
    embeddings_search_max_candidates: int = Field(
        default=500, alias="STUBGRAPH_EMBEDDINGS_SEARCH_MAX_CANDIDATES"
    )
    embeddings_search_max_results: int = Field(
        default=20, alias="STUBGRAPH_EMBEDDINGS_SEARCH_MAX_RESULTS"
    )
    embeddings_daily_chunk_limit: int | None = Field(
        default=None, alias="STUBGRAPH_EMBEDDINGS_DAILY_CHUNK_LIMIT"
    )
    embeddings_daily_query_limit: int | None = Field(
        default=None, alias="STUBGRAPH_EMBEDDINGS_DAILY_QUERY_LIMIT"
    )
    llm_daily_request_limit: int | None = Field(
        default=None, alias="STUBGRAPH_LLM_DAILY_REQUEST_LIMIT"
    )

    # Agentic tool-based retrieval (LLM chooses which context to fetch)
    llm_agentic_retrieval: bool = Field(default=True, alias="STUBGRAPH_LLM_AGENTIC_RETRIEVAL")
    llm_agentic_max_calls: int = Field(default=100, alias="STUBGRAPH_LLM_AGENTIC_MAX_CALLS")
    llm_agentic_max_total_tool_output_chars: int = Field(
        default=2_000_000, alias="STUBGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS"
    )
    llm_agentic_max_file_chars: int = Field(
        default=200_000,
        alias="STUBGRAPH_LLM_AGENTIC_MAX_FILE_CHARS",
    )
    llm_agentic_temperature: float = Field(default=0.0, alias="STUBGRAPH_LLM_AGENTIC_TEMPERATURE")
    llm_agentic_trace_enabled: bool = Field(
        default=True, alias="STUBGRAPH_LLM_AGENTIC_TRACE_ENABLED"
    )
    llm_agentic_max_retry_per_run: int = Field(
        default=1,
        alias="STUBGRAPH_LLM_AGENTIC_MAX_RETRY_PER_RUN",
    )
    llm_agentic_missing_context_stability_threshold: float = Field(
        default=0.9,
        alias="STUBGRAPH_LLM_AGENTIC_MISSING_CONTEXT_STABILITY_THRESHOLD",
    )
    llm_agentic_escalation_max_per_stage: int = Field(
        default=1,
        alias="STUBGRAPH_LLM_AGENTIC_ESCALATION_MAX_PER_STAGE",
    )
    llm_agentic_fs_ops_concurrency: int = Field(
        default=8,
        alias="STUBGRAPH_LLM_AGENTIC_FS_OPS_CONCURRENCY",
    )
    llm_evidence_min_sources: int = Field(
        default=1,
        alias="STUBGRAPH_LLM_EVIDENCE_MIN_SOURCES",
    )
    llm_routing_sla_profile: str = Field(
        default="balanced", alias="STUBGRAPH_LLM_ROUTING_SLA_PROFILE"
    )
    llm_routing_weight_quality: float = Field(
        default=0.4, alias="STUBGRAPH_LLM_ROUTING_WEIGHT_QUALITY"
    )
    llm_routing_weight_latency: float = Field(
        default=0.25, alias="STUBGRAPH_LLM_ROUTING_WEIGHT_LATENCY"
    )
    llm_routing_weight_token_cost: float = Field(
        default=0.2, alias="STUBGRAPH_LLM_ROUTING_WEIGHT_TOKEN_COST"
    )
    llm_routing_weight_fail_rate: float = Field(
        default=0.15, alias="STUBGRAPH_LLM_ROUTING_WEIGHT_FAIL_RATE"
    )
    llm_routing_low_confidence_threshold: float = Field(
        default=0.55, alias="STUBGRAPH_LLM_ROUTING_LOW_CONFIDENCE_THRESHOLD"
    )
    llm_routing_model_stats_json: str = Field(
        default="", alias="STUBGRAPH_LLM_ROUTING_MODEL_STATS_JSON"
    )
    llm_routing_threshold_low: float = Field(
        default=1.35, alias="STUBGRAPH_LLM_ROUTING_THRESHOLD_LOW"
    )
    llm_routing_threshold_mid: float = Field(
        default=1.5, alias="STUBGRAPH_LLM_ROUTING_THRESHOLD_MID"
    )
    llm_routing_threshold_high: float = Field(
        default=1.7, alias="STUBGRAPH_LLM_ROUTING_THRESHOLD_HIGH"
    )
    llm_routing_policy_version: str = Field(
        default="v1", alias="STUBGRAPH_LLM_ROUTING_POLICY_VERSION"
    )
    llm_routing_calibration_enabled: bool = Field(
        default=True, alias="STUBGRAPH_LLM_ROUTING_CALIBRATION_ENABLED"
    )
    llm_routing_calibration_min_samples: int = Field(
        default=20, alias="STUBGRAPH_LLM_ROUTING_CALIBRATION_MIN_SAMPLES"
    )
    llm_routing_calibration_interval_minutes: int = Field(
        default=60, alias="STUBGRAPH_LLM_ROUTING_CALIBRATION_INTERVAL_MINUTES"
    )

    go_build_tags: str = Field(default="", alias="STUBGRAPH_GO_BUILD_TAGS")
    go_include_unexported_symbols: bool = Field(
        default=False, alias="STUBGRAPH_GO_INCLUDE_UNEXPORTED_SYMBOLS"
    )
    task_queue_completed_ttl_seconds: int | None = Field(
        default=None, alias="STUBGRAPH_TASK_QUEUE_COMPLETED_TTL_SECONDS"
    )
    task_queue_max_completed: int | None = Field(
        default=None,
        alias="STUBGRAPH_TASK_QUEUE_MAX_COMPLETED",
    )

    def cors_origins(self) -> list[str]:
        raw = (self.cors_allow_origins or "").strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    @model_validator(mode="after")
    def _validate_limits(self) -> "Settings":
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            self.database_url = env_url
        storage_backend = (self.storage_backend or "local").strip().lower()
        if storage_backend not in {"local", "s3"}:
            raise ValueError("STUBGRAPH_STORAGE_BACKEND должен быть local или s3")
        if storage_backend == "s3" and not (self.s3_bucket and self.s3_bucket.strip()):
            raise ValueError("STUBGRAPH_S3_BUCKET обязателен для S3 хранилища")
        if self.s3_signed_url_ttl_seconds <= 0:
            raise ValueError("STUBGRAPH_S3_SIGNED_URL_TTL_SECONDS должен быть положительным")
        if self.patch_retention_days < 0:
            raise ValueError("STUBGRAPH_PATCH_RETENTION_DAYS должен быть неотрицательным")
        if self.snapshot_max_bytes <= 0:
            raise ValueError("STUBGRAPH_SNAPSHOT_MAX_BYTES должен быть положительным")
        if self.snapshot_max_files <= 0:
            raise ValueError("STUBGRAPH_SNAPSHOT_MAX_FILES должен быть положительным")
        if self.snapshot_max_file_bytes <= 0:
            raise ValueError("STUBGRAPH_SNAPSHOT_MAX_FILE_BYTES должен быть положительным")
        if self.scan_hash_verify_max_file_bytes is None:
            self.scan_hash_verify_max_file_bytes = self.snapshot_max_file_bytes
        if self.scan_hash_verify_max_file_bytes <= 0:
            raise ValueError(
                "STUBGRAPH_SCAN_HASH_VERIFY_MAX_FILE_BYTES должен быть положительным"
            )
        if self.snapshot_max_unpacked_bytes <= 0:
            raise ValueError("STUBGRAPH_SNAPSHOT_MAX_UNPACKED_BYTES должен быть положительным")
        if not isinstance(self.allow_local_root_path, bool):
            raise ValueError("STUBGRAPH_ALLOW_LOCAL_ROOT_PATH должен быть булевым")
        if not isinstance(self.celery_broker_url, str) or not self.celery_broker_url.strip():
            raise ValueError("STUBGRAPH_CELERY_BROKER_URL должен быть непустым")
        if not isinstance(self.redis_url, str) or not self.redis_url.strip():
            raise ValueError("STUBGRAPH_REDIS_URL должен быть непустым")
        if self.db_pool_size <= 0:
            raise ValueError("STUBGRAPH_DB_POOL_SIZE должен быть положительным")
        if self.db_max_overflow < 0:
            raise ValueError("STUBGRAPH_DB_MAX_OVERFLOW должен быть неотрицательным")
        if self.db_pool_timeout_seconds <= 0:
            raise ValueError("STUBGRAPH_DB_POOL_TIMEOUT_SECONDS должен быть положительным")
        if self.db_pool_recycle_seconds <= 0:
            raise ValueError("STUBGRAPH_DB_POOL_RECYCLE_SECONDS должен быть положительным")
        if self.auth_session_ttl_hours <= 0:
            raise ValueError("STUBGRAPH_AUTH_SESSION_TTL_HOURS должен быть положительным")
        if self.auth_api_key_ttl_days is not None and self.auth_api_key_ttl_days <= 0:
            raise ValueError("STUBGRAPH_AUTH_API_KEY_TTL_DAYS должен быть положительным")
        if self.cache_default_ttl_seconds <= 0:
            raise ValueError("STUBGRAPH_CACHE_DEFAULT_TTL_SECONDS должен быть положительным")
        if self.cache_invalidate_batch_size <= 0:
            raise ValueError("STUBGRAPH_CACHE_INVALIDATE_BATCH_SIZE должен быть положительным")
        if self.rate_limit_requests_per_minute <= 0:
            raise ValueError("STUBGRAPH_RATE_LIMIT_REQUESTS_PER_MINUTE должен быть положительным")
        if (
            self.task_queue_inflight_heavy_limit is not None
            and self.task_queue_inflight_heavy_limit <= 0
        ):
            raise ValueError("STUBGRAPH_TASK_QUEUE_INFLIGHT_HEAVY_LIMIT должен быть положительным")
        if self.task_queue_enqueue_workers <= 0:
            raise ValueError("STUBGRAPH_TASK_QUEUE_ENQUEUE_WORKERS должен быть положительным")
        if self.default_depth < 0:
            raise ValueError("STUBGRAPH_DEFAULT_DEPTH должен быть неотрицательным")
        if (self.llm_routing_sla_profile or "balanced").strip().lower() not in {
            "balanced",
            "fast",
            "quality",
            "cheap",
        }:
            raise ValueError(
                "STUBGRAPH_LLM_ROUTING_SLA_PROFILE должен быть balanced, fast, quality или cheap"
            )
        if not (0.0 <= self.llm_routing_low_confidence_threshold <= 1.0):
            raise ValueError(
                "STUBGRAPH_LLM_ROUTING_LOW_CONFIDENCE_THRESHOLD должен быть в диапазоне [0,1]"
            )
        if not (
            1.0 <= self.llm_routing_threshold_low <= self.llm_routing_threshold_mid <= self.llm_routing_threshold_high <= 2.0
        ):
            raise ValueError(
                "STUBGRAPH_LLM_ROUTING_THRESHOLD_* должны удовлетворять 1.0 <= low <= mid <= high <= 2.0"
            )
        if self.llm_routing_calibration_min_samples <= 0:
            raise ValueError(
                "STUBGRAPH_LLM_ROUTING_CALIBRATION_MIN_SAMPLES должен быть положительным"
            )
        if self.llm_routing_calibration_interval_minutes <= 0:
            raise ValueError(
                "STUBGRAPH_LLM_ROUTING_CALIBRATION_INTERVAL_MINUTES должен быть положительным"
            )
        if self.max_root_path_chars <= 0:
            raise ValueError("Лимит длины пути до корня должен быть положительным")
        if self.max_rel_path_chars <= 0:
            raise ValueError("Лимит длины относительного пути должен быть положительным")
        if self.max_prompt_chars <= 0:
            raise ValueError("Лимит длины промпта должен быть положительным")
        if self.scc_max_nodes < 0 or self.scc_max_edges < 0:
            raise ValueError("Параметры SCC должны быть неотрицательными")
        if self.graph_metrics_incremental_max_paths <= 0:
            raise ValueError(
                "STUBGRAPH_GRAPH_METRICS_INCREMENTAL_MAX_PATHS должен быть положительным"
            )
        if self.graph_metrics_incremental_max_component_nodes <= 0:
            raise ValueError(
                "STUBGRAPH_GRAPH_METRICS_INCREMENTAL_MAX_COMPONENT_NODES должен быть положительным"
            )
        if self.graph_metrics_incremental_max_component_edges <= 0:
            raise ValueError(
                "STUBGRAPH_GRAPH_METRICS_INCREMENTAL_MAX_COMPONENT_EDGES должен быть положительным"
            )
        if self.impact_max_nodes is not None and self.impact_max_nodes <= 0:
            raise ValueError("STUBGRAPH_IMPACT_MAX_NODES должен быть положительным")
        if self.impact_max_depth is not None and self.impact_max_depth < 0:
            raise ValueError("STUBGRAPH_IMPACT_MAX_DEPTH должен быть неотрицательным")
        if self.openai_timeout_seconds <= 0:
            raise ValueError("Таймаут OpenAI должен быть положительным")
        if self.openai_max_retries < 0:
            raise ValueError("Количество ретраев OpenAI не может быть отрицательным")
        if self.embeddings_chunk_size <= 0:
            raise ValueError("STUBGRAPH_EMBEDDINGS_CHUNK_SIZE должен быть положительным")
        if self.embeddings_chunk_overlap < 0:
            raise ValueError("STUBGRAPH_EMBEDDINGS_CHUNK_OVERLAP должен быть неотрицательным")
        if self.embeddings_chunk_overlap >= self.embeddings_chunk_size:
            raise ValueError("STUBGRAPH_EMBEDDINGS_CHUNK_OVERLAP должен быть меньше размера чанка")
        if self.embeddings_max_file_chars <= 0:
            raise ValueError("STUBGRAPH_EMBEDDINGS_MAX_FILE_CHARS должен быть положительным")
        if self.embeddings_search_max_candidates <= 0:
            raise ValueError("STUBGRAPH_EMBEDDINGS_SEARCH_MAX_CANDIDATES должен быть положительным")
        if self.embeddings_search_max_results <= 0:
            raise ValueError("STUBGRAPH_EMBEDDINGS_SEARCH_MAX_RESULTS должен быть положительным")
        if not self.embeddings_model or not self.embeddings_model.strip():
            raise ValueError("STUBGRAPH_EMBEDDINGS_MODEL должен быть непустым")
        if self.embeddings_daily_chunk_limit is not None and self.embeddings_daily_chunk_limit <= 0:
            raise ValueError("STUBGRAPH_EMBEDDINGS_DAILY_CHUNK_LIMIT должен быть положительным")
        if self.embeddings_daily_query_limit is not None and self.embeddings_daily_query_limit <= 0:
            raise ValueError("STUBGRAPH_EMBEDDINGS_DAILY_QUERY_LIMIT должен быть положительным")
        if self.llm_daily_request_limit is not None and self.llm_daily_request_limit <= 0:
            raise ValueError("STUBGRAPH_LLM_DAILY_REQUEST_LIMIT должен быть положительным")
        if self.llm_agentic_max_calls <= 0:
            raise ValueError("STUBGRAPH_LLM_AGENTIC_MAX_CALLS должен быть положительным")
        if self.llm_agentic_max_total_tool_output_chars <= 0:
            raise ValueError(
                "STUBGRAPH_LLM_AGENTIC_MAX_TOTAL_TOOL_OUTPUT_CHARS должен быть положительным"
            )
        if self.llm_agentic_max_file_chars <= 0:
            raise ValueError("STUBGRAPH_LLM_AGENTIC_MAX_FILE_CHARS должен быть положительным")
        if self.llm_agentic_temperature < 0 or self.llm_agentic_temperature > 2:
            raise ValueError("STUBGRAPH_LLM_AGENTIC_TEMPERATURE должен быть в диапазоне 0..2")
        if self.llm_agentic_max_retry_per_run < 0:
            raise ValueError("STUBGRAPH_LLM_AGENTIC_MAX_RETRY_PER_RUN должен быть неотрицательным")
        if not (0.0 <= self.llm_agentic_missing_context_stability_threshold <= 1.0):
            raise ValueError(
                "STUBGRAPH_LLM_AGENTIC_MISSING_CONTEXT_STABILITY_THRESHOLD должен быть в "
                "диапазоне [0,1]"
            )
        if self.llm_agentic_escalation_max_per_stage < 0:
            raise ValueError(
                "STUBGRAPH_LLM_AGENTIC_ESCALATION_MAX_PER_STAGE должен быть неотрицательным"
            )
        if self.llm_agentic_fs_ops_concurrency <= 0:
            raise ValueError("STUBGRAPH_LLM_AGENTIC_FS_OPS_CONCURRENCY должен быть положительным")
        if self.llm_evidence_min_sources < 1:
            raise ValueError("STUBGRAPH_LLM_EVIDENCE_MIN_SOURCES должен быть >= 1")
        if self.project_lock_timeout_seconds < 0:
            raise ValueError("STUBGRAPH_PROJECT_LOCK_TIMEOUT_SECONDS должен быть неотрицательным")
        if self.project_lock_poll_interval_seconds <= 0:
            raise ValueError(
                "STUBGRAPH_PROJECT_LOCK_POLL_INTERVAL_SECONDS должен быть положительным"
            )
        if (
            self.task_queue_completed_ttl_seconds is not None
            and self.task_queue_completed_ttl_seconds <= 0
        ):
            raise ValueError("STUBGRAPH_TASK_QUEUE_COMPLETED_TTL_SECONDS должен быть положительным")
        if self.task_queue_max_completed is not None and self.task_queue_max_completed <= 0:
            raise ValueError("STUBGRAPH_TASK_QUEUE_MAX_COMPLETED должен быть положительным")
        return self


settings = Settings()
settings.db_dir.mkdir(parents=True, exist_ok=True)
