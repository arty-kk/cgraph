# backend/app/services/file_mutation_service.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..graph import update_graph_metrics_incremental
from ..scan import scan_files_async

IndexStatus = Literal["ok", "rescan_scheduled", "failed"]
TaskStatus = Literal["pending", "running", "succeeded", "failed"]


class FileMutationResponse(BaseModel):
    path: str
    saved: bool
    task_id: str | None = None
    task_status: TaskStatus | None = None
    reindexed: object | None = None
    index_status: IndexStatus
    warnings: list[str] = Field(default_factory=list)
    rescan_task: dict | None = None
    rescan_scheduled: bool | None = None
    aborted: bool | None = None
    rollback: str | None = None
    partial: bool | None = None
    conflict: bool | None = None
    conflict_reason: str | None = None
    error: str | None = None
    metrics_pending: bool | None = None


@dataclass
class RollbackResult:
    status: Literal["ok", "skipped", "failed"]
    conflict: bool = False
    conflict_reason: str | None = None


def removed_neighbors(reindexed: object) -> list[str] | None:
    if isinstance(reindexed, dict):
        value = reindexed.get("removed_edge_neighbors")
        return value if isinstance(value, list) else value
    return None


def scan_aborted(reindexed: object) -> bool:
    if isinstance(reindexed, dict):
        return bool(reindexed.get("aborted"))
    return False


def build_mutation_queued_response(
    *,
    path: str,
    task_id: str,
    task_status: Literal["pending", "running"],
) -> dict:
    payload = FileMutationResponse(
        path=path,
        saved=True,
        task_id=task_id,
        task_status=task_status,
        reindexed=False,
        index_status="rescan_scheduled",
        warnings=[],
        rescan_task={"task_id": task_id, "status": task_status},
        rescan_scheduled=True,
    )
    return payload.model_dump(exclude_none=True)


async def run_mutation_indexing_async(
    *,
    project_id: int,
    org_id: int,
    root: Path,
    rel_paths: list[str],
) -> dict:
    reindexed = await scan_files_async(project_id, org_id, root, rel_paths)
    if scan_aborted(reindexed):
        return {
            "ok": False,
            "aborted": True,
            "reindexed": False,
            "index_status": "failed",
            "warnings": ["scan_aborted"],
            "metrics_pending": False,
        }

    removed = removed_neighbors(reindexed)
    metrics_pending = update_graph_metrics_incremental(
        project_id,
        rel_paths,
        removed_edge_neighbors=removed,
    )
    return {
        "ok": True,
        "aborted": False,
        "reindexed": reindexed,
        "index_status": "ok",
        "warnings": [],
        "metrics_pending": bool(metrics_pending),
    }
