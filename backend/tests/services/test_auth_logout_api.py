import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.api.auth import router as auth_router  # noqa: E402
from app.errors import install_exception_handlers  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class TestAuthLogoutApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = FastAPI()

        @app.middleware("http")
        async def _inject_test_session(request, call_next):
            request.state.db_session = object()
            return await call_next(request)

        install_exception_handlers(app)
        app.include_router(auth_router, prefix="/api")
        cls.client = TestClient(app)

    @patch("app.api.auth.revoke_session_async", new_callable=AsyncMock)
    @patch("app.api.auth.get_user_from_token_async", new_callable=AsyncMock)
    def test_logout_with_session_bearer_revokes_session(
        self,
        mock_get_user_from_token_async,
        mock_revoke_session_async,
    ) -> None:
        token = "sess_test_token"
        revoked_tokens: set[str] = set()

        async def revoke_side_effect(_session, raw_token: str) -> None:
            revoked_tokens.add(raw_token)

        async def get_user_side_effect(_session, raw_token: str):
            if raw_token in revoked_tokens:
                from app.errors import UnauthorizedError

                raise UnauthorizedError("Неверный токен")
            return SimpleNamespace(id=1, email="user@example.com")

        mock_revoke_session_async.side_effect = revoke_side_effect
        mock_get_user_from_token_async.side_effect = get_user_side_effect

        headers = {"Authorization": f"Bearer {token}"}
        response = self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        mock_revoke_session_async.assert_awaited_once()
        self.assertEqual(mock_revoke_session_async.await_args.args[1], token)

        me_response = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me_response.status_code, 401)
        self.assertEqual(me_response.json()["error"]["code"], "unauthorized")

    @patch("app.api.auth.create_session_async", new_callable=AsyncMock)
    @patch("app.api.auth.authenticate_user_async", new_callable=AsyncMock)
    @patch("app.api.auth.register_user_async", new_callable=AsyncMock)
    @patch("app.api.auth.bootstrap_user_async", new_callable=AsyncMock)
    @patch(
        "app.api.auth.AsyncSessionLocal",
        side_effect=AssertionError(
            "AsyncSessionLocal should not be used in auth endpoints"
        ),
        create=True,
    )
    def test_auth_endpoints_use_request_scoped_session_only(
        self,
        mock_async_session_local,
        mock_bootstrap_user_async,
        mock_register_user_async,
        mock_authenticate_user_async,
        mock_create_session_async,
    ) -> None:
        app = FastAPI()

        db_session = object()

        @app.middleware("http")
        async def _inject_test_session(request, call_next):
            request.state.db_session = db_session
            return await call_next(request)

        install_exception_handlers(app)
        app.include_router(auth_router, prefix="/api")

        user = SimpleNamespace(id=42, email="tester@example.com")
        mock_bootstrap_user_async.return_value = user
        mock_register_user_async.return_value = user
        mock_authenticate_user_async.return_value = user
        mock_create_session_async.return_value = (
            "sess_token",
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        )

        with TestClient(app) as client:
            bootstrap_response = client.post(
                "/api/auth/bootstrap",
                json={"email": "tester@example.com", "password": "secret"},
            )
            self.assertEqual(bootstrap_response.status_code, 200)
            self.assertEqual(
                bootstrap_response.json(),
                {"id": user.id, "email": user.email},
            )

            register_response = client.post(
                "/api/auth/register",
                json={"email": "tester@example.com", "password": "secret"},
            )
            self.assertEqual(register_response.status_code, 200)
            self.assertEqual(
                register_response.json(),
                {"id": user.id, "email": user.email},
            )

            login_response = client.post(
                "/api/auth/login",
                json={"email": "tester@example.com", "password": "secret"},
            )
            self.assertEqual(login_response.status_code, 200)
            self.assertEqual(login_response.json()["token"], "sess_token")
            self.assertIn("expires_at", login_response.json())

        mock_bootstrap_user_async.assert_awaited_once_with(
            db_session,
            "tester@example.com",
            "secret",
        )
        mock_register_user_async.assert_awaited_once_with(
            db_session,
            "tester@example.com",
            "secret",
        )
        mock_authenticate_user_async.assert_awaited_once_with(
            db_session,
            "tester@example.com",
            "secret",
        )
        mock_create_session_async.assert_awaited_once_with(db_session, user.id)
        mock_async_session_local.assert_not_called()

    @patch("app.api.auth.revoke_session_async", new_callable=AsyncMock)
    def test_logout_with_api_key_returns_error(self, mock_revoke_session_async) -> None:
        headers = {"X-API-Key": "api_test_token"}

        response = self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertNotEqual(payload.get("ok"), True)
        self.assertIn("API-ключи", payload["error"]["message"])
        mock_revoke_session_async.assert_not_called()


if __name__ == "__main__":
    unittest.main()
