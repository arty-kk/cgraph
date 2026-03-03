from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def neighbors_limited_recursive_cte_async(
    session: AsyncSession,
    project_id: int,
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
    from_col = "dst_path" if direction == "in" else "src_path"
    to_col = "src_path" if direction == "in" else "dst_path"

    query = text(
        f"""
        WITH RECURSIVE walk(node, depth, path) AS (
            SELECT CAST(:start AS TEXT), 0, ARRAY[CAST(:start AS TEXT)]::TEXT[]
            UNION ALL
            SELECT edge.{to_col}, walk.depth + 1, walk.path || edge.{to_col}
            FROM walk
            JOIN fileedge AS edge
              ON edge.project_id = :project_id
             AND edge.{from_col} = walk.node
            WHERE walk.depth < :depth
              AND NOT (edge.{to_col} = ANY(walk.path))
        ),
        ranked AS (
            SELECT
                node,
                depth,
                ARRAY_TO_STRING(path, E'\\x1F') AS path_sort,
                ROW_NUMBER() OVER (
                    PARTITION BY node
                    ORDER BY depth ASC, ARRAY_TO_STRING(path, E'\\x1F') ASC
                ) AS rn
            FROM walk
            WHERE depth > 0
              AND node <> :start
        )
        SELECT node
        FROM ranked
        WHERE rn = 1
        ORDER BY depth ASC, path_sort ASC, node ASC
        LIMIT :limit
        """
    )
    rows = (
        await session.execute(
            query,
            {
                "project_id": project_id,
                "start": start,
                "depth": depth,
                "limit": limit,
            },
        )
    ).all()
    out: list[str] = []
    for row in rows:
        val = row[0] if isinstance(row, (tuple, list)) else row
        if isinstance(val, str) and val:
            out.append(val)
    return out[:limit]
