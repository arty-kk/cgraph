import sys
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

sys.path.append(str(Path(__file__).resolve().parents[2]))

import app.db as db  # noqa: E402
from app.models import FileEdge  # noqa: E402
from app.services import task_service  # noqa: E402


def test_impact_limits(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def get_test_session() -> Session:
        return Session(engine)

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "get_session", get_test_session)
    monkeypatch.setattr(task_service, "get_session", get_test_session)

    with get_test_session() as session:
        session.add(FileEdge(project_id=1, src_path="A", dst_path="B", kind="import"))
        session.add(FileEdge(project_id=1, src_path="B", dst_path="C", kind="import"))
        session.commit()

    impacted, truncated = task_service._impact(1, "C", max_nodes=1, max_depth=None)
    assert impacted == ["B"]
    assert truncated is True

    impacted, truncated = task_service._impact(1, "C", max_nodes=None, max_depth=1)
    assert impacted == ["B"]
    assert truncated is True
