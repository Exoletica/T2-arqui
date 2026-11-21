import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import START_ID, connection, init_db  # noqa: E402


def test_first_generated_id_is_start_id(tmp_path):
    db_file = tmp_path / "fresh.db"
    init_db(str(db_file))

    with connection(str(db_file)) as conn:
        cursor = conn.execute(
            "INSERT INTO urls (hash, long_url) VALUES (?, ?)",
            ("tmp", "https://example.com"),
        )
        assert cursor.lastrowid == START_ID


def test_grpc_service_stores_visit(tmp_path, monkeypatch):
    db_file = tmp_path / "grpc.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    init_db()

    from logs_service.server import LogService
    import logs_pb2

    response = LogService().LogVisit(
        logs_pb2.LogRequest(
            timestamp=1700000000,
            short_url="http://localhost:8000/XYVz5",
            long_url="https://example.com",
        ),
        None,
    )

    assert response.success is True

    with connection() as conn:
        row = conn.execute("SELECT * FROM visits").fetchone()

    assert row["timestamp"] == 1700000000
    assert row["short_url"] == "http://localhost:8000/XYVz5"
    assert row["long_url"] == "https://example.com"
