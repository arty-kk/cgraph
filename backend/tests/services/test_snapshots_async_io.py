import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import snapshots


@pytest.mark.anyio
async def test_store_snapshot_upload_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Upload:
        def __init__(self):
            self.file = object()
            self.seek_calls: list[int] = []

        async def seek(self, offset: int):
            self.seek_calls.append(offset)

    calls: dict[str, object] = {}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["func"] = func
        calls["args"] = args
        calls["kwargs"] = kwargs
        return "meta"

    monkeypatch.setattr(snapshots.asyncio, "to_thread", _fake_to_thread)

    upload = _Upload()

    result = await snapshots.store_snapshot_upload(upload, "repo.zip")

    assert result == "meta"
    assert upload.seek_calls == [0]
    assert calls["func"] is snapshots.store_snapshot_stream
    assert calls["args"] == (upload.file, "repo.zip")
    assert calls["kwargs"] == {}
