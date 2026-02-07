#!/usr/bin/env sh
set -e

python - <<'PY'
import os
import time

import psycopg

db_url = os.getenv("STUBGRAPH_DATABASE_URL") or os.getenv("DATABASE_URL")
if not db_url:
    raise SystemExit("STUBGRAPH_DATABASE_URL is not set")

deadline = time.time() + 30
last_error = None
while time.time() < deadline:
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        last_error = None
        break
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        time.sleep(1)
if last_error is not None:
    raise SystemExit(f"Database is not ready: {last_error}")
PY

exec "$@"
