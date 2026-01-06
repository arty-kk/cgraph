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
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    target_path: str
    mode: str
    prompt: str
    model_used: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    result_json: str
