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
    monkeypatch.setenv("LOG_DB_PATH", str(db_file))
    from logs_service.db import init_log_db, log_connection
    init_log_db()

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

    with log_connection() as conn:
        row = conn.execute("SELECT * FROM visits").fetchone()

    assert row["timestamp"] == 1700000000
    assert row["short_url"] == "http://localhost:8000/XYVz5"
    assert row["long_url"] == "https://example.com"


def test_separate_schemas_and_log_restart(tmp_path, monkeypatch):
    from logs_service.db import init_log_db, log_connection
    monkeypatch.setenv("DB_PATH", str(tmp_path / "urls.db"))
    monkeypatch.setenv("LOG_DB_PATH", str(tmp_path / "visits.db"))
    init_db()
    init_log_db()
    with connection() as conn:
        conn.execute("INSERT INTO urls (hash, long_url) VALUES ('eRgfR', 'https://example.com')")
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='visits'").fetchone()
    from logs_service.server import LogService
    import logs_pb2
    for _ in range(3):
        LogService().LogVisit(logs_pb2.LogRequest(timestamp=1700000000,
            short_url="https://localhost/eRgfR", long_url="https://example.com"), None)
    init_db()
    init_log_db()
    with log_connection() as conn:
        rows = conn.execute("SELECT * FROM visits").fetchall()
        assert len(rows) == 3
        assert len({r["id"] for r in rows}) == 3
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='urls'").fetchone()
    with connection() as conn:
        assert conn.execute("SELECT hash FROM urls").fetchone()[0] == "eRgfR"
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='visits'").fetchone()


def test_log_initializes_without_shortener(tmp_path, monkeypatch):
    from logs_service.db import init_log_db
    shortener = tmp_path / "not-created.db"
    monkeypatch.setenv("DB_PATH", str(shortener))
    monkeypatch.setenv("LOG_DB_PATH", str(tmp_path / "visits.db"))
    init_log_db()
    assert not shortener.exists()


def test_log_rejects_same_database(tmp_path, monkeypatch):
    import pytest
    from logs_service.db import init_log_db
    path = str(tmp_path / "same.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("LOG_DB_PATH", path)
    with pytest.raises(ValueError, match="distinto"):
        init_log_db()


def test_verified_reset_preserves_legacy_backup(tmp_path, monkeypatch):
    import sqlite3
    from scripts import reset_dev_db
    from logs_service.db import log_connection
    shortener, logs = tmp_path / "urls.db", tmp_path / "visits.db"
    monkeypatch.setenv("DB_PATH", str(shortener))
    monkeypatch.setenv("LOG_DB_PATH", str(logs))
    monkeypatch.setattr(reset_dev_db, "ROOT", tmp_path)
    # Esta prueba comprueba respaldo/reinicialización. La guarda de archivos
    # abiertos se comprueba aparte con el proceso real de pytest.
    monkeypatch.setattr(reset_dev_db, "ensure_idle", lambda paths: None)
    init_db()
    with connection() as conn:
        conn.execute("INSERT INTO urls (hash, long_url) VALUES ('eRgfR', 'https://example.com')")
        conn.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, timestamp INTEGER, short_url TEXT, long_url TEXT)")
        conn.execute("INSERT INTO visits VALUES (1, 1700000000, 'https://localhost/eRgfR', 'https://example.com')")
    backup = reset_dev_db.reset()
    with sqlite3.connect(backup / "shortener.db") as conn:
        assert conn.execute("SELECT hash FROM urls").fetchone()[0] == "eRgfR"
        assert conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 1
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0] == 0
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='visits'").fetchone()
        assert conn.execute("INSERT INTO urls (hash, long_url) VALUES ('eRgfR', 'https://example.com')").lastrowid == START_ID
    with log_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0


def test_idle_guard_detects_open_database(tmp_path):
    import sqlite3
    import subprocess
    from scripts.reset_dev_db import ROOT
    path = tmp_path / "open.db"
    with sqlite3.connect(path):
        result = subprocess.run([sys.executable, "-c",
            "from pathlib import Path; from scripts.reset_dev_db import ensure_idle; "
            "import sys; ensure_idle([Path(sys.argv[1])])", str(path)],
            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Base en uso" in result.stderr
