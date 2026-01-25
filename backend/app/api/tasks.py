#backend/app/api/tasks.py
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from ..llm.policy import ProfileName
from ..services.task_service import (
    TaskRequest, describe_task,
    delete_run, get_run, get_run_patch,
    list_runs, run_task_with_background,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class RunTask(BaseModel):
    target_path: str = Field(..., description="Path relative to project root")
    prompt: str = Field(..., description="Any natural language request")
    mode: str | None = Field(default=None, description="analyze|evolve|fix|impact (if omitted: auto-triage)")
    profile: ProfileName | None = Field(
        default=None,
        description="LLM profile: architect|surgical|incident (if omitted: architect)",
    )
    depth: int | None = Field(default=None, description="Dependency depth for context pack")
    dep_mode: str = Field(default="contracts", description="contracts|full")
    apply_patch: bool = Field(default=False, description="Apply patch for fix tasks")
    agentic: bool = Field(
        default=True,
        description="Context strategy: true=agentic tool-based retrieval, false=pack_context",
    )
    agentic_evidence_mode: bool | None = Field(
        default=False,
        description="Require evidence with file/line references in agentic outputs",
    )

    pack_max_files: int | None = Field(default=None, ge=1, le=80, description="Max files in pack_context")
    pack_max_chars_per_file: int | None = Field(default=None, ge=200, le=50_000, description="Max chars per file in pack_context")
    pack_max_total_chars: int | None = Field(default=None, ge=1_000, le=500_000, description="Max total chars in pack_context")

    agentic_max_calls: int | None = Field(default=None, ge=1, le=100, description="Max tool calls in agentic mode")
    agentic_max_file_chars: int | None = Field(default=None, ge=200, le=50_000, description="Max chars per get_file in agentic mode")
    agentic_max_total_tool_output_chars: int | None = Field(default=None, ge=2_000, le=1_000_000, description="Total tool output char budget in agentic mode")
    agentic_temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="Temperature override for agentic mode")

@router.post("/{project_id}/run")
def run_task(project_id: int, body: RunTask, background_tasks: BackgroundTasks, background: bool = False):
    provided_fields = set(getattr(body, "model_fields_set", set()))
    request = TaskRequest(
        target_path=body.target_path,
        prompt=body.prompt,
        mode=body.mode,
        profile=body.profile,
        depth=body.depth,
        dep_mode=body.dep_mode,
        apply_patch=body.apply_patch,
        agentic=body.agentic,
        agentic_evidence_mode=body.agentic_evidence_mode,
        pack_max_files=body.pack_max_files,
        pack_max_chars_per_file=body.pack_max_chars_per_file,
        pack_max_total_chars=body.pack_max_total_chars,
        agentic_max_calls=body.agentic_max_calls,
        agentic_max_file_chars=body.agentic_max_file_chars,
        agentic_max_total_tool_output_chars=body.agentic_max_total_tool_output_chars,
        agentic_temperature=body.agentic_temperature,
        provided_fields=provided_fields,
    )
    return run_task_with_background(project_id, request, background=background, background_tasks=background_tasks)


@router.get("/{project_id}/runs")
def list_runs_endpoint(project_id: int, limit: int = 50):
    return list_runs(project_id, limit=limit)


@router.get("/{project_id}/runs/{run_id}")
def get_run_endpoint(project_id: int, run_id: int):
    return get_run(project_id, run_id)


@router.get("/{project_id}/runs/{run_id}/patch")
def get_run_patch_endpoint(project_id: int, run_id: int):
    return get_run_patch(project_id, run_id)


@router.delete("/{project_id}/runs/{run_id}")
def delete_run_endpoint(project_id: int, run_id: int):
    return delete_run(project_id, run_id)


@router.get("/status/{task_id}")
def get_task_status(task_id: str):
    return describe_task(task_id)
