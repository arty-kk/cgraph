#backend/app/services/task_service.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks
from sqlmodel import delete, select
from sqlalchemy import func

from ..config import settings
from ..context_pack import pack_context
from ..contracts import get_or_build_contract
from ..errors import (
    BadRequestError,
    ExternalServiceError,
    LimitExceededError,
    NotFoundError,
    ServerError,
)
from ..graph import compute_graph_metrics, update_graph_metrics_incremental
from ..llm.orchestrator import analyze, evolve, fix, triage, plan_task
from ..llm.agentic import analyze_agentic, evolve_agentic, fix_agentic, AgenticMeta
from ..models import AnalysisRun, FileEdge, FileNode, ModuleContract
from ..patches import PatchApplyError, apply_unified_diff, delete_patch_blob_for_sha
from ..scan import scan_files
from ..utils import normalize_project_root, project_lock, resolve_under_root, sha256_text
from ..db import get_session
from ..logging import get_logger
from .project_service import get_project, scan_with_background
from .task_queue import TaskState, task_queue

MAX_PATCH_STORE_CHARS = 50_000
PATCH_BLOB_DIRNAME = "patches"
MAX_GRAPH_DEPS_FOR_LLM = 500
MAX_GRAPH_INBOUND_FOR_LLM = 200
MAX_GRAPH_OUTBOUND_FOR_LLM = 200
MAX_OMITTED_PATHS_FOR_LLM = 200
MAX_OMITTED_METRICS_FOR_LLM = 50
MIN_GRAPH_NODES_FOR_READY = 2
MIN_GRAPH_EDGES_FOR_READY = 1
GRAPH_NOT_READY_WARNING = "graph not built"

logger = get_logger("cgraph.api")

PLAN_TZ_EMPTY = {
    "summary": "",
    "requirements": [],
    "constraints": [],
    "sdlc_plan": [],
    "acceptance_criteria": [],
    "risks": [],
    "open_questions": [],
    "deliverables": [],
}

@dataclass
class TaskRequest:
    target_path: str
    prompt: str
    mode: str | None
    depth: int | None
    dep_mode: str
    apply_patch: bool
    agentic: bool
    agentic_evidence_mode: bool | None = None

    provided_fields: set[str]

    # pack_context advanced
    pack_max_files: int | None = None
    pack_max_chars_per_file: int | None = None
    pack_max_total_chars: int | None = None

    # agentic advanced
    agentic_max_calls: int | None = None
    agentic_max_file_chars: int | None = None
    agentic_max_total_tool_output_chars: int | None = None
    agentic_temperature: float | None = None

def _clamp_int(value: int | None, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value) if value is not None else int(default)
    except Exception:
        v = int(default)
    return max(lo, min(hi, v))

def _clamp_float(value: float | None, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value) if value is not None else float(default)
    except Exception:
        v = float(default)
    return max(lo, min(hi, v))

def _store_patch_blob(patch_text: str) -> dict:
    sha = sha256_text(patch_text)
    base = Path(settings.db_dir).resolve()
    patches_dir = base / PATCH_BLOB_DIRNAME
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


def _llm_http_error(phase: str, error: Exception) -> None:
    if isinstance(error, RuntimeError):
        raise ExternalServiceError(str(error), context={"phase": phase})
    raise ExternalServiceError(f"LLM {phase} failed", context={"phase": phase})


def _validate_depth(depth: int) -> int:
    if depth < 0 or depth > 6:
        raise BadRequestError("depth должно быть в диапазоне 0..6")
    return depth


def _impact(project_id: int, target: str) -> list[str]:
    visited: set[str] = set()
    frontier: list[str] = [target]
    SQLITE_IN_CHUNK = 400

    def _chunks(seq: list[str], size: int) -> list[list[str]]:
        return [seq[i : i + size] for i in range(0, len(seq), size)]

    with get_session() as session:
        while frontier:
            frontier = [p for p in list(dict.fromkeys(frontier)) if isinstance(p, str) and p]
            nxt: list[str] = []
            for chunk in _chunks(frontier, SQLITE_IN_CHUNK):
                rows = session.exec(
                    select(FileEdge.src_path).where(
                        FileEdge.project_id == project_id,
                        FileEdge.dst_path.in_(chunk),
                    )
                ).all()
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


def _ensure_node_exists(project_id: int, target: str, root: Path) -> None:
    def _has_node() -> bool:
        with get_session() as session:
            return (
                session.exec(
                    select(FileNode.id).where(
                        FileNode.project_id == project_id,
                        FileNode.path == target,
                    )
                ).first()
                is not None
            )

    if _has_node():
        return

    try:
        with project_lock(project_id):
            scan_files(project_id, root, [target])
            compute_graph_metrics(project_id)
    except Exception as error:  # noqa: BLE001
        raise ServerError(
            "Не удалось проиндексировать целевой файл", context={"reason": str(error)}
        ) from error
    if not _has_node():
        raise ServerError(
            "Не удалось проиндексировать целевой файл (узел отсутствует после сканирования)",
            context={"target": target},
        )


def _graph_warning(project_id: int) -> str | None:
    with get_session() as session:
        nodes_row = session.exec(
            select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
        ).one()
        edges_row = session.exec(
            select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
        ).one()

    node_count = int(nodes_row[0] if isinstance(nodes_row, (tuple, list)) else nodes_row or 0)
    edge_count = int(edges_row[0] if isinstance(edges_row, (tuple, list)) else edges_row or 0)

    if node_count < MIN_GRAPH_NODES_FOR_READY or edge_count < MIN_GRAPH_EDGES_FOR_READY:
        return GRAPH_NOT_READY_WARNING
    return None


def _node_metrics_from_row(node: FileNode) -> dict[str, object]:
    return {
        "path": node.path,
        "language": node.language,
        "loc": node.loc,
        "complexity": node.complexity,
        "fan_in": node.fan_in,
        "fan_out": node.fan_out,
        "scc_id": node.scc_id,
        "status": node.status,
    }


def _load_node_metrics(project_id: int, paths: list[str]) -> dict[str, dict[str, object]]:
    node_metrics: dict[str, dict[str, object]] = {}
    if not paths:
        return node_metrics
    with get_session() as session:
        rows = session.exec(
            select(FileNode).where(
                FileNode.project_id == project_id,
                FileNode.path.in_(paths),
            )
        ).all()
    for n in rows:
        if not isinstance(n.path, str) or not n.path:
            continue
        node_metrics[n.path] = _node_metrics_from_row(n)
    return node_metrics


def _load_contract_summary(project_id: int, target: str) -> dict[str, object] | None:
    with get_session() as session:
        contract = session.exec(
            select(ModuleContract).where(
                ModuleContract.project_id == project_id,
                ModuleContract.path == target,
            )
        ).first()
    if contract is None or not isinstance(contract.contract_json, str):
        return None
    try:
        data = json.loads(contract.contract_json)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    summary: dict[str, object] = {
        "path": data.get("path"),
        "language": data.get("language"),
    }
    exports = data.get("exports")
    if isinstance(exports, list):
        summary["exports"] = exports
    module_doc = data.get("module_doc")
    if isinstance(module_doc, str) and module_doc.strip():
        summary["module_doc"] = module_doc
    notes = data.get("notes")
    if isinstance(notes, str) and notes.strip():
        summary["notes"] = notes
    return summary


def _plan_tz_skipped(reason: str) -> dict:
    skipped = dict(PLAN_TZ_EMPTY)
    skipped["summary"] = reason
    return skipped


def run_task(project_id: int, request: TaskRequest) -> dict:
    project = get_project(project_id)

    if len(request.prompt) > settings.max_prompt_chars:
        raise LimitExceededError(
            "Промпт слишком длинный",
            context={"max_chars": settings.max_prompt_chars},
        )

    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)
    abs_target, target = resolve_under_root(
        root, request.target_path, max_length=settings.max_rel_path_chars
    )
    if not abs_target.exists():
        raise NotFoundError("Целевой файл не найден", context={"path": target})
    if not abs_target.is_file():
        raise BadRequestError("Цель должна быть файлом")

    _ensure_node_exists(project_id, target, root)
    warning = _graph_warning(project_id)
    graph_scan_task: dict | None = None
    if warning == GRAPH_NOT_READY_WARNING:
        graph_scan_task = scan_with_background(project_id, background=True)
    graph_scan_task_id = graph_scan_task.get("task_id") if graph_scan_task else None
    graph_scan_status = graph_scan_task.get("status") if graph_scan_task else None

    mode = request.mode
    depth = request.depth
    dep_mode = request.dep_mode

    if mode is not None and mode not in ("analyze", "evolve", "fix", "impact"):
        raise BadRequestError("Неизвестный режим")
    if dep_mode not in ("contracts", "full"):
        raise BadRequestError("Неизвестный dep_mode")

    if not settings.openai_api_key and (mode is None or mode in ("analyze", "evolve", "fix")):
        raise BadRequestError(
            "OPENAI_API_KEY не задан. Для Run без LLM доступен только режим impact. "
            "Укажи mode=impact или настрой ключ.",
            context={"mode": mode or "auto"},
        )

    if mode is None:
        try:
            triage_result = triage(request.prompt)
        except Exception as error:  # noqa: BLE001
            _llm_http_error("triage", error)

        if not isinstance(triage_result, dict):
            raise ExternalServiceError("Ответ LLM триажа не является объектом JSON")
        task_kind = triage_result.get("task_kind")
        triage_depth = triage_result.get("depth")
        triage_dep_mode = triage_result.get("dep_mode")
        if task_kind not in ("analyze", "evolve", "fix", "impact"):
            raise ExternalServiceError(
                "LLM triage вернул неподдерживаемый task_kind",
                context={"task_kind": task_kind},
            )
        mode = task_kind
        if depth is None:
            try:
                depth = int(triage_depth)
            except Exception:  # noqa: BLE001
                raise ExternalServiceError(
                    "LLM triage вернул некорректную глубину",
                    context={"depth": triage_depth},
                )
        if "dep_mode" not in request.provided_fields:
            if triage_dep_mode not in ("contracts", "full"):
                raise ExternalServiceError(
                    "LLM triage вернул некорректный dep_mode",
                    context={"dep_mode": triage_dep_mode},
                )
            dep_mode = triage_dep_mode

    if depth is None:
        depth = int(settings.default_depth)
        if depth < 0 or depth > 6:
            raise BadRequestError(
                "Неверная конфигурация сервера: DEFAULT_DEPTH должен быть от 0 до 6",
                context={"default_depth": settings.default_depth},
            )
    depth = _validate_depth(depth)

    allowed_patch_paths: set[str] | None = None
    agentic_meta: AgenticMeta | None = None
    use_agentic = bool(request.agentic) and bool(getattr(settings, "llm_agentic_retrieval", True))
    evidence_mode = bool(request.agentic_evidence_mode)
    plan_tz: dict | None = None
    plan_source: str | None = None

    if mode == "impact":
        impacted = _impact(project_id, target)
        result = {"impacted": impacted, "count": len(impacted)}
        model_used = "graph"
        retrieval_used = "graph"
        retrieval_settings = {"graph": {}}
        if settings.openai_api_key:
            paths_for_metrics = sorted({target, *impacted})
            knowledge = {
                "target_path": target,
                "impacted": impacted,
                "nodes": _load_node_metrics(project_id, paths_for_metrics),
            }
            try:
                plan_tz = plan_task(knowledge, request.prompt)
            except Exception as error:  # noqa: BLE001
                _llm_http_error("plan", error)
            plan_source = "graph"
        else:
            plan_tz = _plan_tz_skipped("Планирование пропущено: OPENAI_API_KEY не задан.")
            plan_source = "skipped"
    else:
        retrieval_used = "agentic" if use_agentic else "pack"

        # pack_context budgets (effective)
        pack_max_files = _clamp_int(request.pack_max_files, 25, 1, 80)
        pack_max_chars_per_file = _clamp_int(request.pack_max_chars_per_file, 12_000, 200, 50_000)
        pack_max_total_chars = _clamp_int(request.pack_max_total_chars, 120_000, 1_000, 500_000)
        if pack_max_total_chars < pack_max_chars_per_file:
            pack_max_total_chars = pack_max_chars_per_file

        # agentic budgets (effective, cannot exceed server ceilings)
        srv_calls = int(getattr(settings, "llm_agentic_max_calls", 24))
        srv_file = int(getattr(settings, "llm_agentic_max_file_chars", 24_000))
        srv_total = int(getattr(settings, "llm_agentic_max_total_tool_output_chars", 180_000))
        srv_temp = float(getattr(settings, "llm_agentic_temperature", 0.0))

        complexity_coeff = 1.0
        complexity_inputs: dict[str, object] | None = None
        if use_agentic:
            mode_weights = {
                "analyze": 0.0,
                "evolve": 0.1,
                "fix": 0.2,
                "impact": 0.0,
            }
            depth_norm = max(0.0, min(1.0, depth / 6.0))
            prompt_len = len(request.prompt)
            prompt_norm = min(
                1.0,
                prompt_len / max(1, int(settings.max_prompt_chars)),
            )
            with get_session() as session:
                nodes_row = session.exec(
                    select(func.count())
                    .select_from(FileNode)
                    .where(FileNode.project_id == project_id)
                ).one()
            project_nodes = int(nodes_row[0] if isinstance(nodes_row, (tuple, list)) else nodes_row or 0)
            project_norm = min(1.0, project_nodes / 1_000.0)
            complexity_coeff = _clamp_float(
                1.0
                + depth_norm
                + float(mode_weights.get(mode, 0.0))
                + prompt_norm
                + project_norm,
                1.0,
                1.0,
                2.0,
            )
            complexity_inputs = {
                "depth": depth,
                "prompt_len": prompt_len,
                "project_nodes": project_nodes,
                "mode": mode,
            }

        base_agentic_max_calls = _clamp_int(request.agentic_max_calls, srv_calls, 1, 100)
        base_agentic_max_file_chars = _clamp_int(
            request.agentic_max_file_chars, srv_file, 200, 50_000
        )
        base_agentic_max_total_tool_output_chars = _clamp_int(
            request.agentic_max_total_tool_output_chars, srv_total, 2_000, 1_000_000
        )

        agentic_max_calls = min(
            int(round(base_agentic_max_calls * complexity_coeff)),
            srv_calls,
        )
        agentic_max_file_chars = min(
            int(round(base_agentic_max_file_chars * complexity_coeff)),
            srv_file,
        )
        agentic_max_total_tool_output_chars = min(
            int(round(base_agentic_max_total_tool_output_chars * complexity_coeff)),
            srv_total,
        )
        agentic_temperature = _clamp_float(request.agentic_temperature, srv_temp, 0.0, 2.0)

        retrieval_settings = (
            {
                "agentic": {
                    "complexity_coeff": complexity_coeff,
                    "complexity_inputs": complexity_inputs,
                    "max_calls": agentic_max_calls,
                    "max_file_chars": agentic_max_file_chars,
                    "max_total_tool_output_chars": agentic_max_total_tool_output_chars,
                    "temperature": agentic_temperature,
                    "agentic_evidence_mode": evidence_mode,
                }
            }
            if use_agentic
            else {
                "pack": {
                    "max_files": pack_max_files,
                    "max_chars_per_file": pack_max_chars_per_file,
                    "max_total_chars": pack_max_total_chars,
                }
            }
        )

        if use_agentic:
            knowledge: dict[str, object] = {"target_path": target}
            node_metrics = _load_node_metrics(project_id, [target])
            if target in node_metrics:
                knowledge["node"] = node_metrics[target]
            contract_summary = _load_contract_summary(project_id, target)
            if contract_summary is not None:
                knowledge["contract"] = contract_summary
            try:
                plan_tz = plan_task(knowledge, request.prompt)
            except Exception as error:  # noqa: BLE001
                _llm_http_error("plan", error)
            plan_source = "agentic"
            allowed_patch_paths = {target}
            try:
                if mode == "analyze":
                    result, agentic_meta = analyze_agentic(
                        project_id,
                        root,
                        target,
                        depth=depth,
                        user_prompt=request.prompt,
                        max_calls=agentic_max_calls,
                        max_file_chars=agentic_max_file_chars,
                        max_total_tool_output_chars=agentic_max_total_tool_output_chars,
                        temperature=agentic_temperature,
                        evidence_mode=evidence_mode,
                    )
                    model_used = settings.analysis_model
                elif mode == "evolve":
                    result, agentic_meta = evolve_agentic(
                        project_id,
                        root,
                        target,
                        depth=depth,
                        user_prompt=request.prompt,
                        max_calls=agentic_max_calls,
                        max_file_chars=agentic_max_file_chars,
                        max_total_tool_output_chars=agentic_max_total_tool_output_chars,
                        temperature=agentic_temperature,
                        evidence_mode=evidence_mode,
                    )
                    model_used = settings.analysis_model
                elif mode == "fix":
                    result, agentic_meta = fix_agentic(
                        project_id,
                        root,
                        target,
                        depth=depth,
                        user_prompt=request.prompt,
                        max_calls=agentic_max_calls,
                        max_file_chars=agentic_max_file_chars,
                        max_total_tool_output_chars=agentic_max_total_tool_output_chars,
                        temperature=agentic_temperature,
                        evidence_mode=evidence_mode,
                    )
                    model_used = settings.patch_model
                else:
                    raise BadRequestError("Неизвестный режим")
            except Exception as error:  # noqa: BLE001
                _llm_http_error(mode or "agentic", error)

            if agentic_meta is not None:
                # Files read via get_contract/get_symbol are whitelisted for patching.
                allowed_patch_paths = set(agentic_meta.full_file_paths) | {target}
                try:
                    if isinstance(retrieval_settings, dict) and isinstance(retrieval_settings.get("agentic"), dict):
                        retrieval_settings["agentic"]["tool_calls_used"] = int(agentic_meta.tool_calls)
                        retrieval_settings["agentic"]["tool_output_chars_used"] = int(agentic_meta.total_tool_output_chars)
                        retrieval_settings["agentic"]["cache_hits"] = int(getattr(agentic_meta, "cache_hits", 0))
                        retrieval_settings["agentic"]["files_read"] = int(len(agentic_meta.full_file_paths or []))
                        retrieval_settings["agentic"]["self_check_ok"] = agentic_meta.self_check_ok
                        retrieval_settings["agentic"]["self_check_notes"] = list(
                            agentic_meta.self_check_notes or []
                        )
                        retrieval_settings["agentic"]["self_check_missing_context"] = list(
                            agentic_meta.self_check_missing_context or []
                        )
                        if settings.llm_agentic_trace_enabled:
                            retrieval_settings["agentic"]["tool_trace"] = list(
                                agentic_meta.tool_trace or []
                            )
                except Exception:
                    pass
        else:
            packed = pack_context(
                project_id,
                root,
                target,
                depth=depth,
                dep_mode=dep_mode,
                mode=mode,
                max_files=pack_max_files,
                max_chars_per_file=pack_max_chars_per_file,
                max_total_chars=pack_max_total_chars,
            )

            graph_raw = packed.graph if isinstance(packed.graph, dict) else {}
        
            included_paths = {
                p for p in (
                    f.get("path") for f in packed.files
                    if isinstance(f, dict) and isinstance(f.get("path"), str)
                )
                if isinstance(p, str) and p
            }
            allowed_patch_paths = included_paths | {target}

            deps_total = 0
            deps_limited: list[str] = []
            omitted_total = 0
            omitted_sample: list[str] = []
            deps_raw = graph_raw.get("deps") or []
            if isinstance(deps_raw, list):
                for d in deps_raw:
                    if not isinstance(d, str) or not d:
                        continue
                    deps_total += 1
                    if len(deps_limited) < MAX_GRAPH_DEPS_FOR_LLM:
                        deps_limited.append(d)
                    if d not in included_paths:
                        omitted_total += 1
                        if len(omitted_sample) < MAX_OMITTED_PATHS_FOR_LLM:
                            omitted_sample.append(d)

            inbound_total = 0
            inbound_limited: list[str] = []
            inbound_raw = graph_raw.get("inbound") or []
            if isinstance(inbound_raw, list):
                for d in inbound_raw:
                    if not isinstance(d, str) or not d:
                        continue
                    inbound_total += 1
                    if len(inbound_limited) < MAX_GRAPH_INBOUND_FOR_LLM:
                        inbound_limited.append(d)

            outbound_total = 0
            outbound_limited: list[str] = []
            outbound_raw = graph_raw.get("outbound") or []
            if isinstance(outbound_raw, list):
                for d in outbound_raw:
                    if not isinstance(d, str) or not d:
                        continue
                    outbound_total += 1
                    if len(outbound_limited) < MAX_GRAPH_OUTBOUND_FOR_LLM:
                        outbound_limited.append(d)

            graph_for_llm = dict(graph_raw)
            graph_for_llm["deps"] = deps_limited
            graph_for_llm["deps_total"] = deps_total
            graph_for_llm["deps_truncated"] = deps_total > len(deps_limited)
            graph_for_llm["inbound"] = inbound_limited
            graph_for_llm["inbound_total"] = inbound_total
            graph_for_llm["inbound_truncated"] = inbound_total > len(inbound_limited)
            graph_for_llm["outbound"] = outbound_limited
            graph_for_llm["outbound_total"] = outbound_total
            graph_for_llm["outbound_truncated"] = outbound_total > len(outbound_limited)

            node_metrics: dict[str, dict[str, object]] = {}
            metrics_sample = omitted_sample[:MAX_OMITTED_METRICS_FOR_LLM]
            paths_for_metrics = sorted(set(included_paths).union(set(metrics_sample)))
            if paths_for_metrics:
                with get_session() as session:
                    rows = session.exec(
                        select(FileNode).where(
                            FileNode.project_id == project_id,
                            FileNode.path.in_(paths_for_metrics),
                        )
                    ).all()
                for n in rows:
                    if not isinstance(n.path, str) or not n.path:
                        continue
                    node_metrics[n.path] = {
                        "path": n.path,
                        "language": n.language,
                        "loc": n.loc,
                        "complexity": n.complexity,
                        "fan_in": n.fan_in,
                        "fan_out": n.fan_out,
                        "scc_id": n.scc_id,
                        "status": n.status,
                    }

            packed_dict = {
                "target_path": packed.target_path,
                "graph": graph_for_llm,
                "files": packed.files,
                "nodes": node_metrics,
                "context_omitted_paths": omitted_sample,
                "context_omitted_paths_total": omitted_total,
                "context_omitted_paths_truncated": omitted_total > len(omitted_sample),
            }
            try:
                plan_tz = plan_task(packed_dict, request.prompt)
            except Exception as error:  # noqa: BLE001
                _llm_http_error("plan", error)
            plan_source = "pack"
            if mode == "analyze":
                try:
                    result = analyze(packed_dict, request.prompt)
                except Exception as error:  # noqa: BLE001
                    _llm_http_error("analyze", error)
                model_used = settings.analysis_model
            elif mode == "evolve":
                try:
                    result = evolve(packed_dict, request.prompt)
                except Exception as error:  # noqa: BLE001
                    _llm_http_error("evolve", error)
                model_used = settings.analysis_model
            elif mode == "fix":
                try:
                    result = fix(packed_dict, request.prompt)
                except Exception as error:  # noqa: BLE001
                    _llm_http_error("fix", error)
                model_used = settings.patch_model
            else:
                raise BadRequestError("Неизвестный режим")

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

    with get_session() as session:
        run = AnalysisRun(
            project_id=project_id,
            target_path=target,
            mode=mode,
            prompt=request.prompt,
            model_used=model_used,
            depth=depth,
            dep_mode=dep_mode,
            retrieval=retrieval_used,
            retrieval_settings_json=json.dumps(retrieval_settings, ensure_ascii=False),
            apply_patch=bool(request.apply_patch),
            result_json=json.dumps(result_for_db, ensure_ascii=False),
        )
        session.add(run)

        node = session.exec(
            select(FileNode).where(FileNode.project_id == project_id, FileNode.path == target)
        ).first()
        if node and mode in ("analyze", "evolve"):
            node.status = "ok"
            session.add(node)
        session.commit()
        session.refresh(run)

    applied = None
    if mode == "fix" and request.apply_patch:
        try:
            patch_text = patch_text_full
            if patch_text is None and isinstance(result_full, dict):
                patch_text = result_full.get("patch_unified_diff")
            if not isinstance(patch_text, str) or not patch_text.strip():
                raise PatchApplyError("Empty or missing patch_unified_diff")

            with project_lock(project_id):
                allowed = None
                if bool(getattr(settings, "patch_require_in_context", True)):
                    allowed = allowed_patch_paths
                modified = apply_unified_diff(
                    root,
                    patch_text,
                    allowed_rel_paths=allowed,
                    allow_new_files=bool(getattr(settings, "patch_allow_new_files", False)),
                )
                modified = sorted(set(modified))
                applied = {"modified": modified}

                try:
                    applied["reindexed"] = scan_files(project_id, root, modified)
                    removed_edge_neighbors = None
                    if isinstance(applied.get("reindexed"), dict):
                        removed_edge_neighbors = applied["reindexed"].get("removed_edge_neighbors")
                    update_graph_metrics_incremental(
                        project_id,
                        modified,
                        removed_edge_neighbors=removed_edge_neighbors,
                    )

                    updated_contracts: list[str] = []
                    removed_contracts: list[str] = []
                    for rel_path in modified:
                        try:
                            abs_path, rel_norm = resolve_under_root(
                                root, rel_path, max_length=settings.max_rel_path_chars
                            )
                            if not abs_path.exists():
                                removed_contracts.append(rel_norm)
                                continue
                            if not abs_path.is_file():
                                continue
                            contract = get_or_build_contract(project_id, root, rel_norm)
                            if isinstance(contract, dict) and contract.get("path"):
                                updated_contracts.append(str(contract["path"]))
                        except Exception:  # noqa: BLE001
                            continue
                    applied["contracts_updated"] = sorted(set(updated_contracts))

                    removed_contracts = sorted(set(removed_contracts))
                    if removed_contracts:
                        with get_session() as session:
                            session.exec(
                                delete(ModuleContract).where(
                                    ModuleContract.project_id == project_id,
                                    ModuleContract.path.in_(removed_contracts),
                                )
                            )
                            session.commit()
                        applied["contracts_removed"] = removed_contracts
                except Exception as error:  # noqa: BLE001
                    applied["reindex_error"] = str(error)

                with get_session() as session:
                    patched_nodes = session.exec(
                        select(FileNode).where(
                            FileNode.project_id == project_id,
                            FileNode.path.in_(modified),
                        )
                    ).all()
                    for node in patched_nodes:
                        node.status = "patched"
                        session.add(node)
                    session.commit()
        except PatchApplyError as error:
            applied = {"error": str(error)}

    if applied is not None:
        with get_session() as session:
            run_update = session.get(AnalysisRun, run.id)
            if run_update:
                run_update.applied_json = json.dumps(applied, ensure_ascii=False)
                session.add(run_update)
                session.commit()

    return {
        "run_id": run.id,
        "mode": mode,
        "depth": depth,
        "dep_mode": dep_mode,
        "retrieval": retrieval_used,
        "retrieval_settings": retrieval_settings,
        "apply_patch": bool(request.apply_patch),
        "result": result_for_response,
        "plan_tz": plan_tz,
        "plan_source": plan_source,
        "applied": applied,
        "warning": warning,
        "graph_scan_task_id": graph_scan_task_id,
        "graph_scan_status": graph_scan_status,
    }


def run_task_with_background(
    project_id: int, request: TaskRequest, background: bool = False, background_tasks: BackgroundTasks | None = None
) -> dict:
    if background:
        task_id = task_queue.submit(lambda: run_task(project_id, request))
        if background_tasks is not None:
            background_tasks.add_task(lambda: None)
        return {"task_id": task_id, "status": "pending"}
    return run_task(project_id, request)


def list_runs(project_id: int, limit: int = 50) -> list[dict]:
    if limit < 1 or limit > 200:
        raise BadRequestError("limit должен быть в диапазоне 1..200")
    with get_session() as session:
        runs = (
            session.exec(
                select(AnalysisRun)
                .where(AnalysisRun.project_id == project_id)
                .order_by(AnalysisRun.id.desc())
                .limit(limit)
            ).all()
        )
    return [
        {
            "id": run.id,
            "target_path": run.target_path,
            "mode": run.mode,
            "prompt": run.prompt,
            "model_used": run.model_used,
            "created_at": run.created_at.isoformat(),
        }
        for run in runs
    ]


def get_run(project_id: int, run_id: int) -> dict:
    with get_session() as session:
        run = session.get(AnalysisRun, run_id)
    if not run or run.project_id != project_id:
        raise NotFoundError("Запуск не найден", context={"run_id": run_id, "project_id": project_id})

    try:
        result: Any = json.loads(run.result_json or "{}")
    except Exception:  # noqa: BLE001
        result = {}

    try:
        retrieval_settings: Any = json.loads(run.retrieval_settings_json or "{}")
    except Exception:  # noqa: BLE001
        retrieval_settings = {}

    try:
        applied: Any = json.loads(run.applied_json or "null")
    except Exception:  # noqa: BLE001
        applied = None

    warning = _graph_warning(project_id)
    graph_scan_task: dict | None = None
    if warning == GRAPH_NOT_READY_WARNING:
        graph_scan_task = scan_with_background(project_id, background=True)
    graph_scan_task_id = graph_scan_task.get("task_id") if graph_scan_task else None
    graph_scan_status = graph_scan_task.get("status") if graph_scan_task else None

    return {
        "id": run.id,
        "project_id": run.project_id,
        "target_path": run.target_path,
        "mode": run.mode,
        "prompt": run.prompt,
        "model_used": run.model_used,
        "depth": run.depth,
        "dep_mode": run.dep_mode,
        "retrieval": run.retrieval,
        "retrieval_settings": retrieval_settings,
        "apply_patch": run.apply_patch,
        "applied": applied,
        "created_at": run.created_at.isoformat(),
        "result": result,
        "warning": warning,
        "graph_scan_task_id": graph_scan_task_id,
        "graph_scan_status": graph_scan_status,
    }


def get_run_patch(project_id: int, run_id: int) -> dict:
    with get_session() as session:
        run = session.get(AnalysisRun, run_id)
    if not run or run.project_id != project_id:
        raise NotFoundError("Патч не найден", context={"run_id": run_id, "project_id": project_id})

    try:
        data = json.loads(run.result_json or "{}")
    except Exception:  # noqa: BLE001
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
                    raise BadRequestError("Некорректный путь к сохранённому патчу")
                if not fp.exists() or not fp.is_file():
                    raise NotFoundError("Сохранённый патч не найден", context={"sha": sha})
                try:
                    text = fp.read_text(encoding="utf-8", errors="replace")
                except Exception as error:  # noqa: BLE001
                    raise BadRequestError("Не удалось прочитать патч", context={"reason": str(error)})
                return {"patch_unified_diff": text}

    raise NotFoundError("Патч не найден", context={"run_id": run_id})


def delete_run(project_id: int, run_id: int) -> dict:
    with get_session() as session:
        run = session.get(AnalysisRun, run_id)
        if not run or run.project_id != project_id:
            raise NotFoundError("Запуск не найден", context={"run_id": run_id, "project_id": project_id})
        try:
            data = json.loads(run.result_json or "{}")
        except Exception:  # noqa: BLE001
            data = {}
        if isinstance(data, dict):
            meta = data.get("patch_unified_diff_meta")
            if isinstance(meta, dict):
                sha = meta.get("sha256")
                if isinstance(sha, str) and sha:
                    delete_patch_blob_for_sha(sha)
        session.delete(run)
        session.commit()
    return {"ok": True}


def describe_task(task_id: str) -> dict:
    state: TaskState | None = task_queue.get(task_id)
    if not state:
        raise NotFoundError("Задача не найдена", context={"task_id": task_id})
    payload: dict[str, Any] = {"task_id": task_id, "status": state.status}
    if state.error:
        payload["error"] = state.error
    if state.result is not None:
        payload["result"] = state.result
    return payload
