import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal  # noqa: E402
from app.db import engine, get_session  # noqa: E402
from app.models import Project, RepoSnapshot  # noqa: E402
from app.services import project_service  # noqa: E402
from app.snapshots import SnapshotMeta  # noqa: E402




class TestProjectServiceCreateFromSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        if engine.dialect.name != "postgresql":
            self.skipTest("Postgres is required for snapshot create tests")
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            self.skipTest("Postgres is not available for snapshot create tests")

    def tearDown(self) -> None:
        with get_session() as session:
            session.exec(delete(RepoSnapshot).where(RepoSnapshot.org_id == 9102))
            session.exec(delete(Project).where(Project.org_id == 9102))
            session.commit()

    def test_create_project_from_snapshot_rolls_back_project_on_snapshot_error(self) -> None:
        org_id = 9102
        with tempfile.TemporaryDirectory() as tmpdir:
            meta = SnapshotMeta(
                storage="local",
                sha256="a" * 64,
                archive_name="repo.zip",
                archive_ext=".zip",
                size=1,
                file="snapshots/test/archive.zip",
                root_dir="snapshots/test/repo",
            )

            with (
                mock.patch.object(
                    project_service,
                    "prepare_project_snapshot_root",
                    return_value=Path(tmpdir),
                ),
                mock.patch.object(project_service, "RepoSnapshot", side_effect=RuntimeError("snapshot persist failed")),
            ):
                with self.assertRaises(RuntimeError):
                    async def _run() -> None:
                        async with AsyncSessionLocal() as session:
                            await project_service.create_project_from_snapshot_async(
                                session=session,
                                name="rollback-test",
                                meta=meta,
                                org_id=org_id,
                            )

                    asyncio.run(_run())

            with get_session() as session:
                project_row = session.exec(
                    select(Project).where(Project.org_id == org_id, Project.name == "rollback-test")
                ).first()
                snapshot_rows = session.exec(
                    select(RepoSnapshot).where(RepoSnapshot.org_id == org_id)
                ).all()

            self.assertIsNone(project_row)
            self.assertEqual(snapshot_rows, [])


if __name__ == "__main__":
    unittest.main()
