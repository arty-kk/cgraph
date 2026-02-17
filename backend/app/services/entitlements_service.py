"""Entitlement helpers for org-level gating (runtime async-only)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..models import OrgEntitlement


async def _entitlement_rows_async(session: AsyncSession, org_id: int) -> list[OrgEntitlement]:
    return list(
        (
            await session.execute(
                select(OrgEntitlement).where(OrgEntitlement.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )


async def get_entitlement_bool_async(session: AsyncSession, org_id: int, key: str) -> bool | None:
    rows = await _entitlement_rows_async(session, org_id)
    for row in rows:
        if row.key == key:
            return row.value_bool
    return None


async def get_entitlement_int_async(session: AsyncSession, org_id: int, key: str) -> int | None:
    rows = await _entitlement_rows_async(session, org_id)
    for row in rows:
        if row.key == key:
            return row.value_int
    return None
