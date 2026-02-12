import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.db import engine, get_session  # noqa: E402
from app.models import AnalysisRun, Project, RepoSnapshot  # noqa: E402
from app.services import project_service  # noqa: E402


class TestProjectServiceDelete(unittest.TestCase):
    def setUp(self) -> None:
        if engine.dialect.name != "postgresql":
            self.skipTest("Postgres is required for project delete tests")
        try:
            with get_session() as session:
                session.exec(select(1)).first()
        except SQLAlchemyError:
            self.skipTest("Postgres is not available for project delete tests")

    def tearDown(self) -> None:
        with get_session() as session:
            session.exec(delete(AnalysisRun).where(AnalysisRun.org_id == 9101))
            session.exec(delete(RepoSnapshot).where(RepoSnapshot.org_id == 9101))
            session.exec(delete(Project).where(Project.org_id == 9101))
            session.commit()

    def test_delete_project_file_errors_do_not_rollback_db(self) -> None:
        org_id = 9101
        with tempfile.TemporaryDirectory() as tmpdir:
            with get_session() as session:
                project = Project(name="Delete Test", root_path=tmpdir, org_id=org_id)
                session.add(project)
                session.commit()
                session.refresh(project)
                project_id = project.id

                run = AnalysisRun(
                    org_id=org_id,
                    project_id=project_id,
                    target_path=".",
                    mode="test",
                    prompt="prompt",
                    model_used="model",
                    result_json=json.dumps(
                        {"patch_unified_diff_meta": {"sha256": "sha-test"}}, ensure_ascii=False
                    ),
                )
                session.add(run)
                snapshot_payload = {
                    "storage": "local",
                    "sha256": "snap-sha",
                    "archive_name": "repo.zip",
                    "archive_ext": ".zip",
                    "size": 1,
                    "file": "snapshots/snap-sha/archive.zip",
                    "root_dir": "snapshots/snap-sha/repo",
                }
                snapshot = RepoSnapshot(
                    org_id=org_id,
                    project_id=project_id,
                    content_sha256="snap-sha",
                    archive_name="repo.zip",
                    storage_json=json.dumps(snapshot_payload, ensure_ascii=False),
                )
                session.add(snapshot)
                session.commit()

            cache_calls: list[list[str]] = []

            async def _cache_set_json_async(parts: list[str], payload: object, *, ttl_seconds=None) -> None:
                cache_calls.append(parts)

            with (
                mock.patch.object(
                    project_service,
                    "delete_project_snapshot_root",
                    side_effect=RuntimeError("root delete failed"),
                ),
                mock.patch.object(
                    project_service,
                    "delete_patch_blob_for_sha",
                    side_effect=RuntimeError("patch delete failed"),
                ),
                mock.patch.object(
                    project_service,
                    "delete_snapshot",
                    side_effect=RuntimeError("snapshot delete failed"),
                ),
                mock.patch.object(project_service, "cache_set_json_async", side_effect=_cache_set_json_async),
            ):
                with get_session() as session:
                    asyncio.run(project_service.delete_project_async(session, project_id, org_id))

            with get_session() as session:
                project_row = session.get(Project, project_id)
                self.assertIsNone(project_row)
                runs = session.exec(
                    select(AnalysisRun).where(AnalysisRun.project_id == project_id)
                ).all()
                snapshots = session.exec(
                    select(RepoSnapshot).where(RepoSnapshot.project_id == project_id)
                ).all()
                self.assertEqual(runs, [])
                self.assertEqual(snapshots, [])

            self.assertIn(
                ["project_delete_failed", "project_root", str(project_id)],
                cache_calls,
            )
            self.assertIn(["project_delete_failed", "patch", "sha-test"], cache_calls)
            self.assertIn(["project_delete_failed", "snapshot", "snap-sha"], cache_calls)


if __name__ == "__main__":
    unittest.main()
