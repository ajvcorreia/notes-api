from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import settings

_DB_PATH = Path(settings.stats_db_path)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                duration_ms REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp)")


def record_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO requests (timestamp, method, path, status_code, duration_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), method, path, status_code, duration_ms),
        )


def get_summary(days: int = 14, recent_limit: int = 50, exclude_health: bool = True) -> dict:
    since = time.time() - days * 86400
    health_filter = "WHERE path != '/health'" if exclude_health else ""
    health_and = "AND path != '/health'" if exclude_health else ""
    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM requests {health_filter}").fetchone()["c"]
        errors = conn.execute(
            f"SELECT COUNT(*) AS c FROM requests WHERE status_code >= 400 {health_and}"
        ).fetchone()["c"]
        avg_ms = conn.execute(
            f"SELECT AVG(duration_ms) AS a FROM requests {health_filter}"
        ).fetchone()["a"] or 0.0
        today_start = time.time() - (time.time() % 86400)
        today_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM requests WHERE timestamp >= ? {health_and}", (today_start,)
        ).fetchone()["c"]

        by_endpoint = conn.execute(
            f"""
            SELECT method, path, COUNT(*) AS count, AVG(duration_ms) AS avg_ms,
                   SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS errors
            FROM requests
            {health_filter}
            GROUP BY method, path
            ORDER BY count DESC
            LIMIT 8
            """
        ).fetchall()

        by_status = conn.execute(
            f"SELECT status_code, COUNT(*) AS count FROM requests {health_filter} "
            "GROUP BY status_code ORDER BY status_code"
        ).fetchall()

        by_day = conn.execute(
            f"""
            SELECT date(timestamp, 'unixepoch') AS day, COUNT(*) AS count
            FROM requests
            WHERE timestamp >= ? {health_and}
            GROUP BY day
            ORDER BY day ASC
            """,
            (since,),
        ).fetchall()

        recent = conn.execute(
            f"SELECT timestamp, method, path, status_code, duration_ms FROM requests "
            f"{health_filter} ORDER BY id DESC LIMIT ?",
            (recent_limit,),
        ).fetchall()

    return {
        "total_requests": total,
        "error_count": errors,
        "avg_duration_ms": round(avg_ms, 2),
        "today_count": today_count,
        "by_endpoint": [dict(r) for r in by_endpoint],
        "by_status": [dict(r) for r in by_status],
        "by_day": [dict(r) for r in by_day],
        "recent": [dict(r) for r in recent],
    }
