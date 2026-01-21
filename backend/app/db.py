#backend/app/db.py
from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import SQLModel, Session, create_engine

from .config import settings

DB_DIR = Path(settings.db_dir).expanduser()
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "cgraph.sqlite3"

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

def _ensure_fts_sqlite(conn) -> None:
    conn.exec_driver_sql("""
        CREATE VIRTUAL TABLE IF NOT EXISTS filetext_fts USING fts5(
            project_id UNINDEXED,
            path UNINDEXED,
            content,
            tokenize='unicode61'
        );
    """)

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

    try:
        conn.exec_driver_sql("""
            DELETE FROM filetext_fts
            WHERE rowid NOT IN (
                SELECT MAX(rowid) FROM filetext_fts GROUP BY project_id, path
            );
        """)
    except Exception:
        pass

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
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_fileedge_project_dst ON fileedge (project_id, dst_path);"
    )
    conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_fileedge_project_src ON fileedge (project_id, src_path);"
    )

def _ensure_analysisrun_columns_sqlite(conn) -> None:
    try:
        rows = conn.exec_driver_sql("PRAGMA table_info(analysisrun);").fetchall()
    except Exception:
        return
    existing = {row[1] for row in rows if isinstance(row, (tuple, list)) and len(row) > 1}
    desired = {
        "depth": "INTEGER",
        "dep_mode": "TEXT",
        "retrieval": "TEXT",
        "retrieval_settings_json": "TEXT",
        "apply_patch": "INTEGER",
        "applied_json": "TEXT",
    }
    for column, col_type in desired.items():
        if column in existing:
            continue
        try:
            conn.exec_driver_sql(f"ALTER TABLE analysisrun ADD COLUMN {column} {col_type};")
        except Exception:
            pass

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
            _ensure_fts_sqlite(conn)
            _dedupe_sqlite(conn)
            _ensure_unique_indexes_sqlite(conn)
            _ensure_analysisrun_columns_sqlite(conn)
    except SQLAlchemyError as e:
        raise RuntimeError(f"DB init failed while ensuring uniqueness: {e}") from e

def get_session() -> Session:
    return Session(engine)
