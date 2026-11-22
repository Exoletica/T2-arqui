from contextlib import ExitStack, contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from litestar.testing import TestClient

from app import grpc_client, urls
import base62
from app.db import START_ID, connection
from app.main import app as app1
from arquitectura2.main import create_app


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "isolated.db"))
    monkeypatch.delenv("A2_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("A2_CACHE_TTL_SECONDS", raising=False)
    # Cualquier llamada gRPC de A2 hace fallar la prueba.
    monkeypatch.setattr(grpc_client, "log_visit", Mock(side_effect=AssertionError("A2 llamó gRPC")))
    with ExitStack() as stack:
        def make(app=None, base_url="https://localhost.local:8444"):
            client = stack.enter_context(TestClient(
                app if app is not None else create_app(),
                base_url=base_url,
            ))
            client.follow_redirects = False
            return client
        yield make


@pytest.fixture
def selects(monkeypatch):
    statements = []
    original = urls.connection

    @contextmanager
    def traced_connection():
        with original() as conn:
            conn.set_trace_callback(lambda sql: statements.append(sql)
                                    if sql.startswith("SELECT hash, long_url FROM urls") else None)
            yield conn

    monkeypatch.setattr(urls, "connection", traced_connection)
    return statements


@pytest.fixture
def advance_clock(monkeypatch):
    import litestar.stores.base as store_base
    import litestar.middleware.rate_limit as rate_module

    offset = [0]
    original_time = rate_module.time

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=offset[0])

    monkeypatch.setattr(store_base, "datetime", Clock)
    monkeypatch.setattr(rate_module, "time", lambda: original_time() + offset[0])

    def advance(seconds):
        offset[0] += seconds
    return advance


def shorten(client, url="https://example.com/recurso"):
    response = client.post("/shorten", json={"long_url": url})
    assert response.status_code == 201
    return response.json()


def test_creation_sequence_https_and_no_post_cache(clients):
    client = clients()
    for index in range(3):
        data = shorten(client)
        assert data == {"hash": base62.encode(START_ID + index),
                        "short_url": f"https://localhost.local:8444/{base62.encode(START_ID + index)}"}
        assert base62.decode(data["hash"]) == START_ID + index
    with connection() as conn:
        assert [r["id"] for r in conn.execute("SELECT id FROM urls ORDER BY id")] == list(range(START_ID, START_ID + 3))


def test_both_apps_use_library_and_preserve_legacy_hash(clients, monkeypatch):
    one, two = clients(app1), clients()
    monkeypatch.setattr(grpc_client, "log_visit", Mock(return_value=True))
    # Hash literal obtenido de la implementación anterior, almacenado antes del POST.
    with connection() as conn:
        conn.execute("INSERT INTO urls (hash, long_url) VALUES (?, ?)",
                     ("eRgfR", "https://example.com/legacy"))
    encoder = Mock(wraps=base62.encode)
    monkeypatch.setattr(base62, "encode", encoder)
    for client, status in ((one, 302), (two, 301)):
        response = client.get("/eRgfR")
        assert response.status_code == status
        assert response.headers["location"] == "https://example.com/legacy"
        shorten(client)
    assert [call.args for call in encoder.call_args_list] == [(START_ID + 1,), (START_ID + 2,)]


@pytest.mark.parametrize("url", ["http://example.com/ruta?q=1#x", "https://example.com/ruta"])
def test_permanent_redirect_location_and_no_grpc(clients, url):
    client = clients()
    created = shorten(client, f"  {url}  ")
    for _ in range(2):
        response = client.get(f"/{created['hash']}")
        assert response.status_code == 301
        assert response.headers["location"] == url
    grpc_client.log_visit.assert_not_called()
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'visits'").fetchone()[0] == 0


def test_cache_reduces_sqlite_queries_and_expires(clients, selects, advance_clock, monkeypatch):
    monkeypatch.setenv("A2_CACHE_TTL_SECONDS", "10")
    client = clients()
    data = shorten(client)
    first = client.get(f"/{data['hash']}")
    assert len(selects) == 1
    advance_clock(9)
    second = client.get(f"/{data['hash']}")
    assert len(selects) == 1, "El segundo GET no debe consultar SQLite"
    advance_clock(2)
    third = client.get(f"/{data['hash']}")
    assert len(selects) == 2, "Tras vencer el TTL debe consultar SQLite"
    for response in (first, second, third):
        assert response.status_code == 301
        assert response.headers["location"] == "https://example.com/recurso"


def test_cache_key_distinguishes_hashes(clients, selects):
    client = clients()
    for index in range(2):
        url = f"https://example.com/{index}"
        data = shorten(client, url)
        for _ in range(2):
            response = client.get(f"/{data['hash']}")
            assert response.status_code == 301
            assert response.headers["location"] == url
    assert len(selects) == 2


def test_not_found_not_cached(clients, selects):
    client = clients()
    for _ in range(2):
        response = client.get("/eRgfR")
        assert response.status_code == 404
        assert response.json() == {"detail": "URL no encontrada"}
    assert len(selects) == 2
    shorten(client)
    assert client.get("/eRgfR").status_code == 301
    assert len(selects) == 3


@pytest.mark.parametrize("payload", [
    {"long_url": "no-es-url"}, {"long_url": "ftp://example.com"},
    {"long_url": "https://"}, {"long_url": ""}, {},
    {"long_url": None}, {"long_url": 123}, [],
])
def test_validation_matches_architecture1(clients, payload):
    one, two = clients(app1), clients()
    first = one.post("/shorten", json=payload)
    second = two.post("/shorten", json=payload)
    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 0


@pytest.mark.parametrize("body", [b"", b"null", b'{"long_url":'])
def test_invalid_json_matches_architecture1(clients, body):
    responses = [client.post("/shorten", content=body, headers={"Content-Type": "application/json"})
                 for client in (clients(app1), clients())]
    assert [r.status_code for r in responses] == [422, 422]
    assert responses[0].json() == responses[1].json()


def test_rate_limit_covers_post_and_cached_get_and_resets(clients, monkeypatch, selects, advance_clock):
    monkeypatch.setenv("A2_RATE_LIMIT_PER_MINUTE", "3")
    client = clients()
    shorten(client)  # 1: POST
    assert client.get("/eRgfR").status_code == 301  # 2: SQLite
    response = client.get("/eRgfR")  # 3: cache
    assert response.status_code == 301
    assert response.headers["ratelimit-remaining"] == "0"
    assert len(selects) == 1
    for path in ("/eRgfR", "/unknown"):
        response = client.get(path, headers={"X-Forwarded-For": "203.0.113.99"})
        assert response.status_code == 429  # XFF no evade el contador
        assert response.headers["ratelimit-limit"] == "3"
    assert client.post("/shorten", json={"long_url": "https://example.com"}).status_code == 429
    for path in ("/health", "/schema/swagger", "/schema/openapi.json"):
        assert client.get(path).status_code == 200
    assert len(selects) == 1
    advance_clock(61)
    assert client.get("/eRgfR").status_code == 301  # 429 no reemplazó la caché
    assert len(selects) == 1


def test_limit_default_is_60_and_identity_is_per_client(clients, monkeypatch):
    client = clients()
    for _ in range(60):
        response = client.get("/missing")
        assert response.status_code == 404
        assert response.headers["ratelimit-limit"] == "60"
    assert client.get("/missing").status_code == 429
    # Identidad de transporte distinta, sin recurrir a cabeceras suministradas por el usuario.
    from litestar.testing.transport import TestClientTransport
    original = TestClientTransport.parse_request

    def other_address(self, request):
        scope = original(self, request)
        scope["client"] = ("192.0.2.2", 50000)
        return scope

    monkeypatch.setattr(TestClientTransport, "parse_request", other_address)
    assert client.get("/missing").status_code == 404


def test_apps_independent_with_shared_persistence(clients, monkeypatch, selects):
    monkeypatch.setenv("A2_RATE_LIMIT_PER_MINUTE", "2")
    visits = Mock(return_value=True)
    monkeypatch.setattr(grpc_client, "log_visit", visits)
    one = clients(app1, "https://localhost.local:8443")
    two = clients()
    first, second = shorten(one), shorten(two)
    assert first["short_url"] == "https://localhost.local:8443/eRgfR"
    assert second["hash"] == base62.encode(START_ID + 1)
    assert two.get(f"/{first['hash']}").status_code == 301
    assert two.get(f"/{first['hash']}").status_code == 429
    for _ in range(4):
        response = one.get(f"/{second['hash']}")
        assert response.status_code == 302
        assert response.headers["location"] == "https://example.com/recurso"
    assert visits.call_count == 4
    assert len(selects) == 5  # A1 no comparte caché con A2
    new_instance = clients()
    assert new_instance.get(f"/{first['hash']}").status_code == 301
    assert len(selects) == 6  # almacenes independientes entre instancias


def test_default_ttl_and_openapi(clients):
    client = clients()
    assert client.app.response_cache_config.default_expiration == 300
    schema = client.get("/schema/openapi.json").json()
    assert "301" in schema["paths"]["/{short_hash}"]["get"]["responses"]
    assert "201" in schema["paths"]["/shorten"]["post"]["responses"]


def test_concurrent_creation_across_both_apps(clients):
    one, two = clients(app1), clients()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda n: shorten(one if n % 2 else two), range(16)))
    ids = sorted(base62.decode(data["hash"]) for data in results)
    assert ids == list(range(START_ID, START_ID + 16))


def test_server_error_is_not_cached(clients, monkeypatch):
    from litestar.exceptions import HTTPException
    import arquitectura2.main as a2

    client = clients()
    shorten(client)
    lookup = Mock(side_effect=[HTTPException(status_code=503, detail="temporal"),
                               {"long_url": "https://example.com/recurso"}])
    monkeypatch.setattr(a2, "find_url", lookup)
    assert client.get("/eRgfR").status_code == 503
    response = client.get("/eRgfR")
    assert response.status_code == 301
    assert response.headers["location"] == "https://example.com/recurso"
    assert lookup.call_count == 2


@pytest.mark.parametrize("name", ["A2_CACHE_TTL_SECONDS", "A2_RATE_LIMIT_PER_MINUTE"])
@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_invalid_configuration_fails_explicitly(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        create_app()
