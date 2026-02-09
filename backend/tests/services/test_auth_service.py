import sys
import unittest
from pathlib import Path
from threading import Barrier, Lock, Thread
from time import time

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlmodel import select  # noqa: E402


class TestAuthServiceBootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from app.db import get_session  # noqa: E402
            from app.errors import BadRequestError  # noqa: E402
            from app.models import User  # noqa: E402
            from app.services.auth_service import bootstrap_user  # noqa: E402
        except ModuleNotFoundError:
            raise unittest.SkipTest("Postgres dependencies missing for auth service tests")
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            raise unittest.SkipTest("Postgres is not available for auth service tests")
        with get_session() as session:
            if session.exec(select(User).limit(1)).first():
                raise unittest.SkipTest("Users already exist for auth service tests")
        cls.get_session = get_session
        cls.BadRequestError = BadRequestError
        cls.bootstrap_user = bootstrap_user

    def test_concurrent_bootstrap_user(self) -> None:
        barrier = Barrier(2)
        results: list[str] = []
        lock = Lock()
        suffix = int(time() * 1000000)
        email = f"bootstrap_{suffix}@example.com"
        password = "strong-password"

        def worker() -> None:
            try:
                barrier.wait()
                self.bootstrap_user(email, password)
                outcome = "ok"
            except self.BadRequestError:
                outcome = "bad_request"
            with lock:
                results.append(outcome)

        threads = [Thread(target=worker), Thread(target=worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("bad_request"), 1)


if __name__ == "__main__":
    unittest.main()
