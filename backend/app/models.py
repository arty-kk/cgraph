# backend/app/models.py
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, Computed, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    __tablename__ = "project"
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    name: str
    root_path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("email", name="uq_user_email"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    password_hash: str
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class BootstrapSentinel(SQLModel, table=True):
    __tablename__ = "bootstrapsentinel"
    __table_args__ = (UniqueConstraint("key", name="uq_bootstrapsentinel_key"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True)


class Organization(SQLModel, table=True):
    __tablename__ = "organization"
    __table_args__ = (Index("uq_organization_slug", "slug", unique=True),)
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    slug: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class OrgMembership(SQLModel, table=True):
    __tablename__ = "orgmembership"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_orgmembership_org_user"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    user_id: int = Field(index=True)
    role: str = Field(default="member", index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class OrgUsage(SQLModel, table=True):
    __tablename__ = "orgusage"
    __table_args__ = (UniqueConstraint("org_id", "day", "kind", name="uq_orgusage_org_day_kind"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    day: date = Field(index=True)
    kind: str = Field(index=True)
    count: int = Field(default=0)


class Plan(SQLModel, table=True):
    __tablename__ = "plan"
    __table_args__ = (UniqueConstraint("name", name="uq_plan_name"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    llm_enabled: bool = Field(default=True)
    embeddings_enabled: bool = Field(default=True)
    llm_daily_request_limit: int | None = Field(default=None)
    embeddings_daily_chunk_limit: int | None = Field(default=None)
    embeddings_daily_query_limit: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class OrgSubscription(SQLModel, table=True):
    __tablename__ = "orgsubscription"
    __table_args__ = (UniqueConstraint("org_id", name="uq_orgsubscription_org_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    plan_id: int = Field(index=True)
    status: str = Field(default="active", index=True)
    current_period_start: datetime = Field(index=True)
    current_period_end: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class OrgEntitlement(SQLModel, table=True):
    __tablename__ = "orgentitlement"
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_orgentitlement_org_key"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    key: str = Field(index=True)
    value_int: int | None = Field(default=None)
    value_bool: bool | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class UserSession(SQLModel, table=True):
    __tablename__ = "usersession"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    token_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: datetime = Field(index=True)
    revoked_at: datetime | None = Field(default=None, index=True)


class ApiKey(SQLModel, table=True):
    __tablename__ = "apikey"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(default="default")
    token_prefix: str = Field(index=True)
    token_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: datetime | None = Field(default=None, index=True)
    revoked_at: datetime | None = Field(default=None, index=True)


class RepoSnapshot(SQLModel, table=True):
    __tablename__ = "reposnapshot"
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    project_id: int = Field(index=True)
    content_sha256: str = Field(index=True)
    archive_name: str
    storage_json: str
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class FileNode(SQLModel, table=True):
    __tablename__ = "filenode"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_filenode_project_path"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    path: str = Field(index=True)
    language: str = Field(default="unknown")
    loc: int = Field(default=0)
    complexity: int = Field(default=0)
    fan_in: int = Field(default=0)
    fan_out: int = Field(default=0)
    scc_id: int = Field(default=-1)
    status: str = Field(default="new")
    file_hash: str = Field(default="")
    file_mtime: float = Field(default=0)
    file_mtime_ns: int = Field(default=0)
    file_size: int = Field(default=0)


class FileEdge(SQLModel, table=True):
    __tablename__ = "fileedge"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "src_path", "dst_path", "kind", name="uq_fileedge_project_src_dst_kind"
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    src_path: str = Field(index=True)
    dst_path: str = Field(index=True)
    kind: str = Field(default="import")
    raw: str = Field(default="")


class ModuleContract(SQLModel, table=True):
    __tablename__ = "modulecontract"
    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_modulecontract_project_path"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    path: str = Field(index=True)
    file_hash: str
    contract_json: str


class AnalysisRun(SQLModel, table=True):
    __tablename__ = "analysisrun"
    # Store run parameters in explicit nullable columns for easier querying; keep
    # nested settings in JSON text fields for forward-compatible payloads.
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    project_id: int = Field(index=True)
    target_path: str
    mode: str
    prompt: str
    model_used: str
    depth: Optional[int] = Field(default=None)
    dep_mode: Optional[str] = Field(default=None)
    retrieval: Optional[str] = Field(default=None)
    retrieval_settings_json: Optional[str] = Field(default=None)
    apply_patch: Optional[bool] = Field(default=None)
    applied_json: Optional[str] = Field(default=None)
    allowed_patch_paths_json: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    result_json: str


class ProjectDoc(SQLModel, table=True):
    __tablename__ = "projectdoc"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    kind: str = Field(default="overview", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    content_md: str = Field(default="")


class ApiRoute(SQLModel, table=True):
    __tablename__ = "apiroute"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "handler_name",
            "lineno",
            name="uq_apiroute_project_method_path_src_handler_line",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    method: str = Field(index=True)
    path: str = Field(index=True)
    path_skeleton: str = Field(default="", index=True)
    router_prefix: str = Field(default="")
    source_path: str = Field(index=True)
    handler_name: str = Field(default="")
    lineno: int = Field(default=0)
    decorator: str = Field(default="")


class ApiCall(SQLModel, table=True):
    __tablename__ = "apicall"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "lineno",
            name="uq_apicall_project_method_path_src_line",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    method: str = Field(index=True)
    path: str = Field(index=True)
    path_skeleton: str = Field(default="", index=True)
    source_path: str = Field(index=True)
    lineno: int = Field(default=0)
    client: str = Field(default="")


class ApiInclude(SQLModel, table=True):
    __tablename__ = "apiinclude"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "parent_source_path",
            "parent_instance",
            "child_source_path",
            "child_instance",
            "prefix",
            "lineno",
            name="uq_apiinclude_project_parent_child_prefix_line",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    parent_source_path: str = Field(index=True)
    parent_instance: str = Field(default="", index=True)
    child_source_path: str = Field(default="", index=True)
    child_instance: str = Field(default="", index=True)
    child_ref: str = Field(default="")
    child_module_spec: str = Field(default="")
    prefix: str = Field(default="")
    lineno: int = Field(default=0)


class ApiRouteContract(SQLModel, table=True):
    __tablename__ = "apiroutecontract"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "handler_name",
            "lineno",
            name="uq_apiroutecontract_project_method_path_src_handler_line",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    method: str = Field(index=True)
    path: str = Field(index=True)  # local path as stored in ApiRoute
    source_path: str = Field(index=True)
    handler_name: str = Field(default="", index=True)
    lineno: int = Field(default=0)
    contract_json: str = Field(default="")


class ApiCallMeta(SQLModel, table=True):
    __tablename__ = "apicallmeta"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "method",
            "path",
            "source_path",
            "lineno",
            name="uq_apicallmeta_project_method_path_src_line",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    method: str = Field(index=True)
    path: str = Field(index=True)
    source_path: str = Field(index=True)
    lineno: int = Field(default=0)
    wrapper_name: str = Field(default="")
    wrapper_response_type: str = Field(default="")
    wrapper_body_type: str = Field(default="")
    wrapper_params_json: str = Field(default="[]")
    body_keys_json: str = Field(default="[]")
    notes: str = Field(default="")


class TsTypeDef(SQLModel, table=True):
    __tablename__ = "tstypedef"
    __table_args__ = (
        UniqueConstraint("project_id", "name", "source_path", name="uq_tstypedef_project_name_src"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    name: str = Field(index=True)
    kind: str = Field(default="type")
    source_path: str = Field(index=True)
    fields_json: str = Field(default="[]")


class FileChunkEmbedding(SQLModel, table=True):
    __tablename__ = "filechunkembedding"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "path",
            "chunk_index",
            "file_hash",
            name="uq_filechunkembedding_project_path_chunk_hash",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    path: str = Field(index=True)
    chunk_index: int
    file_hash: str = Field(index=True)
    embedding_json: str
    symbol_name: str = Field(default="")
    symbol_start_line: int = Field(default=0)
    symbol_end_line: int = Field(default=0)


class FileText(SQLModel, table=True):
    __tablename__ = "filetext"
    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_filetext_project_path"),
        Index("ix_filetext_search", "search", postgresql_using="gin"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    path: str = Field(index=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    search: str | None = Field(
        sa_column=Column(
            TSVECTOR,
            Computed("to_tsvector('simple', content)", persisted=True),
        )
    )


class TaskJob(SQLModel, table=True):
    __tablename__ = "taskjob"
    __table_args__ = (
        Index(
            "uq_taskjob_org_idempotency_key_active",
            "org_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("status IN ('pending','running')"),
        ),
    )
    id: str = Field(primary_key=True)
    org_id: int = Field(index=True)
    status: str = Field(index=True)
    queue: str = Field(default="medium", index=True)
    idempotency_key: str | None = Field(default=None, index=True)
    result_json: str | None = Field(default=None)
    error: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None, index=True)
