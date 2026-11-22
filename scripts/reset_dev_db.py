"""Reinicialización de desarrollo Linux, sin migración y con respaldo verificado."""
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from app.db import db_path, init_db
from logs_service.db import init_log_db, log_db_path

ROOT = Path(__file__).resolve().parent.parent


def ensure_idle(paths):
    targets = {str(p.resolve()) + suffix for p in paths for suffix in ("", "-wal", "-shm")}
    processes = sorted(Path("/proc").iterdir(), key=lambda p: p.name != str(os.getppid()))
    for process in processes:
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        args = ""
        try:
            if process.stat().st_uid != os.getuid():
                continue
            if any(line.startswith("State:") and "Z" in line
                   for line in (process / "status").read_text().splitlines()):
                continue  # Un proceso zombi ya no conserva descriptores.
            args = (process / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if ("uvicorn" in args and any(s in args for s in ("app.main", "arquitectura2.main"))) or "-m logs_service.server" in args:
                raise RuntimeError(f"Detener primero el servicio PID {process.name}: {args}")
            for fd in (process / "fd").iterdir():
                if os.readlink(fd).removesuffix(" (deleted)") in targets:
                    raise RuntimeError(f"Base en uso por PID {process.name}; no se reinicializó")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            # systemd --user y otros procesos no depurables pueden ocultar fd.
            # No ignorar esa restricción en procesos que pueden ejecutar estos
            # servicios o clientes SQLite; sus argumentos ya fueron comprobados.
            if not args or any(name in args for name in ("python", "uvicorn", "sqlite", "grpc")):
                raise RuntimeError(f"No se pudo comprobar el proceso {process.name}; no se reinicializó") from exc


def snapshot(source, destination):
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as old:
        with sqlite3.connect(destination) as backup:
            old.backup(backup)
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert list(old.iterdump()) == list(backup.iterdump()), "Respaldo diferente del original"
            names = [r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {name: old.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                    for name in names}


def reset():
    paths = [Path(db_path()).resolve(), log_db_path()]
    ensure_idle(paths)
    backup_root = ROOT / "db_backups"
    backup_root.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="reset-", dir=backup_root))
    report = {}
    for label, path in zip(("shortener", "log"), paths):
        if path.exists():
            report[label] = {"source": str(path), "counts": snapshot(path, directory / f"{label}.db")}
        else:
            report[label] = {"source": str(path), "counts": {}, "absent": True}
    (directory / "manifest.json").write_text(json.dumps(report, indent=2))
    # Segunda comprobación inmediatamente antes del reemplazo. Mantener los
    # servicios detenidos durante todo el comando; no iniciar procesos concurrentes.
    ensure_idle(paths)
    for label, path in zip(("shortener", "log"), paths):
        for suffix in ("", "-wal", "-shm"):
            source = Path(str(path) + suffix)
            if source.exists():
                shutil.move(str(source), directory / f"original-{label}.db{suffix}")
    init_db()
    init_log_db()
    print(f"Respaldo verificado y originales conservados: {directory}")
    print(json.dumps(report, indent=2))
    print(f"Creadas desde cero: {paths[0]} (urls), {paths[1]} (visits). Migrados: 0.")
    return directory


if __name__ == "__main__":
    reset()
