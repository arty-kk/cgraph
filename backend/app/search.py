#backend/app/search.py
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text as sa_text

from .db import get_session

_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _fts_query_from_substring(q: str, *, max_tokens: int = 12) -> str | None:
    tokens = [t for t in _FTS_TOKEN_RE.findall(q or "") if t]
    if not tokens:
        return None
    tokens = tokens[: max(1, int(max_tokens))]
    esc = []
    for t in tokens:
        esc.append(t.replace("'", "''"))
    return " & ".join([f"{t}:*" for t in esc if t])


def search_text_paths(
    project_id: int,
    query: str,
    *,
    limit: int,
    prefix: str | None = None,
) -> list[str]:
    fts_query = _fts_query_from_substring(query)
    if not fts_query:
        return []

    sql = """
        SELECT path
        FROM filetext
        WHERE project_id = :pid
          AND search @@ to_tsquery('simple', :q)
    """
    params: dict[str, Any] = {"pid": int(project_id), "q": fts_query, "lim": int(limit)}

    if prefix:
        params["prefix"] = prefix
        params["like"] = f"{prefix}/%"
        sql += " AND (path = :prefix OR path LIKE :like)"

    sql += " ORDER BY ts_rank_cd(search, to_tsquery('simple', :q)) DESC LIMIT :lim"

    with get_session() as s:
        rows = s.execute(sa_text(sql), params).all()

    paths: list[str] = []
    for row in rows:
        p = row[0] if isinstance(row, (tuple, list)) else row
        if isinstance(p, str) and p:
            paths.append(p)
    return paths
