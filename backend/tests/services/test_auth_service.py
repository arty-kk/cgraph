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

    async def test_get_user_from_token_async_rejects_inactive_user(self) -> None:
        from app.errors import UnauthorizedError  # noqa: E402
        from app.services.auth_service import get_user_from_token_async  # noqa: E402

        class _FakeSession:
            async def get(self, _model, _user_id):
                return type("User", (), {"is_active": False})()

        fake_session = _FakeSession()

        for flow in ("session", "api_key"):
            with self.subTest(flow=flow):
                user_session = type("UserSession", (), {"user_id": 1})() if flow == "session" else None
                api_key = type("ApiKey", (), {"user_id": 1})() if flow == "api_key" else None

                with patch(
                    "app.services.auth_service._get_valid_session_async",
                    AsyncMock(return_value=user_session),
                ), patch(
                    "app.services.auth_service._get_valid_api_key_async",
                    AsyncMock(return_value=api_key),
                ):
                    with self.assertRaisesRegex(UnauthorizedError, "Неверный токен"):
                        await get_user_from_token_async(fake_session, "valid-token")

    async def test_create_api_key_async_uses_unique_payload_prefix(self) -> None:
        from app.services.auth_service import (  # noqa: E402
            API_KEY_TOKEN_PREFIX_LENGTH,
            create_api_key_async,
        )

        class _FakeSession:
            def __init__(self):
                self._next_id = 1

            def add(self, obj):
                if hasattr(obj, "id"):
                    obj.id = self._next_id
                    self._next_id += 1

            async def commit(self):
                return None

            async def refresh(self, _obj):
                return None

        fake_session = _FakeSession()

        with patch(
            "app.services.auth_service._generate_token",
            side_effect=[
                ("api_abcdefgh12345678", "hash-1"),
                ("api_hgfedcba87654321", "hash-2"),
            ],
        ):
            token1, key1 = await create_api_key_async(fake_session, user_id=1, name="first")
            token2, key2 = await create_api_key_async(fake_session, user_id=1, name="second")

        self.assertNotEqual(token1, token2)
        self.assertNotEqual(key1.token_prefix, key2.token_prefix)

        for key in (key1, key2):
            self.assertNotEqual(key.token_prefix, "api")
            self.assertEqual(len(key.token_prefix), API_KEY_TOKEN_PREFIX_LENGTH)



if __name__ == "__main__":
    unittest.main()
