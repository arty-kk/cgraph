#backend/app/db.py
from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, create_engine

from .config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

def init_db() -> None:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except SQLAlchemyError as e:
        raise RuntimeError(f"DB init failed: {e}") from e

def get_session() -> Session:
    return Session(engine)
