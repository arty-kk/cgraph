#backend/app/graph.py
from __future__ import annotations

from typing import Any
from sqlmodel import select
from sqlalchemy import text, func
from .db import get_session
from .models import FileNode, FileEdge
from .config import settings
import networkx as nx

def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default

def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default

def compute_graph_metrics(project_id: int) -> None:
    with get_session() as s:
        node_rows = s.exec(select(FileNode.id, FileNode.path).where(FileNode.project_id == project_id)).all()
        if not node_rows:
            return

        indeg_rows = s.exec(
            select(FileEdge.dst_path, func.count())
            .where(FileEdge.project_id == project_id)
            .group_by(FileEdge.dst_path)
        ).all()
        outdeg_rows = s.exec(
            select(FileEdge.src_path, func.count())
            .where(FileEdge.project_id == project_id)
            .group_by(FileEdge.src_path)
        ).all()
 
        indeg: dict[str, int] = {}
        for p, c in indeg_rows:
            if isinstance(p, str) and p:
                indeg[p] = _as_int(c, 0)

        outdeg: dict[str, int] = {}
        for p, c in outdeg_rows:
            if isinstance(p, str) and p:
                outdeg[p] = _as_int(c, 0)

        scc_map: dict[str, int] = {}
        compute_scc = bool(getattr(settings, "compute_scc", True))
        max_nodes = _as_int(getattr(settings, "scc_max_nodes", 4000), 4000)
        max_edges = _as_int(getattr(settings, "scc_max_edges", 20000), 20000)

        if compute_scc:
            edge_count_row = s.exec(
                select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
            ).one()
            if isinstance(edge_count_row, (tuple, list)):
                edge_count_val = edge_count_row[0] if edge_count_row else 0
            else:
                try:
                    edge_count_val = edge_count_row[0]
                except Exception:
                    edge_count_val = edge_count_row
            edge_count_int = _as_int(edge_count_val, 0)

            node_count_int = len(node_rows)
            if node_count_int <= max_nodes and edge_count_int <= max_edges:
                edge_rows = s.exec(
                    select(FileEdge.src_path, FileEdge.dst_path).where(FileEdge.project_id == project_id)
                ).all()
                g = nx.DiGraph()
                for _nid, path in node_rows:
                    if isinstance(path, str) and path:
                        g.add_node(path)
                for src, dst in edge_rows:
                    if isinstance(src, str) and src and isinstance(dst, str) and dst:
                        g.add_edge(src, dst)

                sccs = list(nx.strongly_connected_components(g))
                for i, comp in enumerate(sccs):
                    for p in comp:
                        scc_map[p] = i
            else:
                scc_map = {}

        params: list[dict] = []
        for nid, path in node_rows:
            if nid is None:
                continue
            p = path if isinstance(path, str) else ""
            if not p:
                continue
            params.append({
                "id": int(nid),
                "fan_in": _as_int(indeg.get(p, 0), 0),
                "fan_out": _as_int(outdeg.get(p, 0), 0),
                "scc_id": _as_int(scc_map.get(p, -1), -1),
            })

        if params:
            s.execute(
                text("UPDATE filenode SET fan_in=:fan_in, fan_out=:fan_out, scc_id=:scc_id WHERE id=:id"),
                params,
            )
            s.commit()

def graph_payload(project_id: int, limit_nodes: int | None = None) -> dict:

    AUTO_LIMIT = 8000
    AUTO_RETURN = 2000

    with get_session() as s:
        total_nodes_row = s.exec(
            select(func.count()).select_from(FileNode).where(FileNode.project_id == project_id)
        ).one()
        if isinstance(total_nodes_row, (tuple, list)):
            total_nodes = _as_int(total_nodes_row[0] if total_nodes_row else 0, 0)
        else:
            try:
                total_nodes = _as_int(total_nodes_row[0], 0)  # type: ignore[index]
            except Exception:
                total_nodes = _as_int(total_nodes_row, 0)

        total_edges_row = s.exec(
            select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
        ).one()
        if isinstance(total_edges_row, (tuple, list)):
            total_edges = _as_int(total_edges_row[0] if total_edges_row else 0, 0)
        else:
            try:
                total_edges = _as_int(total_edges_row[0], 0)  # type: ignore[index]
            except Exception:
                total_edges = _as_int(total_edges_row, 0)

        truncated = False
        effective_limit = limit_nodes
        if effective_limit is None and total_nodes > AUTO_LIMIT:
            effective_limit = AUTO_RETURN
            truncated = True

        if effective_limit is not None and effective_limit <= 0:
            effective_limit = None

        def risk_value(n: FileNode) -> float:
            complexity = _as_float(getattr(n, "complexity", 0), 0.0)
            fan_in = _as_float(getattr(n, "fan_in", 0), 0.0)
            fan_out = _as_float(getattr(n, "fan_out", 0), 0.0)
            return (0.3 * complexity) + (0.7 * fan_in) + (0.1 * fan_out)

        risk_expr = (0.3 * FileNode.complexity) + (0.7 * FileNode.fan_in) + (0.1 * FileNode.fan_out)

        if effective_limit is None:
            nodes = s.exec(select(FileNode).where(FileNode.project_id == project_id)).all()
        else:
            nodes = s.exec(
                select(FileNode)
                .where(FileNode.project_id == project_id)
                .order_by(risk_expr.desc(), FileNode.path.asc())
                .limit(int(effective_limit))
            ).all()

        node_payload: list[dict] = []
        node_paths: list[str] = []
        for n in nodes:
            path = n.path if isinstance(n.path, str) else ""
            if not path:
                continue
            node_paths.append(path)
            label = path.rsplit("/", 1)[-1]
            node_payload.append({
                "id": path,
                "label": label,
                "path": path,
                "language": n.language,
                "loc": _as_int(getattr(n, "loc", 0), 0),
                "complexity": _as_float(getattr(n, "complexity", 0), 0.0),
                "fan_in": _as_int(getattr(n, "fan_in", 0), 0),
                "fan_out": _as_int(getattr(n, "fan_out", 0), 0),
                "scc_id": _as_int(getattr(n, "scc_id", -1), -1),
                "status": n.status,
                "risk": risk_value(n),
            })

        node_set = set(node_paths)

        if effective_limit is None:
            edges = s.exec(select(FileEdge).where(FileEdge.project_id == project_id)).all()
        else:
            if not node_set:
                edges = []
            else:
                edges = s.exec(
                    select(FileEdge)
                    .where(
                        FileEdge.project_id == project_id,
                        FileEdge.src_path.in_(node_paths),
                        FileEdge.dst_path.in_(node_paths),
                    )
                ).all()

    edge_payload: list[dict] = []
    for e in edges:
        if not (isinstance(e.src_path, str) and e.src_path and isinstance(e.dst_path, str) and e.dst_path):
            continue
        if effective_limit is not None:
            if e.src_path not in node_set or e.dst_path not in node_set:
                continue
        edge_payload.append({"source": e.src_path, "target": e.dst_path, "kind": e.kind})
    edge_payload.sort(key=lambda x: (x["source"], x["target"], x.get("kind") or ""))

    meta = {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "returned_nodes": len(node_payload),
        "returned_edges": len(edge_payload),
        "truncated": bool(truncated),
        "limit_nodes": (effective_limit if effective_limit is not None else 0),
        "auto_limit_threshold": AUTO_LIMIT,
    }

    return {"nodes": node_payload, "edges": edge_payload, "meta": meta}