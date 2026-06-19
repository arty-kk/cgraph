import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import Request
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import main
from app import request_session
from app.errors import UnauthorizedError


async def _noop_async():
    return None


class _Session:
    def __init__(self, counters: dict[str, int]):
        self._counters = counters

    async def rollback(self):
        self._counters["rollback"] += 1


class _SessionCtx:
    def __init__(self, counters: dict[str, int]):
        self._counters = counters
        self._session = _Session(counters)

    async def __aenter__(self):
        self._counters["enter"] += 1
        self._counters["active"] += 1
        self._counters["max_active"] = max(self._counters["max_active"], self._counters["active"])
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        self._counters["exit"] += 1
        self._counters["active"] -= 1
        return False


class _SessionFactory:
    def __init__(self):
        self.counters = {
            "created": 0,
            "enter": 0,
            "exit": 0,
            "rollback": 0,
            "active": 0,
            "max_active": 0,
        }

    def __call__(self):
        self.counters["created"] += 1
        return _SessionCtx(self.counters)


@contextmanager
def _temporary_get(path: str, endpoint):
    routes_before = len(main.app.router.routes)
    main.app.get(path)(endpoint)
    try:
        yield
    finally:
        del main.app.router.routes[routes_before:]


def _patch_runtime(monkeypatch):
    monkeypatch.setattr(main, "build_startup_steps", lambda *, role: [("noop", lambda: _noop_async())])
    monkeypatch.setattr(main, "build_cleanup_steps", lambda *, role: [("noop", lambda: _noop_async())])
    monkeypatch.setattr(main.settings, "rate_limit_enabled", False)
    monkeypatch.setattr(main.settings, "openai_api_key", "")


def test_api_prefixes_do_not_open_session_without_db_access(monkeypatch):
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(main.settings, "auth_enabled", False)
    session_factory = _SessionFactory()
    monkeypatch.setattr(request_session, "AsyncSessionLocal", session_factory)

    async def _probe(request: Request):
        return {"session_attached": hasattr(request.state, "db_session")}

    with _temporary_get("/api/_session_probe", _probe), _temporary_get("/api/v1/_session_probe", _probe):
        with TestClient(main.app) as client:
            assert client.get("/api/_session_probe").status_code == 200
            assert client.get("/api/v1/_session_probe").status_code == 200

    assert session_factory.counters["created"] == 0
    assert session_factory.counters["enter"] == 0
    assert session_factory.counters["exit"] == 0


def test_options_requests_do_not_create_session(monkeypatch):
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(main.settings, "auth_enabled", True)
    session_factory = _SessionFactory()
    monkeypatch.setattr(request_session, "AsyncSessionLocal", session_factory)

    async def _probe(_request: Request):
        return {"ok": True}

    with _temporary_get("/api/_options_probe", _probe):
        with TestClient(main.app) as client:
            response = client.options("/api/_options_probe")

    assert response.status_code == 405
    assert session_factory.counters["created"] == 0


def test_public_auth_route_without_db_access_does_not_create_session(monkeypatch):
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(main.settings, "auth_enabled", True)
    session_factory = _SessionFactory()
    monkeypatch.setattr(request_session, "AsyncSessionLocal", session_factory)

    async def _public_probe(_request: Request):
        return {"ok": True}

    with _temporary_get("/api/auth/_public_probe", _public_probe):
        with TestClient(main.app) as client:
            response = client.get("/api/auth/_public_probe")

    assert response.status_code == 200
    assert session_factory.counters["created"] == 0


def test_session_not_created_when_error_happens_before_auth_lookup(monkeypatch):
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(main.settings, "auth_enabled", True)
    session_factory = _SessionFactory()
    monkeypatch.setattr(request_session, "AsyncSessionLocal", session_factory)

    async def _protected(_request: Request):
        return {"ok": True}

    async def _never_called(_session, _token):
        raise AssertionError("get_user_from_token_async should not be called")

    monkeypatch.setattr(main, "extract_token", lambda _request: (_ for _ in ()).throw(RuntimeError("pre-auth")))
    monkeypatch.setattr(main, "get_user_from_token_async", _never_called)

    with _temporary_get("/api/_pre_auth_failure", _protected):
        with TestClient(main.app, raise_server_exceptions=False) as client:
            response = client.get("/api/_pre_auth_failure")

    assert response.status_code == 500
    assert session_factory.counters["created"] == 0
    assert session_factory.counters["rollback"] == 0
    assert session_factory.counters["exit"] == 0


def test_session_rolls_back_when_error_happens_after_auth(monkeypatch):
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(main.settings, "auth_enabled", True)
    session_factory = _SessionFactory()
    monkeypatch.setattr(request_session, "AsyncSessionLocal", session_factory)

    async def _boom(_request: Request):
        raise RuntimeError("post-auth")

    async def _user_from_token(_session, _token):
        return SimpleNamespace(id=1)

    monkeypatch.setattr(main, "extract_token", lambda _request: "token")
    monkeypatch.setattr(main, "get_user_from_token_async", _user_from_token)

    with _temporary_get("/api/_post_auth_failure", _boom):
        with TestClient(main.app, raise_server_exceptions=False) as client:
            response = client.get("/api/_post_auth_failure", headers={"Authorization": "Bearer token"})

    assert response.status_code == 500
    assert session_factory.counters["rollback"] == 1
    assert session_factory.counters["exit"] == 1


def test_invalid_token_returns_401_envelope_not_500(monkeypatch):
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(main.settings, "auth_enabled", True)
    session_factory = _SessionFactory()
    monkeypatch.setattr(request_session, "AsyncSessionLocal", session_factory)

    reached = {"value": False}

    async def _protected(_request: Request):
        reached["value"] = True
        return {"ok": True}

    async def _raise_unauthorized(_session, _token):
        raise UnauthorizedError("Неверный токен")

    monkeypatch.setattr(main, "get_user_from_token_async", _raise_unauthorized)

    with _temporary_get("/api/_invalid_token_probe", _protected):
        with TestClient(main.app, raise_server_exceptions=False) as client:
            response = client.get(
                "/api/_invalid_token_probe",
                headers={"Authorization": "Bearer bad-token"},
            )

    # The auth boundary must answer with the 401 envelope, not a 500 server error.
    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "Неверный токен"}
    }
    # Request is denied at the edge and never reaches the handler.
    assert reached["value"] is False
    # The session opened for the auth lookup is converted to a response (no
    # propagating exception), so it is closed without a rollback.
    assert session_factory.counters["rollback"] == 0
    assert session_factory.counters["exit"] == session_factory.counters["created"]


def test_concurrent_and_prefixed_auth_requests_use_single_session_per_request(monkeypatch):
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(main.settings, "auth_enabled", True)
    session_factory = _SessionFactory()
    monkeypatch.setattr(request_session, "AsyncSessionLocal", session_factory)

    async def _ok(_request: Request):
        return {"ok": True}

    async def _user_from_token(_session, _token):
        await asyncio.sleep(0.01)
        return SimpleNamespace(id=1)

    monkeypatch.setattr(main, "get_user_from_token_async", _user_from_token)

    async def _run_batch():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            reqs = [client.get("/api/_batch", headers={"Authorization": "Bearer token"}) for _ in range(10)]
            reqs += [client.get("/api/v1/_batch", headers={"Authorization": "Bearer token"}) for _ in range(10)]
            return await asyncio.gather(*reqs)

    with _temporary_get("/api/_batch", _ok), _temporary_get("/api/v1/_batch", _ok):
        responses = asyncio.run(_run_batch())

    assert all(response.status_code == 200 for response in responses)
    assert session_factory.counters["created"] == 20
    assert session_factory.counters["enter"] == 20
    assert session_factory.counters["exit"] == 20
    assert session_factory.counters["active"] == 0
