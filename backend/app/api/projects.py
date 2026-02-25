# backend/app/api/projects.py
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from ..errors import BadRequestError
from ..policy import require_org_context_async, require_project_access_async
from ..services.docs_service import get_latest_project_doc_async
from ..services.project_service import (
    create_project_async,
)
from ..services.project_service import (
    create_project_from_snapshot_async,
)
from ..services.project_service import delete_project_async
from ..services.project_service import (
    get_file_dependencies_async,
    get_latest_snapshots_async,
    list_project_files_async,
    list_projects_async,
    list_project_tree_entries_async,
    load_graph_async,
    load_local_graph_async,
    enqueue_scan_task_async,
    search_project_nodes_async,
    search_project_semantic_async,
    search_project_text_async,
)
from ..services.task_queue import submit_docs_async
from ..snapshots import store_snapshot_upload

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProject(BaseModel):
    name: str = Field(..., description="UI name for the project")
    root_path: str = Field(..., description="Absolute path on local machine (local-only)")


class ProjectSource(BaseModel):
    kind: str
    label: str


class ProjectResponse(BaseModel):
    id: int
    name: str
    root_path: str | None = None
    source: ProjectSource | None = None


class TaskStatusEnvelope(BaseModel):
    task_id: str = Field(..., description="Background task identifier")
    status: Literal["pending", "running"] = Field(..., description="Task status: pending|running")


def _project_response(project, snapshot_label: str | None = None) -> dict:
    source = None
    if snapshot_label:
        source = {"kind": "snapshot", "label": snapshot_label}
    elif getattr(project, "root_path", ""):
        source = {"kind": "local", "label": project.root_path}
    return {
        "id": project.id,
        "name": project.name,
        "root_path": project.root_path,
        "source": source,
    }


@router.post("")
async def create_project(request: Request, body: CreateProject):
    _, org_id, _ = await require_org_context_async(request, min_role="member")
    project = await create_project_async(request.state.db_session, body.name, body.root_path, org_id)
    return _project_response(project)


@router.post("/from-snapshot")
async def create_project_from_snapshot(
    request: Request,
    name: str = Form(...),
    archive: UploadFile = File(...),
):
    archive_name = archive.filename or ""
    _, org_id, _ = await require_org_context_async(request, min_role="member")
    try:
        meta = await store_snapshot_upload(archive, archive_name)
    except BadRequestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError("Не удалось сохранить архив", context={"reason": str(exc)}) from exc
    project = await create_project_from_snapshot_async(request.state.db_session, name, meta, org_id)
    return _project_response(project, snapshot_label=archive_name)


@router.delete("/{project_id}")
async def delete_project(request: Request, project_id: int):
    _, org_id, _ = await require_org_context_async(request, min_role="admin")
    await delete_project_async(request.state.db_session, project_id, org_id)
    return {"ok": True}


@router.get("")
async def list_projects(request: Request):
    _, org_id, _ = await require_org_context_async(request, min_role="viewer")
    projects = await list_projects_async(request.state.db_session, org_id)
    latest_snapshots = await get_latest_snapshots_async(request.state.db_session, [p.id for p in projects])
    responses = []
    for p in projects:
        snapshot = latest_snapshots.get(p.id)
        label = snapshot.archive_name if snapshot else None
        responses.append(_project_response(p, snapshot_label=label))
    return responses


@router.post("/{project_id}/scan", response_model=TaskStatusEnvelope)
async def scan(
    request: Request,
    project_id: int,
):
    project = await require_project_access_async(request, project_id, min_role="member")
    response = await enqueue_scan_task_async(
        request.state.db_session,
        project.id,
        project.org_id,
    )
    return response


@router.get("/{project_id}/graph")
async def get_graph(request: Request, project_id: int, limit_nodes: int | None = None):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await load_graph_async(request.state.db_session, project.id, project.org_id, limit_nodes)


@router.get("/{project_id}/graph/local")
async def get_local_graph(
    request: Request,
    project_id: int,
    path: str,
    hops: int = 1,
    max_nodes: int = 400,
    max_edges: int = 800,
): 
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await load_local_graph_async(
        request.state.db_session,
        project.id,
        project.org_id,
        path,
        hops,
        max_nodes,
        max_edges,
    )


@router.get("/{project_id}/search")
async def search(request: Request, project_id: int, q: str, limit: int = 20):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await search_project_nodes_async(
        request.state.db_session,
        project.id,
        project.org_id,
        q,
        limit,
    )


@router.get("/{project_id}/search/semantic")
async def search_semantic(
    request: Request,
    project_id: int,
    q: str,
    limit: int = 20,
    prefix: str | None = None,
):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await search_project_semantic_async(
        request.state.db_session,
        project.id,
        project.org_id,
        q,
        limit=limit,
        prefix=prefix,
    )


@router.get("/{project_id}/search/text")
async def search_text(
    request: Request,
    project_id: int,
    q: str,
    limit_files: int = 200,
    limit_matches: int = 50,
    context_chars: int = 160,
    prefix: str | None = None,
    case_sensitive: bool = False,
):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await search_project_text_async(
        request.state.db_session,
        project.id,
        project.org_id,
        q,
        limit_files=limit_files,
        limit_matches=limit_matches,
        context_chars=context_chars,
        prefix=prefix,
        case_sensitive=case_sensitive,
    )


@router.get("/{project_id}/files")
async def files(
    request: Request,
    project_id: int,
    prefix: str | None = None,
    cursor: str | None = None,
    limit: int = 50_000,
):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await list_project_files_async(
        request.state.db_session,
        project.id,
        project.org_id,
        prefix,
        cursor,
        limit,
    )


@router.get("/{project_id}/files/tree")
async def files_tree(
    request: Request,
    project_id: int,
    prefix: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await list_project_tree_entries_async(
        request.state.db_session,
        project.id,
        project.org_id,
        prefix,
        cursor,
        limit,
    )


@router.get("/{project_id}/dependencies")
async def file_dependencies(
    request: Request,
    project_id: int,
    path: str,
    limit: int = 2000,
    cursor_in: str | None = None,
    cursor_out: str | None = None,
):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await get_file_dependencies_async(
        request.state.db_session,
        project.id,
        project.org_id,
        path,
        limit,
        cursor_in,
        cursor_out,
    )


@router.post("/{project_id}/docs/build", response_model=TaskStatusEnvelope)
async def build_docs(
    request: Request,
    project_id: int,
):
    project = await require_project_access_async(request, project_id, min_role="member")
    task_id, task_status = await submit_docs_async(project.id, project.org_id)
    return {"task_id": task_id, "status": task_status}


@router.get("/{project_id}/docs")
async def get_docs(request: Request, project_id: int, kind: str = "overview"):
    project = await require_project_access_async(request, project_id, min_role="viewer")
    return await get_latest_project_doc_async(request.state.db_session, project.id, project.org_id, kind)
