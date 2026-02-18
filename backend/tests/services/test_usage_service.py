import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Lock, Thread
from time import time

import pytest
from sqlmodel import select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal
from app.errors import LimitExceededError
from app.models import OrgUsage
from app.services.usage_service import check_and_increment_async
from tests.services.db_helpers import ensure_async_postgres


@pytest.mark.anyio
async def test_daily_limit_enforced(ensure_async_postgres) -> None:
    org_id = 9999
    kind = "embedding_queries"

    async with AsyncSessionLocal() as session:
        await check_and_increment_async(session, org_id, kind, 1, 2)
    async with AsyncSessionLocal() as session:
        await check_and_increment_async(session, org_id, kind, 1, 2)
    async with AsyncSessionLocal() as session:
        with pytest.raises(LimitExceededError):
            await check_and_increment_async(session, org_id, kind, 1, 2)


@pytest.mark.anyio
async def test_concurrent_increment_respects_limit(ensure_async_postgres) -> None:
    org_id = int(time() * 1000000) % 2000000000
    kind = "llm_requests"
    limit = 1
    barrier = Barrier(2)
    results: list[str] = []
    lock = Lock()

    def worker() -> None:
        try:
            barrier.wait()
            import asyncio

            async def _run() -> None:
                async with AsyncSessionLocal() as session:
                    await check_and_increment_async(session, org_id, kind, 1, limit)

            asyncio.run(_run())
            outcome = "ok"
        except LimitExceededError:
            outcome = "limit"
        with lock:
            results.append(outcome)

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count("ok") == 1
    assert results.count("limit") == 1
    day = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as session:
        row = (
            (
                await session.execute(
                    select(OrgUsage).where(
                        OrgUsage.org_id == org_id,
                        OrgUsage.day == day,
                        OrgUsage.kind == kind,
                    )
                )
            )
            .scalars()
            .first()
        )
    assert row is not None
    assert int(row.count) == 1
