#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
UVICORN="$ROOT/.venv/bin/uvicorn"

if [[ ! -x "$PYTHON" || ! -x "$UVICORN" ]]; then
  echo "No se encontró .venv. Crea el entorno e instala requirements.txt." >&2
  exit 1
fi

VERIFY_DIR="$(mktemp -d /tmp/url-shortener-verify-XXXXXX)"
DB_PATH="$VERIFY_DIR/url_shortener.db"
export LOG_DB_PATH="$VERIFY_DIR/visits.db"
GRPC_PORT="${VERIFY_GRPC_PORT:-50061}"
WEB_PORT="${VERIFY_WEB_PORT:-8010}"
export DB_PATH
export GRPC_PORT
export GRPC_TARGET="localhost:${GRPC_PORT}"

GRPC_PID=""
WEB_PID=""

cleanup() {
  if [[ -n "$WEB_PID" ]]; then
    kill "$WEB_PID" 2>/dev/null || true
    wait "$WEB_PID" 2>/dev/null || true
  fi
  if [[ -n "$GRPC_PID" ]]; then
    kill "$GRPC_PID" 2>/dev/null || true
    wait "$GRPC_PID" 2>/dev/null || true
  fi
  rm -rf "$VERIFY_DIR"
}
trap cleanup EXIT

port_open() {
  "$PYTHON" - "$1" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(0.2)
sys.exit(0 if sock.connect_ex(("localhost", int(sys.argv[1]))) == 0 else 1)
PY
}

echo "==> Levantando servicio gRPC (:${GRPC_PORT}) y API (:${WEB_PORT})"
"$PYTHON" -m logs_service.server > /tmp/url_shortener_grpc.log 2>&1 &
GRPC_PID=$!
"$UVICORN" app.main:app --port "$WEB_PORT" --log-level warning > /tmp/url_shortener_web.log 2>&1 &
WEB_PID=$!

for _ in $(seq 1 40); do
  port_open "$WEB_PORT" && break
  sleep 0.25
done
for _ in $(seq 1 40); do
  port_open "$GRPC_PORT" && break
  sleep 0.25
done

if ! port_open "$WEB_PORT" || ! port_open "$GRPC_PORT"; then
  echo "Los servicios no arrancaron. Revisa /tmp/url_shortener_web.log y /tmp/url_shortener_grpc.log" >&2
  exit 1
fi

echo "==> POST /shorten"
RESPONSE="$(curl -fsS -w '\n%{http_code}' -X POST "http://localhost:${WEB_PORT}/shorten" \
  -H 'Content-Type: application/json' \
  -d '{"long_url":"https://example.com/verificacion"}')"
[[ "${RESPONSE##*$'\n'}" == "201" ]] || { echo "POST no devolvió 201" >&2; exit 1; }
RESPONSE="${RESPONSE%$'\n'*}"
echo "$RESPONSE"

HASH="$("$PYTHON" -c 'import json, sys; print(json.loads(sys.argv[1])["hash"])' "$RESPONSE")"

echo "==> GET /${HASH} (se espera 302)"
REDIRECT="$(curl -sS -o /dev/null -w 'status=%{http_code} location=%{redirect_url}' \
  "http://localhost:${WEB_PORT}/${HASH}")"
echo "$REDIRECT"
[[ "$REDIRECT" == "status=302 location=https://example.com/verificacion" ]] || exit 1

echo "==> GET /health"
"$PYTHON" - "$WEB_PORT" <<'PY'
import json
import sys
from urllib.request import urlopen

with urlopen(f"http://localhost:{sys.argv[1]}/health") as response:
    assert response.status == 200
    assert json.load(response) == {"status": "ok"}
PY

echo "==> Visitas registradas por gRPC"
"$PYTHON" - <<'PY'
from app.db import connection
from app.db import START_ID
from logs_service.db import log_connection

with connection() as conn:
    url = conn.execute("SELECT id, hash, long_url FROM urls").fetchone()
    assert url["id"] == START_ID
    assert url["hash"] == "eRgfR"
    assert url["long_url"] == "https://example.com/verificacion"
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'visits'").fetchone()[0] == 0
with log_connection() as conn:
    rows = conn.execute(
        "SELECT id, timestamp, short_url, long_url FROM visits"
    ).fetchall()
    if not rows:
        raise SystemExit("No se registró ninguna visita")
    for row in rows:
        assert row["long_url"] == url["long_url"]
        assert row["short_url"].endswith("/eRgfR")
        print(dict(row))
PY

echo "==> Pruebas"
"$PYTHON" -m pytest -q

echo "Verificación completada correctamente."
