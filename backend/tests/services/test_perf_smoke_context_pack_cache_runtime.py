import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import context_pack
from app.infra import cache as cache_module


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Session:
    async def execute(self, statement, params=None):
        sql = str(statement)
        if "WITH RECURSIVE walk" in sql:
            direction = "in" if "edge.dst_path = walk.node" in sql else "out"
            start = (params or {}).get("start")
            if direction == "out" and start == "target.py":
                return _Result([("dep_a.py",), ("dep_b.py",)])
            return _Result([])
        if "filenode.path, filenode.file_hash" in sql:
            return _Result(
                [
                    ("target.py", "h-target"),
                    ("dep_a.py", "h-a"),
                    ("dep_b.py", "h-b"),
                ]
            )
        if "ORDER BY filenode.fan_in DESC" in sql:
            return _Result([])
        raise AssertionError(sql)


class _Pipeline:
    def __init__(self, client: "_CacheClient") -> None:
        self.client = client
        self.items: list[tuple[str, int, str]] = []

    def setex(self, key: str, ttl: int, payload: str) -> None:
        self.items.append((key, ttl, payload))

    async def execute(self) -> None:
        for key, _ttl, payload in self.items:
            self.client.storage[key] = payload


class _CacheClient:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}

    async def get(self, key: str):
        return self.storage.get(key)

    async def setex(self, key: str, ttl: int, payload: str):
        _ = ttl
        self.storage[key] = payload

    async def mget(self, keys):
        return [self.storage.get(key) for key in keys]

    def pipeline(self, transaction: bool = False):
        _ = transaction
        return _Pipeline(self)


@pytest.mark.anyio
async def test_pack_context_cache_runtime_concurrency_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    cache_client = _CacheClient()

    async def _read_file_async(path: Path, max_chars: int) -> str:
        await asyncio.sleep(0.004)
        return (f"{path.name}:stub")[:max_chars]

    async def _contract_async(_session, _project_id, _root, path):
        await asyncio.sleep(0.001)
        return {"exports": ["Foo"] if path == "target.py" else [], "path": path}

    async def _fake_run_cpu_io_async(fn, *args, operation=None, **kwargs):
        _ = (operation, kwargs)
        await asyncio.sleep(0)
        return fn(*args)

    monkeypatch.setattr(context_pack, "_read_file_async", _read_file_async)
    monkeypatch.setattr(context_pack, "get_or_build_contract_async", _contract_async)
    monkeypatch.setattr(cache_module.settings, "cache_enabled", True)
    monkeypatch.setattr(cache_module.settings, "cache_default_ttl_seconds", 60)
    monkeypatch.setattr(cache_module.settings, "cache_entry_max_bytes", 10_000)
    monkeypatch.setattr(cache_module, "get_async_redis_client", lambda: cache_client)
    monkeypatch.setattr(cache_module, "run_cpu_io_async", _fake_run_cpu_io_async)

    ticks = 0
    stop = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.003)

    ticker = asyncio.create_task(_ticker())
    started = time.perf_counter()
    try:
        packed = await asyncio.wait_for(
            asyncio.gather(
                *[
                    context_pack.pack_context_async(
                        project_id=1,
                        project_root=Path("."),
                        target_rel="target.py",
                        depth=1,
                        dep_mode="contracts",
                        session=session,
                    )
                    for _ in range(20)
                ]
            ),
            timeout=5,
        )
    finally:
        stop.set()
        await ticker

    elapsed = time.perf_counter() - started
    assert len(packed) == 20
    assert ticks >= 3
    assert elapsed < 5
