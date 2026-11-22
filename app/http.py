"""Contrato HTTP compartido por ambas arquitecturas, sin dependencias gRPC."""
import json
from urllib.parse import urlparse

from litestar import Request, Response
from litestar.exceptions import HTTPException, SerializationException
from pydantic import BaseModel, ValidationError, field_validator

from app.db import init_db


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
    return Response(content={"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

