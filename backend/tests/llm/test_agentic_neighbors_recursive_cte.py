from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import sys

import pytest
from sqlalchemy import event
from sqlmodel import SQLModel, delete

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal, async_engine
from app.llm.agentic.context import _neighbors_limited_async
from app.models import FileEdge
from tests.services.db_helpers import ensure_async_postgres


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _SessionRecorder:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0
        self.last_query_text = ""
        self.last_params = None

    async def execute(self, query, params=None):
        self.calls += 1
        self.last_query_text = str(query)
        self.last_params = dict(params or {})
        return _Rows(self.rows)


def _legacy_neighbors(
    edges: list[tuple[str, str]],
    start: str,
    *,
    direction: str,
    depth: int,
    limit: int,
) -> list[str]:
    if depth <= 0 or limit <= 0:
        return []
    depth = max(0, min(depth, 6))
    limit = max(1, min(limit, 2000))
    visited: set[str] = {start}
    ordered: list[str] = []
    frontier: list[str] = [start]

    out_map: dict[str, list[str]] = defaultdict(list)
    in_map: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        out_map[src].append(dst)
        in_map[dst].append(src)
    for key in list(out_map):
        out_map[key] = sorted(out_map[key])
    for key in list(in_map):
        in_map[key] = sorted(in_map[key])

    for _ in range(depth):
        if not frontier or len(ordered) >= limit:
            break
        frontier = list(dict.fromkeys(frontier))
        nxt: list[str] = []
        pool: list[str] = []
        for node in frontier:
            pool.extend(in_map[node] if direction == "in" else out_map[node])
        for val in pool:
            if not val or val in visited:
                continue
            visited.add(val)
            ordered.append(val)
            nxt.append(val)
            if len(ordered) >= limit:
                break
        frontier = nxt
    return ordered[:limit]


@pytest.mark.anyio
async def test_neighbors_recursive_cte_single_query_and_clamps() -> None:
    session = _SessionRecorder(rows=[("deps/a.py",), ("deps/b.py",), (None,), ("",)])

    out = await _neighbors_limited_async(
        session,
        1,
        "root.py",
        direction="out",
        depth=99,
        limit=9999,
    )

    assert out == ["deps/a.py", "deps/b.py"]
    assert session.calls == 1
    assert "WITH RECURSIVE" in session.last_query_text
    assert "edge.src_path = walk.node" in session.last_query_text
    assert "edge.dst_path" in session.last_query_text
    assert session.last_params == {
        "project_id": 1,
        "start": "root.py",
        "depth": 6,
        "limit": 2000,
    }


@pytest.mark.anyio
async def test_neighbors_recursive_cte_uses_inbound_columns() -> None:
    session = _SessionRecorder(rows=[])

    await _neighbors_limited_async(
        session,
        7,
        "api.py",
        direction="in",
        depth=2,
        limit=5,
    )

    assert session.calls == 1
    assert "edge.dst_path = walk.node" in session.last_query_text
    assert "SELECT edge.src_path" in session.last_query_text


@pytest.mark.anyio
async def test_neighbors_recursive_cte_matches_legacy_on_postgres_graph(ensure_async_postgres) -> None:
    if async_engine.sync_engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL")

    edges = [
        ("a.py", "b.py"),
        ("a.py", "c.py"),
        ("b.py", "d.py"),
        ("c.py", "d.py"),
        ("d.py", "a.py"),
        ("d.py", "e.py"),
        ("b.py", "e.py"),
    ]

    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await session.execute(delete(FileEdge).where(FileEdge.project_id == 4242))
        for idx, (src, dst) in enumerate(edges):
            session.add(FileEdge(project_id=4242, src_path=src, dst_path=dst, kind=f"k{idx}", raw=""))
        session.add(FileEdge(project_id=4242, src_path="a.py", dst_path="c.py", kind="dup", raw=""))
        await session.commit()

    async with AsyncSessionLocal() as session:
        expected_out = _legacy_neighbors(edges + [("a.py", "c.py")], "a.py", direction="out", depth=3, limit=10)
        expected_in = _legacy_neighbors(edges + [("a.py", "c.py")], "e.py", direction="in", depth=4, limit=3)
        got_out = await _neighbors_limited_async(session, 4242, "a.py", direction="out", depth=3, limit=10)
        got_in = await _neighbors_limited_async(session, 4242, "e.py", direction="in", depth=4, limit=3)

    assert got_out == expected_out
    assert got_in == expected_in


@pytest.mark.anyio
async def test_neighbors_recursive_cte_uses_one_traversal_round_trip(ensure_async_postgres) -> None:
    if async_engine.sync_engine.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL")

    async with AsyncSessionLocal() as session:
        await session.execute(delete(FileEdge).where(FileEdge.project_id == 777))
        session.add(FileEdge(project_id=777, src_path="x.py", dst_path="y.py", kind="import", raw=""))
        session.add(FileEdge(project_id=777, src_path="y.py", dst_path="z.py", kind="import", raw=""))
        await session.commit()

    statements: deque[str] = deque()

    def _before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(async_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        async with AsyncSessionLocal() as session:
            out = await _neighbors_limited_async(session, 777, "x.py", direction="out", depth=6, limit=100)
    finally:
        event.remove(async_engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    assert out == ["y.py", "z.py"]
    traversal = [sql for sql in statements if "WITH RECURSIVE walk" in sql]
    assert len(traversal) == 1
