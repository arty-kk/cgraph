"""Entitlement helpers for org-level gating."""
from __future__ import annotations

from sqlmodel import select

from ..models import OrgEntitlement
from ..db import get_session


def _entitlement_rows(org_id: int) -> list[OrgEntitlement]:
    with get_session() as session:
        return session.exec(
            select(OrgEntitlement).where(OrgEntitlement.org_id == org_id)
        ).all()


def get_entitlement_bool(org_id: int, key: str) -> bool | None:
    rows = _entitlement_rows(org_id)
    for row in rows:
        if row.key == key:
            return row.value_bool
    return None


def get_entitlement_int(org_id: int, key: str) -> int | None:
    rows = _entitlement_rows(org_id)
    for row in rows:
        if row.key == key:
            return row.value_int
    return None
