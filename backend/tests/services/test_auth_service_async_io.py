import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.services import auth_service


@pytest.mark.anyio
async def test_hash_password_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return "hashed"

    monkeypatch.setattr(auth_service.asyncio, "to_thread", _fake_to_thread)

    result = await auth_service._hash_password_async("password-123")

    assert result == "hashed"
    assert calls["func"] is auth_service._hash_password
    assert calls["args"] == ("password-123",)
    assert calls["kwargs"] == {"salt": None}


@pytest.mark.anyio
async def test_verify_password_async_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return True

    monkeypatch.setattr(auth_service.asyncio, "to_thread", _fake_to_thread)

    result = await auth_service._verify_password_async("password-123", "stored-hash")

    assert result is True
    assert calls["func"] is auth_service._verify_password
    assert calls["args"] == ("password-123", "stored-hash")
    assert calls["kwargs"] == {}
