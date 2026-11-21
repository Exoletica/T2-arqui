import logging
import os
import sys
import time
from pathlib import Path

import grpc

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import logs_pb2  # noqa: E402
import logs_pb2_grpc  # noqa: E402

logger = logging.getLogger(__name__)

GRPC_TARGET = os.environ.get("GRPC_TARGET", "localhost:50051")
GRPC_TIMEOUT = float(os.environ.get("GRPC_TIMEOUT", "1.0"))


def log_visit(short_url, long_url):
    """Envía una visita al servicio gRPC de logs. Nunca rompe la redirección."""
    try:
        with grpc.insecure_channel(GRPC_TARGET) as channel:
            stub = logs_pb2_grpc.LogServiceStub(channel)
            stub.LogVisit(
                logs_pb2.LogRequest(
                    timestamp=int(time.time()),
                    short_url=short_url,
                    long_url=long_url,
                ),
                timeout=GRPC_TIMEOUT,
            )
        return True
    except grpc.RpcError as exc:
        logger.warning("No se pudo registrar la visita vía gRPC: %s", exc)
        return False
