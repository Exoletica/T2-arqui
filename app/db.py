import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "url_shortener.db")

START_ID = 597652313

SCHEMA = """
CREATE TABLE IF NOT EXISTS urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    long_url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

"""


def db_path():
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def get_connection(path=None):
    conn = sqlite3.connect(path or db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def connection(path=None):
    conn = get_connection(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path=None):
    with connection(path) as conn:
        conn.executescript(SCHEMA)
        row = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'urls'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('urls', ?)",
                (START_ID - 1,),
            )
        elif row["seq"] < START_ID - 1:
            conn.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = 'urls'",
                (START_ID - 1,),
            )
