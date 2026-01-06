#backend/app/db.py
from __future__ import annotations

from sqlmodel import SQLModel, create_engine, Session
from pathlib import Path
from .config import settings
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import event

DB_PATH = Path(settings.db_dir) / "code_surgeon.sqlite3"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)

@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
    try:
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=5000;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.close()
    except Exception:
        pass

def _dedupe_sqlite(conn) -> None:
    conn.exec_driver_sql("""
        DELETE FROM filenode
        WHERE id NOT IN (
            SELECT MAX(id) FROM filenode GROUP BY project_id, path
        );
    """)

    conn.exec_driver_sql("""
        DELETE FROM modulecontract
        WHERE id NOT IN (
            SELECT MAX(id) FROM modulecontract GROUP BY project_id, path
        );
    """)

    conn.exec_driver_sql("""
        DELETE FROM fileedge
        WHERE id NOT IN (
            SELECT MAX(id) FROM fileedge GROUP BY project_id, src_path, dst_path, kind
        );
    """)

def _ensure_unique_indexes_sqlite(conn) -> None:
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_filenode_project_path ON filenode (project_id, path);"
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_modulecontract_project_path ON modulecontract (project_id, path);"
    )
    conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_fileedge_project_src_dst_kind ON fileedge (project_id, src_path, dst_path, kind);"
    )

def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    try:
        with engine.begin() as conn:
            try:
                conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
                conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")
                conn.exec_driver_sql("PRAGMA busy_timeout=5000;")
                conn.exec_driver_sql("PRAGMA foreign_keys=ON;")
            except Exception:
                pass
            _dedupe_sqlite(conn)
            _ensure_unique_indexes_sqlite(conn)
    except SQLAlchemyError as e:
        raise RuntimeError(f"DB init failed while ensuring uniqueness: {e}") from e

def get_session() -> Session:
    return Session(engine)
