#backend/app/api/projects.py
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from ..services.project_service import (
    create_project as create_project_service,
    delete_project as delete_project_service,
    get_project,
    list_projects as list_projects_service,
    load_graph, load_local_graph,
    scan_with_background, search_project_nodes,
    list_project_files,
)
from ..services.docs_service import build_project_docs, get_latest_project_doc
from ..services.task_queue import task_queue

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProject(BaseModel):
    name: str = Field(..., description="UI name for the project")
    root_path: str = Field(..., description="Absolute path on local machine")


@router.post("")
def create_project(body: CreateProject):
    project = create_project_service(body.name, body.root_path)
    return {"id": project.id, "name": project.name, "root_path": project.root_path}


@router.delete("/{project_id}")
def delete_project(project_id: int):
    delete_project_service(project_id)
    return {"ok": True}


@router.get("")
def list_projects():
    projects = list_projects_service()
    return [{"id": p.id, "name": p.name, "root_path": p.root_path} for p in projects]


@router.post("/{project_id}/scan")
def scan(project_id: int, background_tasks: BackgroundTasks, background: bool = False):
    get_project(project_id)
    return scan_with_background(project_id, background=background, background_tasks=background_tasks)


@router.get("/{project_id}/graph")
def get_graph(project_id: int, limit_nodes: int | None = None):
    return load_graph(project_id, limit_nodes=limit_nodes)


@router.get("/{project_id}/graph/local")
def get_local_graph(
    project_id: int,
    path: str,
    hops: int = 1,
    max_nodes: int = 400,
    max_edges: int = 800,
):
    return load_local_graph(
        project_id,
        path,
        hops=hops,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )


@router.get("/{project_id}/search")
def search(project_id: int, q: str, limit: int = 20):
    return search_project_nodes(project_id, q, limit=limit)

@router.get("/{project_id}/files")
def files(project_id: int, prefix: str | None = None, limit: int = 50_000):
    return list_project_files(project_id, prefix=prefix, limit=limit)

@router.post("/{project_id}/docs/build")
def build_docs(project_id: int, background_tasks: BackgroundTasks, background: bool = False):
    if background:
        task_id = task_queue.submit(lambda: build_project_docs(project_id))
        if background_tasks is not None:
            background_tasks.add_task(lambda: None)
        return {"task_id": task_id, "status": "pending"}
    return build_project_docs(project_id)

@router.get("/{project_id}/docs")
def get_docs(project_id: int, kind: str = "overview"):
    return get_latest_project_doc(project_id, kind=kind)