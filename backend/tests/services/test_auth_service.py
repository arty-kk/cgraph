import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from sqlalchemy.exc import IntegrityError  # noqa: E402


class TestAuthServiceAsync(unittest.IsolatedAsyncioTestCase):
    async def test_authenticate_user_async_rejects_invalid_password(self) -> None:
        from app.errors import UnauthorizedError  # noqa: E402
        from app.services.auth_service import authenticate_user_async  # noqa: E402

        class _FakeResult:
            def __init__(self, user):
                self._user = user

            def scalars(self):
                return self

            def first(self):
                return self._user

        class _FakeSession:
            async def execute(self, _query):
                user = type("User", (), {"is_active": True, "password_hash": "stored"})()
                return _FakeResult(user)

        with patch("app.services.auth_service._verify_password_async", AsyncMock(return_value=False)):
            with self.assertRaises(UnauthorizedError):
                await authenticate_user_async(_FakeSession(), "user@example.com", "wrong")

    async def test_register_user_async_rolls_back_on_integrity_error(self) -> None:
        from app.errors import BadRequestError  # noqa: E402
        from app.services.auth_service import register_user_async  # noqa: E402

        class _FakeSession:
            def __init__(self):
                self.rollback_called = False

            def add(self, _obj):
                return None

            async def flush(self):
                raise IntegrityError("INSERT", {}, Exception("duplicate"))

            async def commit(self):
                return None

            async def rollback(self):
                self.rollback_called = True

            async def refresh(self, _obj):
                return None

        fake = _FakeSession()

        with patch("app.services.auth_service.settings.auth_allow_public_signup", True):
            with self.assertRaises(BadRequestError):
                await register_user_async(fake, "duplicate@example.com", "password-123")

        self.assertTrue(fake.rollback_called)


if __name__ == "__main__":
    unittest.main()
