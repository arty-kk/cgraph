import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import auth_service


@pytest.mark.anyio
async def test_hash_password_async_uses_run_cpu_io_async(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, operation=None, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        calls["operation"] = operation
        return "hashed"

    monkeypatch.setattr(auth_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await auth_service._hash_password_async("password-123")

    assert result == "hashed"
    assert calls["func"] is auth_service._hash_password
    assert calls["args"] == ("password-123",)
    assert calls["kwargs"] == {"salt": None}
    assert calls["operation"] == "auth_service.hash_password"


@pytest.mark.anyio
async def test_verify_password_async_uses_run_cpu_io_async(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_run_cpu_io_async(func, *args, operation=None, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        calls["operation"] = operation
        return True

    monkeypatch.setattr(auth_service, "run_cpu_io_async", _fake_run_cpu_io_async)

    result = await auth_service._verify_password_async("password-123", "stored-hash")

    assert result is True
    assert calls["func"] is auth_service._verify_password
    assert calls["args"] == ("password-123", "stored-hash")
    assert calls["kwargs"] == {}
    assert calls["operation"] == "auth_service.verify_password"


@pytest.mark.anyio
async def test_hash_password_async_returns_pbkdf2_sha256_hash() -> None:
    hashed = await auth_service._hash_password_async("password-123")

    assert hashed.startswith("pbkdf2_sha256$")


@pytest.mark.anyio
async def test_verify_password_async_validates_correct_and_incorrect_password() -> None:
    password = "password-123"
    stored = await auth_service._hash_password_async(password)

    assert await auth_service._verify_password_async(password, stored) is True
    assert await auth_service._verify_password_async("wrong-password", stored) is False
