from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext import asyncio as sa_asyncio

from . import config


def _async_database_url() -> str:
    url = config.settings.database_url
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+psycopg_async://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg_async://", 1)
    return url


async_engine = sa_asyncio.create_async_engine(
    _async_database_url(),
    echo=False,
    pool_pre_ping=True,
    pool_size=config.settings.db_pool_size,
    max_overflow=config.settings.db_max_overflow,
    pool_timeout=config.settings.db_pool_timeout_seconds,
    pool_recycle=config.settings.db_pool_recycle_seconds,
)

AsyncSessionLocal = sa_asyncio.async_sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=sa_asyncio.AsyncSession,
)


async def init_async_db() -> None:
    try:
        async with async_engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
    except SQLAlchemyError as e:
        raise RuntimeError(f"DB init failed: {e}") from e


async def close_async_db() -> None:
    await async_engine.dispose()


async def get_async_session() -> AsyncIterator[sa_asyncio.AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
