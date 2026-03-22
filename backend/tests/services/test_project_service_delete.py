import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

pytest_plugins = ("tests.services.db_helpers",)

from app.async_db import AsyncSessionLocal, async_engine  # noqa: E402
from app.models import AnalysisRun, Project, RepoSnapshot  # noqa: E402
from app.services import project_service  # noqa: E402


@pytest.mark.anyio
async def test_load_patch_blob_ref_counts_async_handles_row_objects() -> None:
    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, stmt):
            _ = stmt
            return _Result(
                [
                    ("sha-a", 2),
                    ("sha-b", 1),
                ]
            )

    counts = await project_service.load_patch_blob_ref_counts_async(
        _Session(),
        {"sha-a", "sha-b", "sha-c"},
    )

    assert counts == {"sha-a": 2, "sha-b": 1, "sha-c": 0}


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
                    patch_blob_sha="sha-test",
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

            async def _cache_set_json_async(
                parts: list[str], payload: object, *, ttl_seconds=None
            ) -> None:
                _ = (payload, ttl_seconds)
                cache_calls.append(parts)

            with (
                mock.patch.object(
                    project_service,
                    "delete_project_snapshot_root_async",
                    side_effect=RuntimeError("root delete failed"),
                ),
                mock.patch.object(
                    project_service,
                    "delete_patch_blob_for_sha_async",
                    side_effect=RuntimeError("patch delete failed"),
                ),
                mock.patch.object(
                    project_service,
                    "delete_snapshot_async",
                    side_effect=RuntimeError("snapshot delete failed"),
                ),
                mock.patch.object(
                    project_service,
                    "cache_set_json_async",
                    side_effect=_cache_set_json_async,
                ),
            ):
                async with AsyncSessionLocal() as session:
                    await project_service.delete_project_async(session, project_id, org_id)

            async with AsyncSessionLocal() as session:
                project_row = await session.get(Project, project_id)
                assert project_row is None
                runs = (
                    (
                        await session.execute(
                            select(AnalysisRun).where(AnalysisRun.project_id == project_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                snapshots = (
                    (
                        await session.execute(
                            select(RepoSnapshot).where(RepoSnapshot.project_id == project_id)
                        )
                    )
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


@pytest.mark.anyio
async def test_delete_project_async_keeps_shared_patch_blob(ensure_async_postgres) -> None:
    if async_engine.sync_engine.dialect.name != "postgresql":
        pytest.skip("Postgres is required for project delete tests")

    org_id = 9102
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
        await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
        await session.execute(delete(Project).where(Project.org_id == org_id))
        await session.commit()

    try:
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            async with AsyncSessionLocal() as session:
                project1 = Project(name="Delete Shared 1", root_path=tmpdir1, org_id=org_id)
                project2 = Project(name="Delete Shared 2", root_path=tmpdir2, org_id=org_id)
                session.add(project1)
                session.add(project2)
                await session.commit()
                await session.refresh(project1)
                await session.refresh(project2)
                project1_id = int(project1.id or 0)
                project2_id = int(project2.id or 0)

                run1 = AnalysisRun(
                    org_id=org_id,
                    project_id=project1_id,
                    target_path=".",
                    mode="test",
                    prompt="prompt",
                    model_used="model",
                    result_json=json.dumps(
                        {"patch_unified_diff_meta": {"sha256": "sha-shared"}}, ensure_ascii=False
                    ),
                    patch_blob_sha="sha-shared",
                )
                run2 = AnalysisRun(
                    org_id=org_id,
                    project_id=project2_id,
                    target_path=".",
                    mode="test",
                    prompt="prompt",
                    model_used="model",
                    result_json=json.dumps(
                        {"patch_unified_diff_meta": {"sha256": "sha-shared"}}, ensure_ascii=False
                    ),
                    patch_blob_sha="sha-shared",
                )
                session.add(run1)
                session.add(run2)
                await session.commit()

            deleted_shas: list[str] = []

            async def _fake_delete_patch_blob_for_sha_async(sha: str) -> None:
                deleted_shas.append(sha)

            with (
                mock.patch.object(
                    project_service,
                    "_delete_patch_blob_for_sha_async",
                    side_effect=_fake_delete_patch_blob_for_sha_async,
                ),
                mock.patch.object(project_service, "delete_project_snapshot_root_async"),
                mock.patch.object(project_service, "delete_snapshot_async"),
            ):
                async with AsyncSessionLocal() as session:
                    await project_service.delete_project_async(session, project1_id, org_id)

            assert deleted_shas == []

            async with AsyncSessionLocal() as session:
                remaining_run = (
                    (
                        await session.execute(
                            select(AnalysisRun).where(AnalysisRun.project_id == project2_id)
                        )
                    )
                    .scalars()
                    .first()
                )
                assert remaining_run is not None
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
            await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
            await session.execute(delete(Project).where(Project.org_id == org_id))
            await session.commit()


@pytest.mark.anyio
async def test_delete_project_async_uses_db_sha_without_json_parsing(ensure_async_postgres, monkeypatch) -> None:
    if async_engine.sync_engine.dialect.name != "postgresql":
        pytest.skip("Postgres is required for project delete tests")

    org_id = 9103
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
        await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
        await session.execute(delete(Project).where(Project.org_id == org_id))
        await session.commit()

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            async with AsyncSessionLocal() as session:
                project = Project(name="Delete Perf", root_path=tmpdir, org_id=org_id)
                session.add(project)
                await session.commit()
                await session.refresh(project)
                project_id = int(project.id or 0)

                for idx in range(400):
                    sha = f"sha-{idx % 25}"
                    session.add(
                        AnalysisRun(
                            org_id=org_id,
                            project_id=project_id,
                            target_path=".",
                            mode="test",
                            prompt="prompt",
                            model_used="model",
                            result_json=json.dumps(
                                {"patch_unified_diff_meta": {"sha256": sha}},
                                ensure_ascii=False,
                            ),
                            patch_blob_sha=sha,
                        )
                    )
                await session.commit()

            deleted_shas: list[str] = []

            async def _fake_delete_patch_blob_for_sha_async(sha: str) -> None:
                deleted_shas.append(sha)

            def _json_loads_fail(*args, **kwargs):
                raise AssertionError("json.loads must not be used for patch sha scan")

            monkeypatch.setattr(project_service.json, "loads", _json_loads_fail)
            monkeypatch.setattr(
                project_service,
                "_delete_patch_blob_for_sha_async",
                _fake_delete_patch_blob_for_sha_async,
            )
            monkeypatch.setattr(project_service, "delete_project_snapshot_root_async", mock.AsyncMock())
            monkeypatch.setattr(project_service, "delete_snapshot_async", mock.AsyncMock())

            async with AsyncSessionLocal() as session:
                await project_service.delete_project_async(session, project_id, org_id)

            assert sorted(deleted_shas) == [f"sha-{idx}" for idx in range(25)]
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(AnalysisRun).where(AnalysisRun.org_id == org_id))
            await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
            await session.execute(delete(Project).where(Project.org_id == org_id))
            await session.commit()
