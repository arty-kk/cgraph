import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from sqlmodel import delete, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal, async_engine
from app.models import Project, RepoSnapshot
from app.services import project_service
from app.snapshots import SnapshotMeta
from tests.services.db_helpers import ensure_async_postgres


@pytest.mark.anyio
async def test_create_project_from_snapshot_rolls_back_project_on_snapshot_error(
    ensure_async_postgres,
) -> None:
    if async_engine.sync_engine.dialect.name != "postgresql":
        pytest.skip("Postgres is required for snapshot create tests")

    org_id = 9102
    async with AsyncSessionLocal() as session:
        await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
        await session.execute(delete(Project).where(Project.org_id == org_id))
        await session.commit()

    try:
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
                with pytest.raises(RuntimeError):
                    async with AsyncSessionLocal() as session:
                        await project_service.create_project_from_snapshot_async(
                            session=session,
                            name="rollback-test",
                            meta=meta,
                            org_id=org_id,
                        )

            async with AsyncSessionLocal() as session:
                project_row = (
                    (
                        await session.execute(
                            select(Project).where(Project.org_id == org_id, Project.name == "rollback-test")
                        )
                    )
                    .scalars()
                    .first()
                )
                snapshot_rows = (
                    (
                        await session.execute(select(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
                    )
                    .scalars()
                    .all()
                )

            assert project_row is None
            assert snapshot_rows == []
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(RepoSnapshot).where(RepoSnapshot.org_id == org_id))
            await session.execute(delete(Project).where(Project.org_id == org_id))
            await session.commit()
