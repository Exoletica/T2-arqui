"""Integración real HTTPS de ambas arquitecturas, siempre sobre recursos temporales."""
import os
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import grpc
import httpx

from app.base62 import encode
from app.db import START_ID

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_ready(client, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Un servidor terminó durante el arranque")
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    raise RuntimeError("El servidor HTTPS no respondió a /health")


def check_redirect(client, short_hash, status, url):
    response = client.get(f"/{short_hash}")
    assert response.status_code == status, response.text
    assert response.headers["location"] == url
    return response


def verify():
    with TemporaryDirectory(prefix="shortener-a2-") as tmp, ExitStack() as stack:
        directory = Path(tmp)
        certs = directory / "certs"
        subprocess.run(["bash", str(ROOT / "scripts/gen_certs.sh"), str(certs)],
                       check=True, capture_output=True, text=True)
        # Verifica confianza y SAN: no utiliza verify=False ni curl -k.
        tls = ssl.create_default_context(cafile=str(certs / "localhost.crt"))
        db_file = directory / "integration.db"
        grpc_port, a1_port, a2_port = free_port(), free_port(), free_port()
        while len({grpc_port, a1_port, a2_port}) != 3:
            grpc_port, a1_port, a2_port = free_port(), free_port(), free_port()
        env = {
            **os.environ, "DB_PATH": str(db_file), "GRPC_PORT": str(grpc_port),
            "GRPC_TARGET": f"127.0.0.1:{grpc_port}",
            "A2_RATE_LIMIT_PER_MINUTE": "12", "A2_CACHE_TTL_SECONDS": "2",
        }
        logs = []

        def launch(name, arguments):
            path = directory / f"{name}.log"
            log = stack.enter_context(path.open("w"))
            process = subprocess.Popen([sys.executable, *arguments], cwd=ROOT, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            stack.callback(stop, process)
            logs.append(path)
            return process

        try:
            launch("grpc", ["-m", "logs_service.server"])
            with grpc.insecure_channel(env["GRPC_TARGET"]) as channel:
                grpc.channel_ready_future(channel).result(timeout=15)

            def web(entrypoint, port):
                return ["-m", "uvicorn", entrypoint, "--host", "127.0.0.1", "--port", str(port),
                        "--no-proxy-headers", "--ssl-keyfile", str(certs / "localhost.key"),
                        "--ssl-certfile", str(certs / "localhost.crt"), "--log-level", "warning"]

            p1 = launch("a1", web("app.main:app", a1_port))
            p2 = launch("a2", web("arquitectura2.main:app", a2_port))
            one = stack.enter_context(httpx.Client(base_url=f"https://localhost:{a1_port}",
                                                  verify=tls, trust_env=False, timeout=3))
            two = stack.enter_context(httpx.Client(base_url=f"https://localhost:{a2_port}",
                                                  verify=tls, trust_env=False, timeout=3))
            wait_ready(one, p1)
            wait_ready(two, p2)
            with httpx.Client(verify=tls, trust_env=False, timeout=3) as ip_client:
                assert ip_client.get(f"https://127.0.0.1:{a2_port}/health").status_code == 200
            print("HTTPS real: confianza explícita y SAN localhost/127.0.0.1 correctos.")

            original = "https://example.com/integracion"
            created = []
            for index, client in enumerate((one, two)):
                response = client.post("/shorten", json={"long_url": original})
                assert response.status_code == 201, response.text
                data = response.json()
                assert data["hash"] == encode(START_ID + index)
                assert data["short_url"] == f"{str(client.base_url).rstrip('/')}/{data['hash']}"
                created.append(data)
            first_hash, second_hash = [data["hash"] for data in created]
            check_redirect(one, second_hash, 302, original)
            check_redirect(two, first_hash, 301, original)
            check_redirect(two, first_hash, 301, original)
            print("POST 201, IDs secuenciales compartidos, A1=302 y A2=301 correctos.")

            # Mutación exclusiva de la DB temporal: la respuesta permanece en caché
            # hasta vencer el TTL y entonces refleja la nueva lectura de SQLite.
            changed = "https://example.com/actualizada"
            with sqlite3.connect(db_file) as conn:
                conn.execute("UPDATE urls SET long_url=? WHERE hash=?", (changed, first_hash))
            check_redirect(two, first_hash, 301, original)
            time.sleep(2.1)  # integración real; la prueba unitaria usa reloj simulado
            check_redirect(two, first_hash, 301, changed)
            assert two.get("/missing").status_code == 404
            assert two.post("/shorten", json={"long_url": "ftp://example.com"}).status_code == 422
            print("Caché real: conserva el valor previo y consulta el nuevo tras el TTL.")

            # La misma IP acumula POST, GET y hits de caché. XFF no cambia su identidad.
            for index in range(13):
                response = two.get(f"/{first_hash}", headers={"X-Forwarded-For": f"192.0.2.{index + 1}"})
                if response.status_code == 429:
                    break
                assert response.status_code == 301
            else:
                raise AssertionError("No se aplicó el rate limiter")
            assert response.headers["ratelimit-limit"] == "12"
            assert two.post("/shorten", json={"long_url": original}).status_code == 429
            for path in ("/health", "/schema/swagger", "/schema/openapi.json"):
                assert two.get(path).status_code == 200
            check_redirect(one, first_hash, 302, changed)
            with sqlite3.connect(db_file) as conn:
                visits = conn.execute("SELECT short_url, long_url FROM visits ORDER BY id").fetchall()
                assert visits == [
                    (f"{str(one.base_url).rstrip('/')}/{second_hash}", original),
                    (f"{str(one.base_url).rstrip('/')}/{first_hash}", changed),
                ], visits
            print("429 en GET cacheado y POST; diagnóstico excluido; solo A1 registra visitas gRPC.")
            # Evidencia de SELECT reales, TTL sin esperas e independencia de almacenes.
            subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_arquitectura2.py"],
                           cwd=ROOT, env=env, check=True)
            print("Verificación integral HTTPS completada; procesos y recursos temporales liberados al salir.")
        except BaseException:
            for path in logs:
                print(f"--- {path.name} ---\n{path.read_text()[-5000:]}", file=sys.stderr)
            raise


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Señal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    verify()


if __name__ == "__main__":
    main()
