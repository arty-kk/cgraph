import sys
import tempfile
from pathlib import Path

import pytest
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

import app.scan as scan
from app.async_db import AsyncSessionLocal
from app.config import settings
from app.errors import LimitExceededError
from app.models import FileChunkEmbedding, FileNode, FileText, OrgEntitlement
from app.scan import scan_project_async
from app.utils import sha256_text
from tests.services.db_helpers import ensure_async_postgres


@pytest.mark.anyio
async def test_missing_key_does_not_delete_embeddings_on_change(ensure_async_postgres) -> None:
    project_id = 9001
    org_id = 9002
    previous_embeddings_enabled = settings.embeddings_enabled
    previous_openai_api_key = settings.openai_api_key
    settings.embeddings_enabled = True
    settings.openai_api_key = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            rel_path = "example.py"
            file_path = root / rel_path
            file_path.write_text("print('old')\n", encoding="utf-8")
            old_hash = sha256_text(file_path.read_text(encoding="utf-8"))
            async with AsyncSessionLocal() as session:
                session.add(
                    OrgEntitlement(
                        org_id=org_id,
                        key="embeddings_enabled",
                        value_bool=True,
                    )
                )
                session.add(
                    FileChunkEmbedding(
                        project_id=project_id,
                        path=rel_path,
                        chunk_index=0,
                        file_hash=old_hash,
                        embedding_json="[]",
                        symbol_name="",
                        symbol_start_line=0,
                        symbol_end_line=0,
                    )
                )
                await session.commit()

            file_path.write_text("print('new')\n", encoding="utf-8")

            await scan_project_async(project_id, org_id, root)

            async with AsyncSessionLocal() as session:
                rows = (
                    (
                        await session.execute(
                            select(FileChunkEmbedding).where(
                                FileChunkEmbedding.project_id == project_id,
                                FileChunkEmbedding.path == rel_path,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows) == 1
    finally:
        settings.embeddings_enabled = previous_embeddings_enabled
        settings.openai_api_key = previous_openai_api_key
        async with AsyncSessionLocal() as session:
            await session.execute(delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id))
            await session.execute(delete(FileNode).where(FileNode.project_id == project_id))
            await session.execute(delete(FileText).where(FileText.project_id == project_id))
            await session.execute(
                delete(OrgEntitlement).where(
                    OrgEntitlement.org_id == org_id,
                    OrgEntitlement.key == "embeddings_enabled",
                )
            )
            await session.commit()


@pytest.mark.anyio
async def test_scan_embeddings_partial_failures_do_not_fail_scan(
    ensure_async_postgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = 9011
    org_id = 9012
    previous_embeddings_enabled = settings.embeddings_enabled
    previous_openai_api_key = settings.openai_api_key
    settings.embeddings_enabled = True
    settings.openai_api_key = "test"

    class _EmbeddingItem:
        def __init__(self, embedding):
            self.embedding = embedding

    class _EmbeddingsResponse:
        def __init__(self):
            self.data = [_EmbeddingItem([0.1, 0.2])]

    class _Embeddings:
        async def create(self, model, input):
            _ = model
            if any("fail" in chunk for chunk in input):
                raise RuntimeError("boom")
            return _EmbeddingsResponse()

    class _Client:
        def __init__(self):
            self.embeddings = _Embeddings()

    async def _fake_openai_io(fn, kind="short"):
        _ = kind
        return await fn()

    monkeypatch.setattr(scan, "get_async_openai_client", lambda: _Client())
    monkeypatch.setattr(scan, "run_openai_io_async", _fake_openai_io)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "ok.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "fail.py").write_text("print('fail')\n", encoding="utf-8")
            async with AsyncSessionLocal() as session:
                session.add(OrgEntitlement(org_id=org_id, key="embeddings_enabled", value_bool=True))
                await session.commit()

            result = await scan_project_async(project_id, org_id, root)
            assert result["files"] == 2

            async with AsyncSessionLocal() as session:
                node_count = (
                    (
                        await session.execute(select(FileNode).where(FileNode.project_id == project_id))
                    )
                    .scalars()
                    .all()
                )
                embeddings = (
                    (
                        await session.execute(
                            select(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(node_count) == 2
                assert len(embeddings) == 1
                assert embeddings[0].path == "ok.py"
    finally:
        settings.embeddings_enabled = previous_embeddings_enabled
        settings.openai_api_key = previous_openai_api_key
        async with AsyncSessionLocal() as session:
            await session.execute(delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id))
            await session.execute(delete(FileNode).where(FileNode.project_id == project_id))
            await session.execute(delete(FileText).where(FileText.project_id == project_id))
            await session.execute(
                delete(OrgEntitlement).where(
                    OrgEntitlement.org_id == org_id,
                    OrgEntitlement.key == "embeddings_enabled",
                )
            )
            await session.commit()


@pytest.mark.anyio
async def test_scan_embeddings_quota_exceeded_skips_only_limited_files(
    ensure_async_postgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = 9021
    org_id = 9022
    previous_embeddings_enabled = settings.embeddings_enabled
    previous_openai_api_key = settings.openai_api_key
    settings.embeddings_enabled = True
    settings.openai_api_key = "test"

    class _EmbeddingItem:
        def __init__(self, embedding):
            self.embedding = embedding

    class _EmbeddingsResponse:
        def __init__(self):
            self.data = [_EmbeddingItem([0.1, 0.2])]

    class _Embeddings:
        async def create(self, **_kwargs):
            return _EmbeddingsResponse()

    class _Client:
        def __init__(self):
            self.embeddings = _Embeddings()

    calls = 0

    async def _fake_check_and_increment(_session, _org_id, _kind, _amount, _limit):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise LimitExceededError("embeddings_daily_chunk_limit")

    async def _fake_openai_io(fn, kind="short"):
        _ = kind
        return await fn()

    monkeypatch.setattr(scan, "get_async_openai_client", lambda: _Client())
    monkeypatch.setattr(scan, "run_openai_io_async", _fake_openai_io)
    monkeypatch.setattr(scan, "check_and_increment_async", _fake_check_and_increment)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "one.py").write_text("print('one')\n", encoding="utf-8")
            (root / "two.py").write_text("print('two')\n", encoding="utf-8")
            async with AsyncSessionLocal() as session:
                session.add(OrgEntitlement(org_id=org_id, key="embeddings_enabled", value_bool=True))
                await session.commit()

            result = await scan_project_async(project_id, org_id, root)
            assert result["files"] == 2

            async with AsyncSessionLocal() as session:
                embeddings = (
                    (
                        await session.execute(
                            select(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(embeddings) == 1
    finally:
        settings.embeddings_enabled = previous_embeddings_enabled
        settings.openai_api_key = previous_openai_api_key
        async with AsyncSessionLocal() as session:
            await session.execute(delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id))
            await session.execute(delete(FileNode).where(FileNode.project_id == project_id))
            await session.execute(delete(FileText).where(FileText.project_id == project_id))
            await session.execute(
                delete(OrgEntitlement).where(
                    OrgEntitlement.org_id == org_id,
                    OrgEntitlement.key == "embeddings_enabled",
                )
            )
            await session.commit()
