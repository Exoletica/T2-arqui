import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DB_PATH = ROOT / "visits.db"
LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    short_url TEXT NOT NULL,
    long_url TEXT NOT NULL
);
"""


def log_db_path():
    path = Path(os.environ.get("LOG_DB_PATH", DEFAULT_LOG_DB_PATH)).resolve()
    shortener = Path(os.environ.get("DB_PATH", ROOT / "url_shortener.db")).resolve()
    if path == shortener or (path.exists() and shortener.exists() and path.samefile(shortener)):
        raise ValueError("LOG_DB_PATH debe ser distinto de DB_PATH")
    return path


@contextmanager
def log_connection():
    conn = sqlite3.connect(log_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_log_db():
    with log_connection() as conn:
        conn.executescript(LOG_SCHEMA)
