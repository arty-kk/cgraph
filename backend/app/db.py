# backend/app/db.py
from __future__ import annotations

from sqlmodel import Session, create_engine

from .config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)


def get_session() -> Session:
    return Session(engine)
