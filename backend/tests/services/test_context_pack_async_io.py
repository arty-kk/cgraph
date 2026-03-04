import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app import context_pack


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self) -> None:
        self.hash_query_calls = 0
        self.execute_calls: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.execute_calls.append(sql)
        if "WITH RECURSIVE walk" in sql:
            direction = "in" if "edge.dst_path = walk.node" in sql else "out"
            start = (params or {}).get("start")
            if direction == "out" and start == "target.py":
                return _Result([("dep_a.py",), ("dep_b.py",)])
            return _Result([])
        if "filenode.path, filenode.file_hash" in sql:
            self.hash_query_calls += 1
            return _Result(
                [
                    ("target.py", "h-target"),
                    ("dep_a.py", "h-a"),
                    ("dep_b.py", "h-b"),
                    ("candidate.py", "h-c"),
                ]
            )
        if "ORDER BY filenode.fan_in DESC" in sql:
            return _Result([("candidate.py",)])
        raise AssertionError(f"Unexpected SQL: {sql}")


@pytest.mark.anyio
async def test_pack_context_uses_single_hash_preload_and_batch_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    calls = {"cache_get": 0, "cache_mget": 0}

    contents = {
        "target.py": "def target():\n    return Foo\n",
        "dep_a.py": "from x import y\n",
        "dep_b.py": "from z import k\n",
        "candidate.py": "Foo()\n",
    }

    async def _read_file_async(path: Path, max_chars: int) -> str:
        return contents.get(path.name, "")[:max_chars]

    async def _cache_get_json_async(_parts):
        calls["cache_get"] += 1
        return None

    async def _cache_set_json_async(_parts, _payload, **_kwargs):
        return None

    async def _cache_mget_json_async(parts_list):
        calls["cache_mget"] += 1
        return [None for _ in parts_list]

    async def _cache_mset_json_async(_entries, **_kwargs):
        return None

    async def _contract_async(_session, _project_id, _root, path):
        if path == "target.py":
            return {"exports": ["Foo"]}
        return {"exports": [], "path": path}

    monkeypatch.setattr(context_pack, "_read_file_async", _read_file_async)
    monkeypatch.setattr(context_pack, "cache_get_json_async", _cache_get_json_async)
    monkeypatch.setattr(context_pack, "cache_set_json_async", _cache_set_json_async)
    monkeypatch.setattr(context_pack, "cache_mget_json_async", _cache_mget_json_async)
    monkeypatch.setattr(context_pack, "cache_mset_json_async", _cache_mset_json_async)
    monkeypatch.setattr(context_pack, "get_or_build_contract_async", _contract_async)

    packed = await context_pack.pack_context_async(
        project_id=1,
        project_root=Path("."),
        target_rel="target.py",
        depth=1,
        dep_mode="contracts",
        session=session,
    )

    assert session.hash_query_calls == 1
    assert calls["cache_mget"] >= 1
    assert calls["cache_get"] == 2
    assert packed.files[0]["path"] == "target.py"


@pytest.mark.anyio
async def test_pack_context_preserves_input_order_and_limits_under_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SessionOrder(_Session):
        async def execute(self, statement, params=None):
            sql = str(statement)
            if "WITH RECURSIVE walk" in sql:
                start = (params or {}).get("start")
                direction = "in" if "edge.dst_path = walk.node" in sql else "out"
                if direction == "out" and start == "target.py":
                    return _Result([(f"dep_{idx}.py",) for idx in range(1, 8)])
                return _Result([])
            if "filenode.path, filenode.file_hash" in sql:
                self.hash_query_calls += 1
                return _Result(
                    [("target.py", "h-target")]
                    + [(f"dep_{idx}.py", f"h-{idx}") for idx in range(1, 8)]
                )
            if "ORDER BY filenode.fan_in DESC" in sql:
                return _Result([])
            raise AssertionError(sql)

    async def _read_file_async(path: Path, max_chars: int) -> str:
        await asyncio.sleep(0.01)
        return (path.name + "\n")[:max_chars]

    async def _cache_mget_json_async(parts_list):
        return [None for _ in parts_list]

    async def _cache_mset_json_async(_entries, **_kwargs):
        return None

    async def _cache_get_json_async(_parts):
        return None

    async def _cache_set_json_async(_parts, _payload, **_kwargs):
        return None

    async def _contract_async(_session, _project_id, _root, path):
        if path == "target.py":
            return {"exports": []}
        return {"exports": [], "path": path}

    monkeypatch.setattr(context_pack, "_read_file_async", _read_file_async)
    monkeypatch.setattr(context_pack, "cache_mget_json_async", _cache_mget_json_async)
    monkeypatch.setattr(context_pack, "cache_mset_json_async", _cache_mset_json_async)
    monkeypatch.setattr(context_pack, "cache_get_json_async", _cache_get_json_async)
    monkeypatch.setattr(context_pack, "cache_set_json_async", _cache_set_json_async)
    monkeypatch.setattr(context_pack, "get_or_build_contract_async", _contract_async)

    packed = await context_pack.pack_context_async(
        project_id=1,
        project_root=Path("."),
        target_rel="target.py",
        depth=1,
        dep_mode="full",
        max_files=4,
        max_total_chars=200,
        session=_SessionOrder(),
    )

    assert [item["path"] for item in packed.files] == [
        "target.py",
        "dep_1.py",
        "dep_2.py",
        "dep_3.py",
    ]
    assert packed.graph["deps"][:3] == ["dep_1.py", "dep_2.py", "dep_3.py"]


@pytest.mark.anyio
async def test_pack_context_concurrent_requests_do_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()

    async def _read_file_async(path: Path, max_chars: int) -> str:
        await asyncio.sleep(0.005)
        return ("x" * 20)[:max_chars]

    async def _cache_get_json_async(_parts):
        return None

    async def _cache_set_json_async(_parts, _payload, **_kwargs):
        return None

    async def _cache_mget_json_async(parts_list):
        await asyncio.sleep(0.001)
        return [None for _ in parts_list]

    async def _cache_mset_json_async(_entries, **_kwargs):
        await asyncio.sleep(0.001)
        return None

    async def _contract_async(_session, _project_id, _root, path):
        await asyncio.sleep(0.001)
        return {"exports": ["Foo"] if path == "target.py" else []}

    monkeypatch.setattr(context_pack, "_read_file_async", _read_file_async)
    monkeypatch.setattr(context_pack, "cache_get_json_async", _cache_get_json_async)
    monkeypatch.setattr(context_pack, "cache_set_json_async", _cache_set_json_async)
    monkeypatch.setattr(context_pack, "cache_mget_json_async", _cache_mget_json_async)
    monkeypatch.setattr(context_pack, "cache_mset_json_async", _cache_mset_json_async)
    monkeypatch.setattr(context_pack, "get_or_build_contract_async", _contract_async)

    started = time.perf_counter()
    result = await asyncio.wait_for(
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
                for _ in range(12)
            ]
        ),
        timeout=4,
    )
    elapsed = time.perf_counter() - started

    assert len(result) == 12
    assert elapsed < 4


@pytest.mark.anyio
async def test_pack_context_neighbors_use_recursive_cte_single_roundtrip_per_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()

    async def _read_file_async(path: Path, max_chars: int) -> str:
        return (path.name + "\n")[:max_chars]

    async def _cache_get_json_async(_parts):
        return None

    async def _cache_set_json_async(_parts, _payload, **_kwargs):
        return None

    async def _cache_mget_json_async(parts_list):
        return [None for _ in parts_list]

    async def _cache_mset_json_async(_entries, **_kwargs):
        return None

    async def _contract_async(_session, _project_id, _root, path):
        return {"exports": ["Foo"] if path == "target.py" else [], "path": path}

    monkeypatch.setattr(context_pack, "_read_file_async", _read_file_async)
    monkeypatch.setattr(context_pack, "cache_get_json_async", _cache_get_json_async)
    monkeypatch.setattr(context_pack, "cache_set_json_async", _cache_set_json_async)
    monkeypatch.setattr(context_pack, "cache_mget_json_async", _cache_mget_json_async)
    monkeypatch.setattr(context_pack, "cache_mset_json_async", _cache_mset_json_async)
    monkeypatch.setattr(context_pack, "get_or_build_contract_async", _contract_async)

    packed = await context_pack.pack_context_async(
        project_id=1,
        project_root=Path("."),
        target_rel="target.py",
        depth=3,
        dep_mode="contracts",
        session=session,
    )

    traversal_sql = [sql for sql in session.execute_calls if "WITH RECURSIVE walk" in sql]
    assert len(traversal_sql) == 2
    assert not any(
        "fileedge.src_path IN" in sql or "fileedge.dst_path IN" in sql
        for sql in session.execute_calls
    )
    assert packed.graph["outbound"] == ["dep_a.py", "dep_b.py"]
