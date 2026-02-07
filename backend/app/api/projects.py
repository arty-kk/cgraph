# backend/app/api/projects.py
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from pydantic import BaseModel, Field

from ..config import settings
from ..errors import BadRequestError
from ..policy import require_org_context, require_project_access
from ..services.docs_service import build_project_docs, get_latest_project_doc
from ..services.project_service import (
    create_project as create_project_service,
)
from ..services.project_service import (
    create_project_from_snapshot as create_project_from_snapshot_service,
)
from ..services.project_service import (
    delete_project as delete_project_service,
)
from ..services.project_service import (
    get_latest_snapshots,
    list_project_files,
    load_graph,
    load_local_graph,
    scan_with_background,
    search_project_nodes,
    search_project_semantic,
    search_project_text,
)
from ..services.project_service import (
    list_projects as list_projects_service,
)
from ..services.task_queue import task_queue

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
def create_project(request: Request, body: CreateProject):
    _, org_id, _ = require_org_context(request, min_role="member")
    project = create_project_service(body.name, body.root_path, org_id)
    return _project_response(project)


@router.post("/from-snapshot")
async def create_project_from_snapshot(
    request: Request,
    name: str = Form(...),
    archive: UploadFile = File(...),
):
    archive_name = archive.filename or ""
    chunk_size = 1024 * 1024
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await archive.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > settings.snapshot_max_bytes:
            raise BadRequestError(
                "Архив слишком большой",
                context={"max_bytes": settings.snapshot_max_bytes, "size": total_bytes},
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    _, org_id, _ = require_org_context(request, min_role="member")
    project = create_project_from_snapshot_service(name, data, archive_name, org_id)
    return _project_response(project, snapshot_label=archive_name)


@router.delete("/{project_id}")
def delete_project(request: Request, project_id: int):
    _, org_id, _ = require_org_context(request, min_role="admin")
    delete_project_service(project_id, org_id)
    return {"ok": True}


@router.get("")
def list_projects(request: Request):
    _, org_id, _ = require_org_context(request, min_role="viewer")
    projects = list_projects_service(org_id)
    latest_snapshots = get_latest_snapshots([p.id for p in projects])
    responses = []
    for p in projects:
        snapshot = latest_snapshots.get(p.id)
        label = snapshot.archive_name if snapshot else None
        responses.append(_project_response(p, snapshot_label=label))
    return responses


@router.post("/{project_id}/scan")
def scan(
    request: Request,
    project_id: int,
    background_tasks: BackgroundTasks,
    background: bool = False,
):
    project = require_project_access(request, project_id, min_role="member")
    return scan_with_background(
        project.id,
        project.org_id,
        background=background,
        background_tasks=background_tasks,
    )


@router.get("/{project_id}/graph")
def get_graph(request: Request, project_id: int, limit_nodes: int | None = None):
    project = require_project_access(request, project_id, min_role="viewer")
    return load_graph(project.id, project.org_id, limit_nodes=limit_nodes)


@router.get("/{project_id}/graph/local")
def get_local_graph(
    request: Request,
    project_id: int,
    path: str,
    hops: int = 1,
    max_nodes: int = 400,
    max_edges: int = 800,
):
    project = require_project_access(request, project_id, min_role="viewer")
    return load_local_graph(
        project.id,
        project.org_id,
        path,
        hops=hops,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )


@router.get("/{project_id}/search")
def search(request: Request, project_id: int, q: str, limit: int = 20):
    project = require_project_access(request, project_id, min_role="viewer")
    return search_project_nodes(project.id, project.org_id, q, limit=limit)


@router.get("/{project_id}/search/semantic")
def search_semantic(
    request: Request,
    project_id: int,
    q: str,
    limit: int = 20,
    prefix: str | None = None,
):
    project = require_project_access(request, project_id, min_role="viewer")
    return search_project_semantic(project.id, project.org_id, q, limit=limit, prefix=prefix)


@router.get("/{project_id}/search/text")
def search_text(
    request: Request,
    project_id: int,
    q: str,
    limit_files: int = 200,
    limit_matches: int = 50,
    context_chars: int = 160,
    prefix: str | None = None,
    case_sensitive: bool = False,
):
    project = require_project_access(request, project_id, min_role="viewer")
    return search_project_text(
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
def files(request: Request, project_id: int, prefix: str | None = None, limit: int = 50_000):
    project = require_project_access(request, project_id, min_role="viewer")
    return list_project_files(project.id, project.org_id, prefix=prefix, limit=limit)


@router.post("/{project_id}/docs/build")
def build_docs(
    request: Request,
    project_id: int,
    background_tasks: BackgroundTasks,
    background: bool = False,
):
    project = require_project_access(request, project_id, min_role="member")
    if background:
        task_id = task_queue.submit_docs(project.id, project.org_id)
        if background_tasks is not None:
            background_tasks.add_task(lambda: None)
        return {"task_id": task_id, "status": "pending"}
    return build_project_docs(project.id, project.org_id)


@router.get("/{project_id}/docs")
def get_docs(request: Request, project_id: int, kind: str = "overview"):
    project = require_project_access(request, project_id, min_role="viewer")
    return get_latest_project_doc(project.id, project.org_id, kind=kind)
