import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP_DIR = tempfile.mkdtemp(prefix="url-shortener-tests-")
os.environ["DB_PATH"] = os.path.join(_TMP_DIR, "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import grpc_client  # noqa: E402
from app.base62 import decode  # noqa: E402
from app.db import START_ID  # noqa: E402
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
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_shorten_returns_hash_and_short_url(client):
    response = client.post("/shorten", json={"long_url": "https://example.com/ruta"})

    assert response.status_code == 201
    data = response.json()
    assert data["hash"]
    assert decode(data["hash"]) >= START_ID
    assert data["short_url"].endswith(data["hash"])


def test_redirect_returns_302_and_logs_visit(client, logged_visits):
    created = client.post(
        "/shorten", json={"long_url": "https://example.com/destino"}
    ).json()

    response = client.get(f"/{created['hash']}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/destino"
    assert logged_visits == [
        (created["short_url"], "https://example.com/destino")
    ]


def test_unknown_hash_returns_404(client):
    response = client.get("/ZZZZZ")

    assert response.status_code == 404
    assert response.json()["detail"] == "URL no encontrada"


@pytest.mark.parametrize(
    "bad_url",
    ["no-es-url", "ftp://example.com/archivo", "https://", ""],
)
def test_invalid_url_returns_422(client, bad_url):
    response = client.post("/shorten", json={"long_url": bad_url})

    assert response.status_code == 422
