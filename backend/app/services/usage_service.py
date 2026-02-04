"""Org usage metering helpers (daily quotas)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlmodel import select

from ..db import get_session
from ..errors import LimitExceededError
from ..models import OrgUsage

EMBEDDING_CHUNKS_KIND = "embedding_chunks"
EMBEDDING_QUERY_KIND = "embedding_queries"
LLM_REQUESTS_KIND = "llm_requests"


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def check_and_increment(org_id: int, kind: str, amount: int, limit: int | None) -> None:
    if amount <= 0:
        return
    if limit is not None and limit <= 0:
        raise LimitExceededError("Лимит использования исчерпан")
    day = _today_utc()
    with get_session() as session:
        row = session.exec(
            select(OrgUsage).where(
                OrgUsage.org_id == org_id,
                OrgUsage.day == day,
                OrgUsage.kind == kind,
            )
        ).first()
        current = int(row.count) if row else 0
        if limit is not None and current + amount > limit:
            raise LimitExceededError(
                "Превышен дневной лимит использования",
                context={"kind": kind, "limit": limit},
            )
        if row:
            row.count = current + amount
            session.add(row)
        else:
            session.add(
                OrgUsage(
                    org_id=org_id,
                    day=day,
                    kind=kind,
                    count=amount,
                )
            )
        session.commit()
