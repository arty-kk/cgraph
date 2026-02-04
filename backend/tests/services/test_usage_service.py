import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlmodel import select  # noqa: E402


class TestUsageService(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from app.db import get_session  # noqa: E402
            from app.errors import LimitExceededError  # noqa: E402
            from app.services.usage_service import check_and_increment  # noqa: E402
        except ModuleNotFoundError:
            raise unittest.SkipTest("Postgres dependencies are not available for usage tests")
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            raise unittest.SkipTest("Postgres is not available for usage tests")
        cls.get_session = get_session
        cls.check_and_increment = check_and_increment
        cls.LimitExceededError = LimitExceededError

    def test_daily_limit_enforced(self) -> None:
        org_id = 9999
        kind = "embedding_queries"
        self.check_and_increment(org_id, kind, 1, 2)
        self.check_and_increment(org_id, kind, 1, 2)
        with self.assertRaises(self.LimitExceededError):
            self.check_and_increment(org_id, kind, 1, 2)


if __name__ == "__main__":
    unittest.main()
