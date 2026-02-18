from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.async_db import AsyncSessionLocal, async_engine


@asynccontextmanager
async def async_db_session() -> AsyncIterator[object]:
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def ensure_async_postgres() -> None:
    try:
        async with async_engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
    except SQLAlchemyError:
        pytest.skip("Postgres is not available for tests")
