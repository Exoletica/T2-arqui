import logging
import os
import sys
import time
from concurrent import futures
from pathlib import Path

import grpc

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT, ROOT / "generated"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import logs_pb2  # noqa: E402
import logs_pb2_grpc  # noqa: E402
from app.db import connection, init_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("logs_service")


class LogService(logs_pb2_grpc.LogServiceServicer):
    def LogVisit(self, request, context):
        timestamp = request.timestamp or int(time.time())
        with connection() as conn:
            conn.execute(
                "INSERT INTO visits (timestamp, short_url, long_url) VALUES (?, ?, ?)",
                (timestamp, request.short_url, request.long_url),
            )
        logger.info(
            "Visita registrada: %s -> %s (timestamp=%s)",
            request.short_url,
            request.long_url,
            timestamp,
        )
        return logs_pb2.LogResponse(success=True, message="Visita registrada")


def serve():
    init_db()
    port = os.environ.get("GRPC_PORT", "50051")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    logs_pb2_grpc.add_LogServiceServicer_to_server(LogService(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("Servidor gRPC de logs escuchando en el puerto %s", port)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Deteniendo servidor gRPC...")
        server.stop(grace=2)


if __name__ == "__main__":
    serve()
