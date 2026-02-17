import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Lock, Thread
from time import time

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlmodel import select  # noqa: E402


class TestUsageService(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from app.db import get_session  # noqa: E402
            from app.errors import LimitExceededError  # noqa: E402
            from app.models import OrgUsage  # noqa: E402
            from app.async_db import AsyncSessionLocal  # noqa: E402
            from app.services.usage_service import check_and_increment_async  # noqa: E402
        except ModuleNotFoundError:
            raise unittest.SkipTest("Postgres dependencies are not available for usage tests")
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            raise unittest.SkipTest("Postgres is not available for usage tests")
        cls.get_session = get_session
        cls.AsyncSessionLocal = AsyncSessionLocal
        cls.check_and_increment_async = check_and_increment_async
        cls.LimitExceededError = LimitExceededError
        cls.OrgUsage = OrgUsage

    def test_daily_limit_enforced(self) -> None:
        org_id = 9999
        kind = "embedding_queries"
        import asyncio

        async def _run() -> None:
            async with self.AsyncSessionLocal() as session:
                await self.check_and_increment_async(session, org_id, kind, 1, 2)
            async with self.AsyncSessionLocal() as session:
                await self.check_and_increment_async(session, org_id, kind, 1, 2)
            async with self.AsyncSessionLocal() as session:
                with self.assertRaises(self.LimitExceededError):
                    await self.check_and_increment_async(session, org_id, kind, 1, 2)

        asyncio.run(_run())

    def test_concurrent_increment_respects_limit(self) -> None:
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
                    async with self.AsyncSessionLocal() as session:
                        await self.check_and_increment_async(session, org_id, kind, 1, limit)

                asyncio.run(_run())
                outcome = "ok"
            except self.LimitExceededError:
                outcome = "limit"
            with lock:
                results.append(outcome)

        threads = [Thread(target=worker), Thread(target=worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("limit"), 1)
        day = datetime.now(timezone.utc).date()
        with self.get_session() as session:
            row = session.exec(
                select(self.OrgUsage).where(
                    self.OrgUsage.org_id == org_id,
                    self.OrgUsage.day == day,
                    self.OrgUsage.kind == kind,
                )
            ).one()
            self.assertEqual(int(row.count), 1)


if __name__ == "__main__":
    unittest.main()
