#backend/app/api/tasks.py
from __future__ import annotations

import json
from typing import Any
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select, delete

from ..db import get_session
from ..config import settings
from ..models import Project, AnalysisRun, FileNode, FileEdge, ModuleContract
from ..contracts import get_or_build_contract
from ..context_pack import pack_context
from ..llm.orchestrator import triage, analyze, evolve, fix
from ..patches import apply_unified_diff, PatchApplyError
from ..utils import resolve_under_root, sha256_text
from ..scan import scan_files
from ..graph import compute_graph_metrics

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

MAX_PATCH_STORE_CHARS = 50_000
PATCH_BLOB_DIRNAME = "patches"

def _store_patch_blob(patch_text: str) -> dict:
    sha = sha256_text(patch_text)
    base = Path(settings.db_dir).resolve()
    patches_dir = (base / PATCH_BLOB_DIRNAME)
    patches_dir.mkdir(parents=True, exist_ok=True)
    fp = (patches_dir / f"{sha}.diff").resolve()

    if base not in fp.parents and fp != base:
        raise RuntimeError("Refusing to write patch blob outside db_dir")
    try:
        with fp.open("x", encoding="utf-8") as f:
            f.write(patch_text)
    except FileExistsError:
        pass
    return {
        "omitted": True,
        "chars": len(patch_text),
        "sha256": sha,
        "storage": "file",
        "file": f"{PATCH_BLOB_DIRNAME}/{sha}.diff",
        "store_limit_chars": MAX_PATCH_STORE_CHARS,
    }

def _llm_http_error(phase: str, e: Exception) -> HTTPException:
    if isinstance(e, RuntimeError):
        return HTTPException(status_code=502, detail=str(e))
    return HTTPException(status_code=502, detail=f"LLM {phase} failed: {e}")

class RunTask(BaseModel):
    target_path: str = Field(..., description="Path relative to project root")
    prompt: str = Field(..., description="Any natural language request")
    mode: str | None = Field(default=None, description="analyze|evolve|fix|impact (if omitted: auto-triage)")
    depth: int | None = Field(default=None, description="Dependency depth for context pack")
    dep_mode: str = Field(default="contracts", description="contracts|full")
    apply_patch: bool = Field(default=False, description="Apply patch for fix tasks")

def _validate_depth(depth: int) -> int:
    if depth < 0 or depth > 6:
        raise HTTPException(status_code=400, detail="depth must be between 0 and 6")
    return depth

@router.post("/{project_id}/run")
def run_task(project_id: int, body: RunTask):
    with get_session() as s:
        proj = s.get(Project, project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    root = Path(proj.root_path).resolve()
    target_raw = body.target_path
    try:
        abs_target, target = resolve_under_root(root, target_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path escapes project root")
    if not abs_target.exists():
        raise HTTPException(status_code=404, detail="Target file not found")
    if not abs_target.is_file():
        raise HTTPException(status_code=400, detail="Target must be a file")

    def _has_node() -> bool:
        with get_session() as s:
            return (
                s.exec(
                    select(FileNode.id).where(
                        FileNode.project_id == project_id,
                        FileNode.path == target,
                    )
                ).first()
                is not None
            )

    if not _has_node():
        try:
            scan_files(project_id, root, [target])
            compute_graph_metrics(project_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to index target file: {e}")
        if not _has_node():
            raise HTTPException(status_code=500, detail="Failed to index target file (node still missing after scan)")

    mode = body.mode
    depth = body.depth
    dep_mode = body.dep_mode
    provided_fields = getattr(body, "model_fields_set", set())

    if mode is not None and mode not in ("analyze", "evolve", "fix", "impact"):
        raise HTTPException(status_code=400, detail="Unknown mode")
    if dep_mode not in ("contracts", "full"):
        raise HTTPException(status_code=400, detail="Unknown dep_mode")

    if mode is None:
        try:
            t = triage(body.prompt)
        except Exception as e:
            raise _llm_http_error("triage", e)

        if not isinstance(t, dict):
            raise HTTPException(status_code=502, detail="LLM triage returned non-object JSON")
        task_kind = t.get("task_kind")
        t_depth = t.get("depth")
        t_dep_mode = t.get("dep_mode")
        if task_kind not in ("analyze", "evolve", "fix", "impact"):
            raise HTTPException(status_code=502, detail=f"LLM triage returned invalid task_kind: {task_kind!r}")
        mode = task_kind
        if depth is None:
            try:
                depth = int(t_depth)
            except Exception:
                raise HTTPException(status_code=502, detail=f"LLM triage returned invalid depth: {t_depth!r}")
        if "dep_mode" not in provided_fields:
            if t_dep_mode not in ("contracts", "full"):
                raise HTTPException(status_code=502, detail=f"LLM triage returned invalid dep_mode: {t_dep_mode!r}")
            dep_mode = t_dep_mode

    if depth is None:
        depth = int(settings.default_depth)
        if depth < 0 or depth > 6:
            raise HTTPException(
                status_code=500,
                detail="Server misconfigured: CODESURGEON_DEFAULT_DEPTH must be between 0 and 6",
            )
    depth = _validate_depth(depth)

    if mode == "impact":
        impacted = _impact(project_id, target)
        result = {"impacted": impacted, "count": len(impacted)}
        model_used = "graph"
    else:
        packed = pack_context(project_id, root, target, depth=depth, dep_mode=dep_mode)
        packed_dict = {
            "target_path": packed.target_path,
            "graph": packed.graph,
            "files": packed.files,
        }
        if mode == "analyze":
            try:
                result = analyze(packed_dict, body.prompt)
            except Exception as e:
                raise _llm_http_error("analyze", e)
            model_used = settings.model_analysis
        elif mode == "evolve":
            try:
                result = evolve(packed_dict, body.prompt)
            except Exception as e:
                raise _llm_http_error("evolve", e)
            model_used = settings.model_analysis
        elif mode == "fix":
            try:
                result = fix(packed_dict, body.prompt)
            except Exception as e:
                raise _llm_http_error("fix", e)
            model_used = settings.model_patch
        else:
            raise HTTPException(status_code=400, detail="Unknown mode")

    result_full: Any = result
    result_for_db: Any = result_full
    result_for_response: Any = result_full
    patch_text_full: str | None = None
    if mode == "fix" and isinstance(result, dict):
        patch_text = result_full.get("patch_unified_diff")
        if isinstance(patch_text, str) and len(patch_text) > MAX_PATCH_STORE_CHARS:
            patch_text_full = patch_text
            meta = _store_patch_blob(patch_text_full)
            compact = dict(result_full)
            compact["patch_unified_diff"] = ""
            compact["patch_unified_diff_meta"] = meta
            result_for_db = compact
            result_for_response = compact

    with get_session() as s:
        run = AnalysisRun(
            project_id=project_id,
            target_path=target,
            mode=mode,
            prompt=body.prompt,
            model_used=model_used,
            result_json=json.dumps(result_for_db, ensure_ascii=False),
        )
        s.add(run)

        n = s.exec(select(FileNode).where(FileNode.project_id==project_id, FileNode.path==target)).first()
        if n and mode in ("analyze", "evolve"):
            n.status = "ok"
            s.add(n)
        s.commit()
        s.refresh(run)

    applied = None
    if mode == "fix" and body.apply_patch:
        try:
            patch_text = patch_text_full
            if patch_text is None and isinstance(result_full, dict):
                patch_text = result_full.get("patch_unified_diff")
            if not isinstance(patch_text, str) or not patch_text.strip():
                raise PatchApplyError("Empty or missing patch_unified_diff")
            modified = apply_unified_diff(root, patch_text)
            modified = sorted(set(modified))
            applied = {"modified": modified}

            try:
                applied["reindexed"] = scan_files(project_id, root, modified)
                compute_graph_metrics(project_id)

                updated_contracts: list[str] = []
                removed_contracts: list[str] = []
                for rp in modified:
                    try:
                        abs_p, rel_norm = resolve_under_root(root, rp)
                        if not abs_p.exists():
                            removed_contracts.append(rel_norm)
                            continue
                        if not abs_p.is_file():
                            continue
                        c = get_or_build_contract(project_id, root, rel_norm)
                        if isinstance(c, dict) and c.get("path"):
                            updated_contracts.append(str(c["path"]))
                    except Exception:
                        continue
                applied["contracts_updated"] = sorted(set(updated_contracts))

                removed_contracts = sorted(set(removed_contracts))
                if removed_contracts:
                    with get_session() as s:
                        s.exec(
                            delete(ModuleContract).where(
                                ModuleContract.project_id == project_id,
                                ModuleContract.path.in_(removed_contracts),
                            )
                        )
                        s.commit()
                    applied["contracts_removed"] = removed_contracts
            except Exception as e:
                applied["reindex_error"] = str(e)

            with get_session() as s:
                patched_nodes = s.exec(
                    select(FileNode).where(
                        FileNode.project_id == project_id,
                        FileNode.path.in_(modified),
                    )
                ).all()
                for n in patched_nodes:
                    n.status = "patched"
                    s.add(n)
                s.commit()
        except PatchApplyError as e:
            applied = {"error": str(e)}

    return {
        "run_id": run.id,
        "mode": mode,
        "depth": depth,
        "dep_mode": dep_mode,
        "result": result_for_response,
        "applied": applied,
    }

@router.get("/{project_id}/runs")
def list_runs(project_id: int, limit: int = 50):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    with get_session() as s:
        runs = s.exec(select(AnalysisRun).where(AnalysisRun.project_id==project_id).order_by(AnalysisRun.id.desc()).limit(limit)).all()
    return [
        {
            "id": r.id, "target_path": r.target_path, "mode": r.mode,
            "prompt": r.prompt, "model_used": r.model_used, "created_at": r.created_at.isoformat()
        }
        for r in runs
    ]

@router.get("/{project_id}/runs/{run_id}")
def get_run(project_id: int, run_id: int):
    with get_session() as s:
        run = s.get(AnalysisRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        result: Any = json.loads(run.result_json or "{}")
    except Exception:
        result = {}

    return {
        "id": run.id,
        "project_id": run.project_id,
        "target_path": run.target_path,
        "mode": run.mode,
        "prompt": run.prompt,
        "model_used": run.model_used,
        "created_at": run.created_at.isoformat(),
        "result": result,
    }

@router.get("/{project_id}/runs/{run_id}/patch")
def get_run_patch(project_id: int, run_id: int):
    with get_session() as s:
        run = s.get(AnalysisRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        data = json.loads(run.result_json or "{}")
    except Exception:
        data = {}

    if isinstance(data, dict):
        patch = data.get("patch_unified_diff")
        if isinstance(patch, str) and patch.strip():
            return {"patch_unified_diff": patch}

        meta = data.get("patch_unified_diff_meta")
        if isinstance(meta, dict):
            sha = meta.get("sha256")
            if isinstance(sha, str) and sha:
                base = Path(settings.db_dir).resolve()
                fp = (base / PATCH_BLOB_DIRNAME / f"{sha}.diff").resolve()
                if base not in fp.parents and fp != base:
                    raise HTTPException(status_code=500, detail="Invalid patch blob path")
                if not fp.exists() or not fp.is_file():
                    raise HTTPException(status_code=404, detail="Patch blob not found")
                try:
                    txt = fp.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to read patch blob: {e}")
                return {"patch_unified_diff": txt}

    raise HTTPException(status_code=404, detail="Patch not found")

def _impact(project_id: int, target: str) -> list[str]:
    visited: set[str] = set()
    frontier: list[str] = [target]
    with get_session() as s:
        while frontier:
            rows = s.exec(
                select(FileEdge.src_path)
                .where(FileEdge.project_id == project_id, FileEdge.dst_path.in_(frontier))
            ).all()
            nxt: list[str] = []
            for row in rows:
                src = row[0] if isinstance(row, (tuple, list)) else row
                if not isinstance(src, str) or not src:
                    continue
                if src in visited:
                    continue
                visited.add(src)
                nxt.append(src)
            frontier = nxt
    return sorted(visited)
