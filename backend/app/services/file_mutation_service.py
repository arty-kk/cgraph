# backend/app/services/file_mutation_service.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from fastapi import BackgroundTasks
from pydantic import BaseModel, Field

from ..errors import LockedError
from ..graph import update_graph_metrics_incremental
from ..logging import get_logger
from ..scan import scan_files
from ..services.project_service import scan_with_background
from ..utils import ProjectLockTimeout

IndexStatus = Literal["ok", "rescan_scheduled", "failed"]


class FileMutationResponse(BaseModel):
    path: str
    saved: bool
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


def _build_response(
    *,
    path: str,
    saved: bool,
    reindexed: object | None,
    index_status: IndexStatus,
    warnings: list[str] | None = None,
    rescan_task: dict | None = None,
    rescan_scheduled: bool | None = None,
    aborted: bool | None = None,
    rollback: str | None = None,
    partial: bool | None = None,
    conflict: bool | None = None,
    conflict_reason: str | None = None,
    error: str | None = None,
    metrics_pending: bool | None = None,
) -> dict:
    payload = FileMutationResponse(
        path=path,
        saved=saved,
        reindexed=reindexed,
        index_status=index_status,
        warnings=warnings or [],
        rescan_task=rescan_task,
        rescan_scheduled=rescan_scheduled,
        aborted=aborted,
        rollback=rollback,
        partial=partial,
        conflict=conflict,
        conflict_reason=conflict_reason,
        error=error,
        metrics_pending=metrics_pending,
    )
    return payload.model_dump(exclude_none=True)


def _warn(code: str, warnings: list[str]) -> None:
    if code not in warnings:
        warnings.append(code)


def handle_mutation_scan(
    *,
    project_id: int,
    org_id: int,
    root: Path,
    rel_paths: list[str],
    response_path: str,
    operation: str,
    background_tasks: BackgroundTasks | None,
    rollback: Callable[[], RollbackResult],
) -> dict:
    logger = get_logger("stubgraph.file_mutation")
    try:
        reindexed = scan_files(project_id, org_id, root, rel_paths)
        if scan_aborted(reindexed):
            logger.warning(
                "Scan aborted after %s",
                operation,
                extra={"path": response_path, "operation": operation},
            )
            rescan_task = scan_with_background(
                project_id,
                org_id,
                background=True,
                background_tasks=background_tasks,
            )
            return _build_response(
                path=response_path,
                saved=True,
                reindexed=False,
                index_status="rescan_scheduled",
                warnings=["scan_aborted"],
                rescan_task=rescan_task,
                rescan_scheduled=True,
                aborted=True,
            )
        removed = removed_neighbors(reindexed)
        metrics_pending = update_graph_metrics_incremental(
            project_id,
            rel_paths,
            removed_edge_neighbors=removed,
            background_tasks=background_tasks,
        )
        return _build_response(
            path=response_path,
            saved=True,
            reindexed=reindexed,
            index_status="ok",
            warnings=[],
            metrics_pending=metrics_pending,
        )
    except ProjectLockTimeout as exc:
        raise LockedError(
            "Проект сейчас занят, повторите позже",
            context={"project_id": project_id},
        ) from exc
    except Exception as error:  # noqa: BLE001
        logger.exception(
            "Scan failed after %s",
            operation,
            extra={"path": response_path, "operation": operation},
        )
        rescan_task = scan_with_background(
            project_id,
            org_id,
            background=True,
            background_tasks=background_tasks,
        )
        rollback_result = rollback()
        warnings: list[str] = ["scan_failed"]
        if rollback_result.status == "ok":
            _warn("rollback_ok", warnings)
        elif rollback_result.status == "skipped":
            _warn("rollback_skipped", warnings)
        else:
            _warn("rollback_failed", warnings)

        saved = rollback_result.status != "ok"
        partial = rollback_result.status != "ok"
        index_status: IndexStatus = "failed" if not saved else "rescan_scheduled"
        return _build_response(
            path=response_path,
            saved=saved,
            reindexed=False,
            index_status=index_status,
            warnings=warnings,
            rescan_task=rescan_task,
            rescan_scheduled=True,
            rollback=rollback_result.status,
            partial=partial,
            conflict=rollback_result.conflict,
            conflict_reason=rollback_result.conflict_reason,
            error=str(error),
        )
