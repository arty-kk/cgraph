import sys
import unittest
from pathlib import Path

from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.auth import extract_token  # noqa: E402


class TestAuthUtils(unittest.TestCase):
    def _request(self, headers: dict[str, str]) -> Request:
        scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
        return Request(scope)

    def test_extract_bearer_token(self) -> None:
        req = self._request({"Authorization": "Bearer token123"})
        self.assertEqual(extract_token(req), "token123")

    def test_extract_api_key(self) -> None:
        req = self._request({"X-API-Key": "abc"})
        self.assertEqual(extract_token(req), "abc")

    def test_extract_missing(self) -> None:
        req = self._request({})
        self.assertIsNone(extract_token(req))


if __name__ == "__main__":
    unittest.main()
