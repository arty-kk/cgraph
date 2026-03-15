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


class TestAuthApiKeysApi(unittest.TestCase):
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

    @patch("app.api.auth.create_api_key_async", new_callable=AsyncMock)
    @patch("app.api.auth.get_user_from_token_async", new_callable=AsyncMock)
    def test_create_key_rejects_x_api_key_only(
        self,
        mock_get_user_from_token_async,
        mock_create_api_key_async,
    ) -> None:
        response = self.client.post(
            "/api/auth/api-keys",
            headers={"X-API-Key": "api_test_token"},
            json={"name": "cli"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("API-ключи", payload["error"]["message"])
        mock_get_user_from_token_async.assert_not_called()
        mock_create_api_key_async.assert_not_called()

    @patch("app.api.auth.list_api_keys_async", new_callable=AsyncMock)
    @patch("app.api.auth.get_user_from_token_async", new_callable=AsyncMock)
    def test_list_keys_rejects_x_api_key_only(
        self,
        mock_get_user_from_token_async,
        mock_list_api_keys_async,
    ) -> None:
        response = self.client.get(
            "/api/auth/api-keys",
            headers={"X-API-Key": "api_test_token"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("API-ключи", payload["error"]["message"])
        mock_get_user_from_token_async.assert_not_called()
        mock_list_api_keys_async.assert_not_called()

    @patch("app.api.auth.revoke_api_key_async", new_callable=AsyncMock)
    @patch("app.api.auth.get_user_from_token_async", new_callable=AsyncMock)
    def test_delete_key_rejects_x_api_key_only(
        self,
        mock_get_user_from_token_async,
        mock_revoke_api_key_async,
    ) -> None:
        response = self.client.delete(
            "/api/auth/api-keys/7",
            headers={"X-API-Key": "api_test_token"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("API-ключи", payload["error"]["message"])
        mock_get_user_from_token_async.assert_not_called()
        mock_revoke_api_key_async.assert_not_called()

    @patch("app.api.auth.create_api_key_async", new_callable=AsyncMock)
    @patch("app.api.auth.get_user_from_token_async", new_callable=AsyncMock)
    def test_create_key_with_bearer_calls_service_layer(
        self,
        mock_get_user_from_token_async,
        mock_create_api_key_async,
    ) -> None:
        user = SimpleNamespace(id=17, email="user@example.com")
        key = SimpleNamespace(
            id=10,
            name="cli",
            created_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            expires_at=None,
        )
        mock_get_user_from_token_async.return_value = user
        mock_create_api_key_async.return_value = ("raw_key", key)

        response = self.client.post(
            "/api/auth/api-keys",
            headers={"Authorization": "Bearer sess_test_token"},
            json={"name": "cli"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token"], "raw_key")
        mock_get_user_from_token_async.assert_awaited_once()
        mock_create_api_key_async.assert_awaited_once()

    @patch("app.api.auth.list_api_keys_async", new_callable=AsyncMock)
    @patch("app.api.auth.get_user_from_token_async", new_callable=AsyncMock)
    def test_list_keys_with_bearer_calls_service_layer(
        self,
        mock_get_user_from_token_async,
        mock_list_api_keys_async,
    ) -> None:
        user = SimpleNamespace(id=17, email="user@example.com")
        key = SimpleNamespace(
            id=11,
            name="cli",
            created_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            expires_at=None,
            revoked_at=None,
        )
        mock_get_user_from_token_async.return_value = user
        mock_list_api_keys_async.return_value = [key]

        response = self.client.get(
            "/api/auth/api-keys",
            headers={"Authorization": "Bearer sess_test_token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        mock_get_user_from_token_async.assert_awaited_once()
        mock_list_api_keys_async.assert_awaited_once()

    @patch("app.api.auth.revoke_api_key_async", new_callable=AsyncMock)
    @patch("app.api.auth.get_user_from_token_async", new_callable=AsyncMock)
    def test_delete_key_with_bearer_calls_service_layer(
        self,
        mock_get_user_from_token_async,
        mock_revoke_api_key_async,
    ) -> None:
        user = SimpleNamespace(id=17, email="user@example.com")
        mock_get_user_from_token_async.return_value = user

        response = self.client.delete(
            "/api/auth/api-keys/7",
            headers={"Authorization": "Bearer sess_test_token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        mock_get_user_from_token_async.assert_awaited_once()
        mock_revoke_api_key_async.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
