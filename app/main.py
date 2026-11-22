import json
import logging
import uuid
from urllib.parse import urlparse

from litestar import Litestar, Request, Response, get, post
from litestar.exceptions import HTTPException, SerializationException, ValidationException
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import SwaggerRenderPlugin
from litestar.params import FromPath, JSONBody
from litestar.response import Redirect
from pydantic import BaseModel, ValidationError, field_validator

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


def on_startup() -> None:
    init_db()


async def cache_request_body(request: Request) -> None:
    # Los manejadores de excepciones de Litestar son síncronos.
    request.state.raw_body = await request.body()


def validation_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Conserva HTTP 422 y el formato de errores de validación anterior."""
    body = request.state.raw_body
    if not body or body.strip() == b"null":
        return Response(
            content={"detail": [{"type": "missing", "loc": ["body"], "msg": "Field required", "input": None}]},
            status_code=422,
        )
    try:
        json.loads(body)
    except json.JSONDecodeError as error:
        return Response(
            content={"detail": [{
                "type": "json_invalid", "loc": ["body", error.pos],
                "msg": "JSON decode error", "input": {}, "ctx": {"error": error.msg},
            }]},
            status_code=422,
        )
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, ValidationError):
            errors = cause.errors(include_url=False)
            for error in errors:
                error["loc"] = ["body", *error["loc"]]
                if "ctx" in error:
                    error["ctx"] = {
                        key: str(value) if isinstance(value, Exception) else value
                        for key, value in error["ctx"].items()
                    }
            return Response(content={"detail": errors}, status_code=422)
        cause = cause.__cause__
    return Response(
        content={"detail": [{"type": "value_error", "loc": ["body"], "msg": exc.detail}]},
        status_code=422,
    )


def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    if isinstance(exc.__cause__, SerializationException):
        return validation_exception_handler(request, exc)
    return Response(content={"detail": exc.detail}, status_code=exc.status_code)


def _base_url(request: Request):
    return str(request.base_url).rstrip("/")


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@post("/shorten", status_code=201, sync_to_thread=True, before_request=cache_request_body)
def shorten(data: JSONBody[ShortenRequest], request: Request) -> ShortenResponse:
    placeholder = f"tmp-{uuid.uuid4().hex}"

    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO urls (hash, long_url) VALUES (?, ?)",
            (placeholder, data.long_url),
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


@get("/{short_hash:str}", status_code=302, sync_to_thread=True)
def redirect(short_hash: FromPath[str], request: Request) -> Redirect:
    with connection() as conn:
        row = conn.execute(
            "SELECT hash, long_url FROM urls WHERE hash = ?",
            (short_hash,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="URL no encontrada")

    short_url = f"{_base_url(request)}/{row['hash']}"
    grpc_client.log_visit(short_url, row["long_url"])

    return Redirect(path=row["long_url"], status_code=302)


app = Litestar(
    route_handlers=[health, shorten, redirect],
    on_startup=[on_startup],
    exception_handlers={
        ValidationException: validation_exception_handler,
        HTTPException: http_exception_handler,
    },
    openapi_config=OpenAPIConfig(
        title="Acortador de URLs - Arquitectura 1",
        description="Acortador con Base62, SQLite y registro de visitas vía gRPC.",
        version="1.0.0",
        render_plugins=[SwaggerRenderPlugin()],
    ),
)
