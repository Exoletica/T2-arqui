import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from litestar.testing import TestClient  # noqa: E402

from app import grpc_client  # noqa: E402
import base62  # noqa: E402
from app.db import START_ID, connection, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def logged_visits(monkeypatch):
    calls = []

    def fake_log_visit(short_url, long_url):
        calls.append((short_url, long_url))
        return True

    monkeypatch.setattr(grpc_client, "log_visit", fake_log_visit)
    return calls


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client


def test_shorten_returns_hash_and_short_url(client):
    response = client.post("/shorten", json={"long_url": "https://example.com/ruta"})

    assert response.status_code == 201
    data = response.json()
    assert data["hash"]
    assert base62.decode(data["hash"]) >= START_ID
    assert data["short_url"].endswith(data["hash"])


def test_redirect_returns_302_and_logs_visit(client, logged_visits):
    created = client.post(
        "/shorten", json={"long_url": "https://example.com/destino"}
    ).json()

    response = client.get(f"/{created['hash']}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["location"] == "https://example.com/destino"
    assert logged_visits == [
        (created["short_url"], "https://example.com/destino")
    ]


def test_unknown_hash_returns_404(client):
    response = client.get("/ZZZZZ")

    assert response.status_code == 404
    assert response.json() == {"detail": "URL no encontrada"}


@pytest.mark.parametrize(
    "bad_url",
    ["no-es-url", "ftp://example.com/archivo", "https://", ""],
)
def test_invalid_url_returns_422(client, bad_url):
    response = client.post("/shorten", json={"long_url": bad_url})

    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["loc"] == ["body", "long_url"]
    assert error["type"] == "value_error"
    assert error["msg"] == "Value error, long_url debe ser una URL válida http/https"
    assert error["input"] == bad_url
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 0


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_valid_urls_are_trimmed_and_preserved(client, logged_visits, scheme):
    url = f"{scheme}://example.com/ruta?q=uno%20dos&x=1#seccion"
    response = client.post("/shorten", json={"long_url": f"  {url}  "})
    assert response.status_code == 201
    created = response.json()
    assert set(created) == {"short_url", "hash"}
    assert created["hash"] == "eRgfR"
    assert created["short_url"] == f"{str(client.base_url).rstrip('/')}/eRgfR"
    redirect = client.get("/eRgfR", follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers["location"] == url
    assert logged_visits == [(created["short_url"], url)]


@pytest.mark.parametrize("payload", [{}, {"long_url": None}, {"long_url": 123}, []])
def test_invalid_body_returns_422(client, payload):
    response = client.post("/shorten", json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.parametrize("body", [b"", b"null", b'{"long_url":'])
def test_missing_or_malformed_body_returns_422(client, body):
    response = client.post("/shorten", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert error["type"] == ("missing" if body in (b"", b"null") else "json_invalid")
    assert error["loc"][0] == "body"


def test_startup_preserves_existing_data_and_sequence(tmp_path, monkeypatch, logged_visits):
    db_file = tmp_path / "existing.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    init_db()
    from logs_service.db import init_log_db, log_connection
    monkeypatch.setenv("LOG_DB_PATH", str(tmp_path / "visits.db"))
    init_log_db()
    with connection() as conn:
        conn.execute(
            "INSERT INTO urls (hash, long_url) VALUES (?, ?)",
            (base62.encode(START_ID), "https://example.com/existing"),
        )
    with log_connection() as conn:
        conn.execute(
            "INSERT INTO visits (timestamp, short_url, long_url) VALUES (?, ?, ?)",
            (1700000000, "http://localhost/eRgfR", "https://example.com/existing"),
        )
    for expected_id in (START_ID + 1, START_ID + 2):
        with TestClient(app) as client:
            response = client.get("/eRgfR", follow_redirects=False)
            assert response.status_code == 302
            assert response.headers["location"] == "https://example.com/existing"
            created = client.post("/shorten", json={"long_url": "https://example.com/new"})
            assert created.status_code == 201
            assert created.json()["hash"] == base62.encode(expected_id)
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 3
    with log_connection() as conn:
        assert conn.execute("SELECT timestamp FROM visits").fetchone()[0] == 1700000000


def test_redirect_survives_grpc_failure(client, monkeypatch):
    import grpc
    from unittest.mock import Mock

    stub = Mock()
    stub.LogVisit.side_effect = grpc.RpcError("servicio no disponible")
    monkeypatch.setattr(grpc_client.logs_pb2_grpc, "LogServiceStub", Mock(return_value=stub))
    created = client.post("/shorten", json={"long_url": "https://example.com/offline"}).json()
    response = client.get(f"/{created['hash']}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/offline"
    stub.LogVisit.assert_called_once()


def test_litestar_and_openapi(client):
    from litestar import Litestar

    assert isinstance(app, Litestar)
    assert client.get("/schema/swagger").status_code == 200
    response = client.get("/schema/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "201" in schema["paths"]["/shorten"]["post"]["responses"]
    assert "302" in schema["paths"]["/{short_hash}"]["get"]["responses"]
