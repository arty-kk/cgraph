import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import policy
from app.models import Organization


class _FakeDialect:
    name = "sqlite"


class _FakeBind:
    dialect = _FakeDialect()


class _FakeResult:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def scalars(self):
        return self

    def all(self) -> list[Any]:
        return self._values

    def first(self) -> Any | None:
        return self._values[0] if self._values else None


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.bind = _FakeBind()
        self.advisory_called = False
        self.select_calls = 0
        self.added: Organization | None = None

    async def get(self, model, org_id: int):
        _ = model
        _ = org_id
        return None

    async def execute(self, statement, params=None):
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

    async def flush(self) -> None:
        if self.added is not None and self.added.id is None:
            self.added.id = 1

    async def rollback(self) -> None:
        return None


class _FakeAsyncSessionIntegrity:
    def __init__(self) -> None:
        self.bind = _FakeBind()
        self.advisory_called = False
        self.select_calls = 0
        self.added: list[Organization] = []
        self.persisted = [
            Organization(
                id=7,
                name="Personal",
                slug="personal",
                created_at=datetime.now(timezone.utc),
            )
        ]
        self.flush_calls = 0
        self.rollback_calls = 0

    async def get(self, model, org_id: int):
        _ = model
        _ = org_id
        return None

    async def execute(self, statement, params=None):
        sql_text = str(statement)
        if "pg_advisory_xact_lock" in sql_text:
            self.advisory_called = True
            return _FakeResult([])
        if "organization.slug" in sql_text:
            return _FakeResult(self.persisted)
        if "organization.id" in sql_text:
            self.select_calls += 1
            return _FakeResult([])
        return _FakeResult([])

    def add(self, obj: Organization) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_calls += 1
        raise policy.IntegrityError("INSERT", {}, Exception("conflict"))

    async def rollback(self) -> None:
        self.rollback_calls += 1
        self.added = []


@pytest.mark.anyio
async def test_creates_org_without_advisory_lock():
    session = _FakeAsyncSession()
    request = Request({"type": "http", "headers": [], "state": {"db_session": session}})

    org_id = await policy._resolve_org_id_unauth_async(request)

    assert org_id == 1
    assert not session.advisory_called
    assert session.select_calls == 2
    assert isinstance(session.added, Organization)
    assert session.added.slug == "personal"


@pytest.mark.anyio
async def test_reuses_personal_on_slug_conflict():
    session = _FakeAsyncSessionIntegrity()
    request = Request({"type": "http", "headers": [], "state": {"db_session": session}})

    org_id = await policy._resolve_org_id_unauth_async(request)

    assert org_id == session.persisted[0].id
    assert len(session.persisted) == 1
    assert session.flush_calls == 1
    assert session.rollback_calls == 1
