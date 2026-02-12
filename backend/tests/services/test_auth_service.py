import sys
import base64
import hashlib
import unittest
from pathlib import Path
from threading import Barrier, Lock, Thread
from time import time
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy.exc import IntegrityError, SQLAlchemyError  # noqa: E402
from sqlmodel import select  # noqa: E402


class TestAuthServiceBootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from app.db import get_session  # noqa: E402
            from app.errors import BadRequestError  # noqa: E402
            from app.models import BootstrapSentinel, User  # noqa: E402
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
        cls.BootstrapSentinel = BootstrapSentinel
        cls.User = User
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

        with self.get_session() as session:
            users = session.exec(select(self.User)).all()
            for user in users:
                session.delete(user)
            session.commit()

        with self.assertRaises(self.BadRequestError):
            self.bootstrap_user(f"retry_{suffix}@example.com", password)

        with self.get_session() as session:
            sentinel = session.exec(
                select(self.BootstrapSentinel).where(self.BootstrapSentinel.key == "bootstrap")
            ).first()
        self.assertIsNotNone(sentinel)


class TestAuthServiceAuthenticate(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.config import settings  # noqa: E402
        from app.errors import UnauthorizedError  # noqa: E402
        from app.services.auth_service import authenticate_user  # noqa: E402

        cls.settings = settings
        cls.UnauthorizedError = UnauthorizedError
        cls.authenticate_user = staticmethod(authenticate_user)

    def _mocked_authenticate(self, password_hash: str, password: str = "password-123"):
        from types import SimpleNamespace
        from unittest.mock import patch

        user = SimpleNamespace(email="user@example.com", password_hash=password_hash, is_active=True)

        class _FakeResult:
            def first(self):
                return user

        class _FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def exec(self, _query):
                return _FakeResult()

        with patch("app.services.auth_service.get_session", return_value=_FakeSession()):
            return self.authenticate_user("user@example.com", password)

    def test_authenticate_user_rejects_non_numeric_iterations(self) -> None:
        with self.assertRaises(self.UnauthorizedError):
            self._mocked_authenticate("pbkdf2_sha256$abc$YQ==$Yg==")

    def test_authenticate_user_rejects_invalid_base64_salt(self) -> None:
        with self.assertRaises(self.UnauthorizedError):
            self._mocked_authenticate("pbkdf2_sha256$200000$###$Yg==")

    def test_authenticate_user_rejects_invalid_base64_hash(self) -> None:
        with self.assertRaises(self.UnauthorizedError):
            self._mocked_authenticate("pbkdf2_sha256$200000$YQ==$###")

    def test_authenticate_user_accepts_valid_hash_with_custom_iterations(self) -> None:
        password = "password-123"
        iterations = 175000
        salt = b"custom-salt-1234"
        pepper = self.settings.auth_password_pepper.encode("utf-8")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8") + pepper, salt, iterations)
        password_hash = "pbkdf2_sha256$%d$%s$%s" % (
            iterations,
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(dk).decode("ascii"),
        )

        user = self._mocked_authenticate(password_hash, password=password)

        self.assertEqual(user.email, "user@example.com")


class TestAuthServiceRegister(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.errors import BadRequestError  # noqa: E402
        from app.services.auth_service import register_user  # noqa: E402

        cls.BadRequestError = BadRequestError
        cls.register_user = staticmethod(register_user)

    def test_register_user_integrity_error_rolls_back_and_raises_bad_request(self) -> None:
        class _FakeResult:
            def first(self):
                return None

        class _FakeSession:
            def __init__(self):
                self.rollback_called = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def exec(self, _query):
                return _FakeResult()

            def add(self, _obj):
                return None

            def flush(self):
                return None

            def commit(self):
                raise IntegrityError("INSERT", {}, Exception("duplicate key value"))

            def rollback(self):
                self.rollback_called = True

            def refresh(self, _obj):
                return None

        fake_session = _FakeSession()

        with patch("app.services.auth_service.get_session", return_value=fake_session):
            with patch("app.services.auth_service.settings.auth_allow_public_signup", True):
                with self.assertRaises(self.BadRequestError):
                    self.register_user("duplicate@example.com", "password-123")

        self.assertTrue(fake_session.rollback_called)

    def test_register_user_flush_integrity_error_rolls_back_and_raises_bad_request(self) -> None:
        class _FakeResult:
            def first(self):
                return None

        class _FakeSession:
            def __init__(self):
                self.rollback_called = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def exec(self, _query):
                return _FakeResult()

            def add(self, _obj):
                return None

            def flush(self):
                raise IntegrityError("INSERT", {}, Exception("duplicate key value"))

            def commit(self):
                return None

            def rollback(self):
                self.rollback_called = True

            def refresh(self, _obj):
                return None

        fake_session = _FakeSession()

        with patch("app.services.auth_service.get_session", return_value=fake_session):
            with patch("app.services.auth_service.settings.auth_allow_public_signup", True):
                with self.assertRaises(self.BadRequestError):
                    self.register_user("duplicate@example.com", "password-123")

        self.assertTrue(fake_session.rollback_called)


if __name__ == "__main__":
    unittest.main()
