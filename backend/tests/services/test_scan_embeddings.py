import sys
import asyncio
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.config import settings  # noqa: E402
from app.db import get_session  # noqa: E402
from app.models import FileChunkEmbedding, FileNode, FileText, OrgEntitlement  # noqa: E402
from app.scan import scan_project_async  # noqa: E402
from app.utils import sha256_text  # noqa: E402


class TestScanEmbeddings(unittest.TestCase):
    def setUp(self) -> None:
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            self.skipTest("Postgres is not available for scan embeddings tests")

    def test_missing_key_does_not_delete_embeddings_on_change(self) -> None:
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
                with get_session() as session:
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
                    session.commit()

                file_path.write_text("print('new')\n", encoding="utf-8")

                asyncio.run(scan_project_async(project_id, org_id, root))

                with get_session() as session:
                    rows = session.exec(
                        select(FileChunkEmbedding).where(
                            FileChunkEmbedding.project_id == project_id,
                            FileChunkEmbedding.path == rel_path,
                        )
                    ).all()
                    self.assertEqual(len(rows), 1)
        finally:
            settings.embeddings_enabled = previous_embeddings_enabled
            settings.openai_api_key = previous_openai_api_key
            with get_session() as session:
                session.exec(
                    delete(FileChunkEmbedding).where(FileChunkEmbedding.project_id == project_id)
                )
                session.exec(delete(FileNode).where(FileNode.project_id == project_id))
                session.exec(delete(FileText).where(FileText.project_id == project_id))
                session.exec(
                    delete(OrgEntitlement).where(
                        OrgEntitlement.org_id == org_id,
                        OrgEntitlement.key == "embeddings_enabled",
                    )
                )
                session.commit()


if __name__ == "__main__":
    unittest.main()
