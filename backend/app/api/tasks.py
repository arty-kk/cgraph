# backend/app/api/tasks.py
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field

from ..llm.policy import ProfileName
from ..policy import require_org_context, require_project_access
from ..services.task_service import (
    TaskRequest,
    apply_run_patch,
    delete_run,
    describe_task,
    get_run,
    get_run_patch,
    list_runs,
    run_task_with_background,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


class RunTask(BaseModel):
    target_path: str = Field(..., description="Path relative to project root")
    prompt: str = Field(..., description="Any natural language request")
    mode: str | None = Field(
        default=None, description="analyze|evolve|fix|impact (if omitted: auto-triage)"
    )
    profile: ProfileName | None = Field(
        default=None,
        description="LLM profile: architect|surgical|incident (if omitted: architect)",
    )
    depth: int | None = Field(default=None, description="Dependency depth for context pack")
    dep_mode: str = Field(default="contracts", description="contracts|full")
    impact_max_nodes: int | None = Field(
        default=None,
        ge=1,
        le=10_000,
        description="Impact mode: max nodes to return (null for unlimited)",
    )
    impact_max_depth: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Impact mode: max BFS depth (null for unlimited)",
    )
    apply_patch: bool = Field(default=False, description="Apply patch for fix tasks")
    agentic: bool = Field(
        default=True,
        description="Context strategy: true=agentic tool-based retrieval, false=pack_context",
    )
    agentic_evidence_mode: bool | None = Field(
        default=False,
        description="Require evidence with file/line references in agentic outputs",
    )
    allow_out_of_context_patch: bool = Field(
        default=False,
        description="Allow patch to extend context with diff paths",
    )

    pack_max_files: int | None = Field(
        default=None, ge=1, le=80, description="Max files in pack_context"
    )
    pack_max_chars_per_file: int | None = Field(
        default=None, ge=1, le=200_000, description="Max chars per file in pack_context"
    )
    pack_max_total_chars: int | None = Field(
        default=None, ge=1, le=2_000_000, description="Max total chars in pack_context"
    )

    agentic_max_calls: int | None = Field(
        default=None, ge=1, le=100, description="Max tool calls in agentic mode"
    )
    agentic_max_file_chars: int | None = Field(
        default=None, ge=1, le=200_000, description="Max chars per get_file in agentic mode"
    )
    agentic_max_total_tool_output_chars: int | None = Field(
        default=None,
        ge=1,
        le=2_000_000,
        description="Total tool output char budget in agentic mode",
    )
    agentic_temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Temperature override for agentic mode"
    )
    agentic_reasoning_effort: str | None = Field(
        default=None,
        description="Reasoning effort override for agentic mode (low|medium|high)",
    )


@router.post("/{project_id}/run")
def run_task(
    request: Request,
    project_id: int,
    body: RunTask,
    background_tasks: BackgroundTasks,
    background: bool = False,
):
    project = require_project_access(request, project_id, min_role="member")
    provided_fields = set(getattr(body, "model_fields_set", set()))
    request = TaskRequest(
        target_path=body.target_path,
        prompt=body.prompt,
        mode=body.mode,
        profile=body.profile,
        depth=body.depth,
        dep_mode=body.dep_mode,
        impact_max_nodes=body.impact_max_nodes,
        impact_max_depth=body.impact_max_depth,
        apply_patch=body.apply_patch,
        allow_out_of_context_patch=body.allow_out_of_context_patch,
        agentic=body.agentic,
        agentic_evidence_mode=body.agentic_evidence_mode,
        pack_max_files=body.pack_max_files,
        pack_max_chars_per_file=body.pack_max_chars_per_file,
        pack_max_total_chars=body.pack_max_total_chars,
        agentic_max_calls=body.agentic_max_calls,
        agentic_max_file_chars=body.agentic_max_file_chars,
        agentic_max_total_tool_output_chars=body.agentic_max_total_tool_output_chars,
        agentic_temperature=body.agentic_temperature,
        agentic_reasoning_effort=body.agentic_reasoning_effort,
        provided_fields=provided_fields,
    )
    return run_task_with_background(
        project.id,
        project.org_id,
        request,
        background=background,
        background_tasks=background_tasks,
    )


@router.get("/{project_id}/runs")
def list_runs_endpoint(request: Request, project_id: int, limit: int = 50):
    project = require_project_access(request, project_id, min_role="viewer")
    return list_runs(project.id, project.org_id, limit=limit)


@router.get("/{project_id}/runs/{run_id}")
def get_run_endpoint(request: Request, project_id: int, run_id: int):
    project = require_project_access(request, project_id, min_role="viewer")
    return get_run(project.id, project.org_id, run_id)


@router.get("/{project_id}/runs/{run_id}/patch")
def get_run_patch_endpoint(request: Request, project_id: int, run_id: int):
    project = require_project_access(request, project_id, min_role="viewer")
    return get_run_patch(project.id, project.org_id, run_id)


@router.post("/{project_id}/runs/{run_id}/apply")
def apply_run_patch_endpoint(request: Request, project_id: int, run_id: int):
    project = require_project_access(request, project_id, min_role="member")
    return apply_run_patch(project.id, project.org_id, run_id)


@router.delete("/{project_id}/runs/{run_id}")
def delete_run_endpoint(request: Request, project_id: int, run_id: int):
    project = require_project_access(request, project_id, min_role="member")
    return delete_run(project.id, project.org_id, run_id)


@router.get("/status/{task_id}")
def get_task_status(request: Request, task_id: str):
    _, org_id, _ = require_org_context(request, min_role="viewer")
    return describe_task(task_id, org_id)
