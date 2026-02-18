import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal
from app.config import settings
from app.errors import BadRequestError
from app.models import OrgEntitlement, OrgUsage, Project
from app.services.project_service import search_project_semantic_async
from app.services.usage_service import EMBEDDING_QUERY_KIND
from tests.services.db_helpers import ensure_async_postgres


@pytest.mark.anyio
async def test_missing_api_key_does_not_increment_usage(ensure_async_postgres) -> None:
    org_id = 8102
    previous_embeddings_enabled = settings.embeddings_enabled
    previous_openai_api_key = settings.openai_api_key
    settings.embeddings_enabled = True
    settings.openai_api_key = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            async with AsyncSessionLocal() as session:
                project = Project(name="Usage Test", root_path=tmpdir, org_id=org_id)
                session.add(project)
                await session.commit()
                await session.refresh(project)
                project_id = int(project.id or 0)

            with pytest.raises(BadRequestError):
                async with AsyncSessionLocal() as session:
                    await search_project_semantic_async(session, project_id, org_id, "test query")

            day = datetime.now(timezone.utc).date()
            async with AsyncSessionLocal() as session:
                rows = (
                    (
                        await session.execute(
                            select(OrgUsage).where(
                                OrgUsage.org_id == org_id,
                                OrgUsage.day == day,
                                OrgUsage.kind == EMBEDDING_QUERY_KIND,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows) == 0
    finally:
        settings.embeddings_enabled = previous_embeddings_enabled
        settings.openai_api_key = previous_openai_api_key
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Project).where(Project.org_id == org_id))
            await session.execute(delete(OrgUsage).where(OrgUsage.org_id == org_id))
            await session.execute(delete(OrgEntitlement).where(OrgEntitlement.org_id == org_id))
            await session.commit()
