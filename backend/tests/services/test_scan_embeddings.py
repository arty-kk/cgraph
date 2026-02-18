import sys
import tempfile
from pathlib import Path

import pytest
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal
from app.config import settings
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
