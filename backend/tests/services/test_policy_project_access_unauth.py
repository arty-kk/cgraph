import sys
from pathlib import Path

import pytest
from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import policy
from app.errors import ForbiddenError


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def all(self):
        return []

    def first(self):
        return self._value


class _FakeSession:
    bind = None

    async def execute(self, statement):
        _ = statement
        return _FakeResult(None)


@pytest.mark.anyio
async def test_forbids_access_to_project_from_other_org(monkeypatch):
    scope = {
        "type": "http",
        "headers": [(b"x-org-id", b"1")],
        "state": {"db_session": _FakeSession()},
    }
    request = Request(scope)

    async def _resolve_org_id_unauth_async(_request: Request) -> int:
        return 1

    monkeypatch.setattr(policy, "_resolve_org_id_unauth_async", _resolve_org_id_unauth_async)
    monkeypatch.setattr(policy.settings, "auth_enabled", False)

    with pytest.raises(ForbiddenError, match="Нет доступа к проекту"):
        await policy.require_project_access_async(request, 123)
