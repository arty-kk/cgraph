#backend/app/models.py
from __future__ import annotations

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import datetime
from sqlalchemy import UniqueConstraint

class Project(SQLModel, table=True):
    __tablename__ = "project"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    root_path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class FileNode(SQLModel, table=True):
    __tablename__ = "filenode"
    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_filenode_project_path"),
    )
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
    file_size: int = Field(default=0)

class FileEdge(SQLModel, table=True):
    __tablename__ = "fileedge"
    __table_args__ = (
        UniqueConstraint("project_id", "src_path", "dst_path", "kind", name="uq_fileedge_project_src_dst_kind"),
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
            "project_id", "method", "path", "source_path", "handler_name", "lineno",
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
            "project_id", "method", "path", "source_path", "lineno",
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
            "project_id", "method", "path", "source_path", "handler_name", "lineno",
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
            "project_id", "method", "path", "source_path", "lineno",
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
