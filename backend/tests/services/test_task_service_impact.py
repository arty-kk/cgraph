import sys
from pathlib import Path

import pytest
from sqlmodel import SQLModel, delete

sys.path.append(str(Path(__file__).resolve().parents[2]))

from app.async_db import AsyncSessionLocal, async_engine
from app.models import FileEdge
from app.services import task_service
from tests.services.db_helpers import ensure_async_postgres


@pytest.mark.anyio
async def test_impact_limits(ensure_async_postgres) -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await session.execute(delete(FileEdge).where(FileEdge.project_id == 1))
        session.add(FileEdge(project_id=1, src_path="A", dst_path="B", kind="import"))
        session.add(FileEdge(project_id=1, src_path="B", dst_path="C", kind="import"))
        await session.commit()

    async with AsyncSessionLocal() as session:
        impacted, truncated = await task_service._impact_async(session, 1, "C", max_nodes=1, max_depth=None)
    assert impacted == ["C"]
    assert truncated is True

    async with AsyncSessionLocal() as session:
        impacted, truncated = await task_service._impact_async(session, 1, "C", max_nodes=None, max_depth=1)
    assert impacted == ["B", "C"]
    assert truncated is True


@pytest.mark.anyio
async def test_impact_no_edges_includes_target(ensure_async_postgres) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(FileEdge).where(FileEdge.project_id == 1))
        await session.commit()
        impacted, truncated = await task_service._impact_async(
            session,
            1,
            "file.py",
            max_nodes=None,
            max_depth=None,
        )
    assert impacted == ["file.py"]
    assert len(impacted) == 1
    assert truncated is False
