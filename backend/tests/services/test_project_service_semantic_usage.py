import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.errors import BadRequestError  # noqa: E402
from app.models import OrgEntitlement, OrgUsage, Project  # noqa: E402
from app.async_db import AsyncSessionLocal  # noqa: E402
from app.services.project_service import search_project_semantic_async  # noqa: E402
from app.services.usage_service import EMBEDDING_QUERY_KIND  # noqa: E402


class TestProjectServiceSemanticUsage(unittest.TestCase):
    def setUp(self) -> None:
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            self.skipTest("Postgres is not available for semantic usage tests")

    def test_missing_api_key_does_not_increment_usage(self) -> None:
        org_id = 8102
        previous_embeddings_enabled = settings.embeddings_enabled
        previous_openai_api_key = settings.openai_api_key
        settings.embeddings_enabled = True
        settings.openai_api_key = None
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                with get_session() as session:
                    project = Project(name="Usage Test", root_path=tmpdir, org_id=org_id)
                    session.add(project)
                    session.commit()
                    session.refresh(project)
                    project_id = project.id

                with self.assertRaises(BadRequestError):
                    async def _run() -> None:
                        async with AsyncSessionLocal() as session:
                            await search_project_semantic_async(session, project_id, org_id, "test query")

                    asyncio.run(_run())

                day = datetime.now(timezone.utc).date()
                with get_session() as session:
                    rows = session.exec(
                        select(OrgUsage).where(
                            OrgUsage.org_id == org_id,
                            OrgUsage.day == day,
                            OrgUsage.kind == EMBEDDING_QUERY_KIND,
                        )
                    ).all()
                    self.assertEqual(len(rows), 0)
        finally:
            settings.embeddings_enabled = previous_embeddings_enabled
            settings.openai_api_key = previous_openai_api_key
            with get_session() as session:
                session.exec(delete(Project).where(Project.org_id == org_id))
                session.exec(delete(OrgUsage).where(OrgUsage.org_id == org_id))
                session.exec(delete(OrgEntitlement).where(OrgEntitlement.org_id == org_id))
                session.commit()


if __name__ == "__main__":
    unittest.main()
