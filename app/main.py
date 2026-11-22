import logging

from litestar import Litestar, Request, get, post
from litestar.exceptions import HTTPException, ValidationException
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import SwaggerRenderPlugin
from litestar.params import FromPath, JSONBody
from litestar.response import Redirect

from app import grpc_client
from app.http import (
    ShortenRequest, ShortenResponse, cache_request_body, http_exception_handler,
    on_startup, validation_exception_handler,
)
from app.urls import create_url, find_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _base_url(request: Request):
    return str(request.base_url).rstrip("/")


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@post("/shorten", status_code=201, sync_to_thread=True, before_request=cache_request_body)
def shorten(data: JSONBody[ShortenRequest], request: Request) -> ShortenResponse:
    short_hash = create_url(data.long_url)

    return ShortenResponse(
        short_url=f"{_base_url(request)}/{short_hash}",
        hash=short_hash,
    )


@get("/{short_hash:str}", status_code=302, sync_to_thread=True)
def redirect(short_hash: FromPath[str], request: Request) -> Redirect:
    row = find_url(short_hash)

    if row is None:
        raise HTTPException(status_code=404, detail="URL no encontrada")

    short_url = f"{_base_url(request)}/{row['hash']}"
    grpc_client.log_visit(short_url, row["long_url"])

    return Redirect(path=row["long_url"], status_code=302, headers={"Cache-Control":"no-store"},)


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
