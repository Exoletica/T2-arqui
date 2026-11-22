"""Operaciones SQLite y Base62 comunes; no dependen de HTTP ni de gRPC."""
import uuid

from app.base62 import encode
from app.db import connection


def create_url(long_url: str) -> str:
    placeholder = f"tmp-{uuid.uuid4().hex}"
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO urls (hash, long_url) VALUES (?, ?)",
            (placeholder, long_url),
        )
        url_id = cursor.lastrowid
        short_hash = encode(url_id)
        conn.execute("UPDATE urls SET hash = ? WHERE id = ?", (short_hash, url_id))
    return short_hash


def find_url(short_hash: str):
    with connection() as conn:
        return conn.execute(
            "SELECT hash, long_url FROM urls WHERE hash = ?", (short_hash,)
        ).fetchone()
