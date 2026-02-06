import sys
import unittest
from pathlib import Path
from typing import Callable

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, select

sys.path.append(str(Path(__file__).resolve().parents[2]))

import app.db as db  # noqa: E402
from app.models import FileEdge  # noqa: E402
from app.services import task_service  # noqa: E402


def _ensure_postgres() -> tuple[Engine, Callable[[], Session]]:
    try:
        from app.db import engine, get_session  # noqa: E402
    except ModuleNotFoundError:
        raise unittest.SkipTest("Postgres dependencies are not available for impact tests")
    try:
        with get_session() as session:
            session.exec(select(1)).first()
    except SQLAlchemyError:
        raise unittest.SkipTest("Postgres is not available for impact tests")
    SQLModel.metadata.create_all(engine)
    return engine, get_session


def test_impact_limits(monkeypatch) -> None:
    engine, get_test_session = _ensure_postgres()

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "get_session", get_test_session)
    monkeypatch.setattr(task_service, "get_session", get_test_session)

    with get_test_session() as session:
        session.add(FileEdge(project_id=1, src_path="A", dst_path="B", kind="import"))
        session.add(FileEdge(project_id=1, src_path="B", dst_path="C", kind="import"))
        session.commit()

    impacted, truncated = task_service._impact(1, "C", max_nodes=1, max_depth=None)
    assert impacted == ["C"]
    assert truncated is True

    impacted, truncated = task_service._impact(1, "C", max_nodes=None, max_depth=1)
    assert impacted == ["B", "C"]
    assert truncated is True


def test_impact_no_edges_includes_target(monkeypatch) -> None:
    engine, get_test_session = _ensure_postgres()

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "get_session", get_test_session)
    monkeypatch.setattr(task_service, "get_session", get_test_session)

    impacted, truncated = task_service._impact(1, "file.py", max_nodes=None, max_depth=None)
    assert impacted == ["file.py"]
    assert len(impacted) == 1
    assert truncated is False
