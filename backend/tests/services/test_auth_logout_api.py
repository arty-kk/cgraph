import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.auth import router as auth_router  # noqa: E402
from app.errors import install_exception_handlers  # noqa: E402


class TestAuthLogoutApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app = FastAPI()
        install_exception_handlers(app)
        app.include_router(auth_router, prefix="/api")
        cls.client = TestClient(app)

    @patch("app.api.auth.revoke_session")
    @patch("app.api.auth.get_user_from_token")
    def test_logout_with_session_bearer_revokes_session(
        self,
        mock_get_user_from_token,
        mock_revoke_session,
    ) -> None:
        token = "sess_test_token"
        revoked_tokens: set[str] = set()

        def revoke_side_effect(raw_token: str) -> None:
            revoked_tokens.add(raw_token)

        def get_user_side_effect(raw_token: str):
            if raw_token in revoked_tokens:
                from app.errors import UnauthorizedError

                raise UnauthorizedError("Неверный токен")
            return SimpleNamespace(id=1, email="user@example.com")

        mock_revoke_session.side_effect = revoke_side_effect
        mock_get_user_from_token.side_effect = get_user_side_effect

        headers = {"Authorization": f"Bearer {token}"}
        response = self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        mock_revoke_session.assert_called_once_with(token)

        me_response = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me_response.status_code, 401)
        self.assertEqual(me_response.json()["error"]["code"], "unauthorized")

    @patch("app.api.auth.revoke_session")
    def test_logout_with_api_key_returns_error(self, mock_revoke_session) -> None:
        headers = {"X-API-Key": "api_test_token"}

        response = self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertNotEqual(payload.get("ok"), True)
        self.assertIn("API-ключи", payload["error"]["message"])
        mock_revoke_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
