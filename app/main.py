import logging
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator

from app import grpc_client
from app.base62 import encode
from app.db import connection, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class ShortenRequest(BaseModel):
    long_url: str

    @field_validator("long_url")
    @classmethod
    def validate_long_url(cls, value):
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("long_url debe ser una URL válida http/https")
        return value


class ShortenResponse(BaseModel):
    short_url: str
    hash: str


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(
    title="Acortador de URLs - Arquitectura 1",
    description="Acortador con Base62, SQLite y registro de visitas vía gRPC.",
    version="1.0.0",
    lifespan=lifespan,
)


def _base_url(request: Request):
    return str(request.base_url).rstrip("/")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/shorten", response_model=ShortenResponse, status_code=201)
def shorten(payload: ShortenRequest, request: Request):
    placeholder = f"tmp-{uuid.uuid4().hex}"

    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO urls (hash, long_url) VALUES (?, ?)",
            (placeholder, payload.long_url),
        )
        url_id = cursor.lastrowid
        short_hash = encode(url_id)
        conn.execute(
            "UPDATE urls SET hash = ? WHERE id = ?",
            (short_hash, url_id),
        )

    return ShortenResponse(
        short_url=f"{_base_url(request)}/{short_hash}",
        hash=short_hash,
    )


@app.get("/{short_hash}")
def redirect(short_hash: str, request: Request):
    with connection() as conn:
        row = conn.execute(
            "SELECT hash, long_url FROM urls WHERE hash = ?",
            (short_hash,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="URL no encontrada")

    short_url = f"{_base_url(request)}/{row['hash']}"
    grpc_client.log_visit(short_url, row["long_url"])

    return RedirectResponse(url=row["long_url"], status_code=302)
