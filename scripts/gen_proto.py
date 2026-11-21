from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parent.parent
PROTO_FILE = ROOT / "proto" / "logs.proto"
OUT_DIR = ROOT / "generated"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "__init__.py").touch(exist_ok=True)

    args = [
        "protoc",
        f"-I{ROOT / 'proto'}",
        f"--python_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
        str(PROTO_FILE),
    ]
    code = protoc.main(args)
    if code != 0:
        raise SystemExit(f"protoc falló con código {code}")
    print(f"Stubs gRPC generados en {OUT_DIR}")


if __name__ == "__main__":
    main()
