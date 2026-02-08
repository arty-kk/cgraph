import sys
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import policy  # noqa: E402
from app.models import Organization  # noqa: E402


class _FakeDialect:
    name = "sqlite"


class _FakeBind:
    dialect = _FakeDialect()


class _FakeResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values

    def first(self) -> Any | None:
        if not self._values:
            return None
        return self._values[0]


class _FakeBegin:
    def __enter__(self) -> "_FakeBegin":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSession:
    def __init__(self) -> None:
        self.advisory_called = False
        self.select_calls = 0
        self.added: Organization | None = None

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def begin(self) -> _FakeBegin:
        return _FakeBegin()

    def get_bind(self) -> _FakeBind:
        return _FakeBind()

    def exec(self, statement, params=None) -> _FakeResult:
        sql_text = str(statement)
        if "pg_advisory_xact_lock" in sql_text:
            self.advisory_called = True
            return _FakeResult([])
        if "organization.id" in sql_text:
            self.select_calls += 1
            return _FakeResult([])
        return _FakeResult([])

    def add(self, obj: Organization) -> None:
        self.added = obj

    def flush(self) -> None:
        if self.added is not None and self.added.id is None:
            self.added.id = 1


class TestResolveOrgUnauthSqlite(unittest.TestCase):
    def _request(self) -> Request:
        scope = {"type": "http", "headers": []}
        return Request(scope)

    def test_creates_org_without_advisory_lock(self) -> None:
        session = _FakeSession()

        def _get_session() -> _FakeSession:
            return session

        with mock.patch("app.policy.get_session", _get_session):
            org_id = policy._resolve_org_id_unauth(self._request())

        self.assertEqual(org_id, 1)
        self.assertFalse(session.advisory_called)
        self.assertEqual(session.select_calls, 2)
        self.assertIsInstance(session.added, Organization)


if __name__ == "__main__":
    unittest.main()
