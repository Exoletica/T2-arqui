import os

from litestar import Litestar, Request, get, post
from litestar.config.response_cache import ResponseCacheConfig
from litestar.exceptions import HTTPException, ValidationException
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import SwaggerRenderPlugin
from litestar.params import FromPath, JSONBody
from litestar.response import Redirect
from litestar.stores.memory import MemoryStore

from app.http import (
    ShortenRequest, ShortenResponse, cache_request_body, http_exception_handler,
    on_startup, validation_exception_handler,
)
from app.urls import create_url, find_url


def positive_setting(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} debe ser un entero positivo")
    return value


def redirect_cache_key(request: Request) -> str:
    return f"a2:redirect:{request.path_params['short_hash']}"


def cache_only_redirects(scope, status_code: int) -> bool:
    return scope["method"] == "GET" and status_code == 301


def create_app() -> Litestar:
    """Cada instancia tiene sus propios almacenes; configuración leída al crearla."""
    limit = positive_setting("A2_RATE_LIMIT_PER_MINUTE", 60)
    ttl = positive_setting("A2_CACHE_TTL_SECONDS", 300)
    rate_limit = RateLimitConfig(
        rate_limit=("minute", limit),
        exclude=[r"^/health/?$", r"^/schema(?:/|$)"],
        store="a2_rate_limit",
    )

    @get("/health", sync_to_thread=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @post("/shorten", status_code=201, sync_to_thread=True, before_request=cache_request_body)
    def shorten(data: JSONBody[ShortenRequest], request: Request) -> ShortenResponse:
        short_hash = create_url(data.long_url)
        return ShortenResponse(
            short_url=f"{str(request.base_url).rstrip('/')}/{short_hash}",
            hash=short_hash,
        )

    @get("/{short_hash:str}", status_code=301, cache=True, sync_to_thread=True)
    def redirect(short_hash: FromPath[str]) -> Redirect:
        row = find_url(short_hash)
        if row is None:
            raise HTTPException(status_code=404, detail="URL no encontrada")
        return Redirect(path=row["long_url"], status_code=301)

    return Litestar(
        route_handlers=[health, shorten, redirect],
        on_startup=[on_startup],
        middleware=[rate_limit.middleware],
        stores={"a2_rate_limit": MemoryStore(), "a2_redirects": MemoryStore()},
        response_cache_config=ResponseCacheConfig(
            default_expiration=ttl,
            key_builder=redirect_cache_key,
            store="a2_redirects",
            cache_response_filter=cache_only_redirects,
        ),
        exception_handlers={
            ValidationException: validation_exception_handler,
            HTTPException: http_exception_handler,
        },
        openapi_config=OpenAPIConfig(
            title="Acortador de URLs - Arquitectura 2",
            version="1.0.0",
            render_plugins=[SwaggerRenderPlugin()],
        ),
    )


app = create_app()
