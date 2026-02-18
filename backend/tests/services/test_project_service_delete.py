import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal, async_engine
from app.models import AnalysisRun, Project, RepoSnapshot
from app.services import project_service
from tests.services.db_helpers import ensure_async_postgres


@pytest.mark.anyio
async def test_delete_project_file_errors_do_not_rollback_db(ensure_async_postgres) -> None:
    if async_engine.sync_engine.dialect.name != "postgresql":
        pytest.skip("Postgres is required for project delete tests")

    org_id = 9101
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
        await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
        await session.execute(delete(Project).where(Project.org_id == org_id))
        await session.commit()

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            async with AsyncSessionLocal() as session:
                project = Project(name="Delete Test", root_path=tmpdir, org_id=org_id)
                session.add(project)
                await session.commit()
                await session.refresh(project)
                project_id = int(project.id or 0)

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
                await session.commit()

            cache_calls: list[list[str]] = []

            async def _cache_set_json_async(parts: list[str], payload: object, *, ttl_seconds=None) -> None:
                _ = (payload, ttl_seconds)
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
                async with AsyncSessionLocal() as session:
                    await project_service.delete_project_async(session, project_id, org_id)

            async with AsyncSessionLocal() as session:
                project_row = await session.get(Project, project_id)
                assert project_row is None
                runs = (
                    (await session.execute(select(AnalysisRun).where(AnalysisRun.project_id == project_id)))
                    .scalars()
                    .all()
                )
                snapshots = (
                    (await session.execute(select(RepoSnapshot).where(RepoSnapshot.project_id == project_id)))
                    .scalars()
                    .all()
                )
                assert runs == []
                assert snapshots == []

            assert ["project_delete_failed", "project_root", str(project_id)] in cache_calls
            assert ["project_delete_failed", "patch", "sha-test"] in cache_calls
            assert ["project_delete_failed", "snapshot", "snap-sha"] in cache_calls
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
            await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
            await session.execute(delete(Project).where(Project.org_id == org_id))
            await session.commit()
