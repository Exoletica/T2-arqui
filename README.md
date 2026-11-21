# Acortador de URLs — Arquitectura 1

Servicio de acortamiento de URLs construido con **FastAPI**, **SQLite**, hashes
**Base62** derivados del ID y un **servicio gRPC** independiente que registra
cada visita.

## Arquitectura

```
Cliente
  │
  ├── POST /shorten ──► FastAPI ──► SQLite (tabla urls)
  │                        │
  │                        └── genera hash Base62 a partir del ID
  │
  └── GET /{hash} ────► FastAPI ──► busca URL ──► HTTP 302
                             │
                             └── gRPC LogVisit ──► Servidor de logs (:50051)
                                                        │
                                                        └── SQLite (tabla visits)
```

- El **ID** de cada URL inicia en `597652313` y es único.
- El **hash** es la codificación Base62 de ese ID (alfabeto `0-9A-Za-z`), por lo
  que también es único. El primer hash es `eRgfR`.
- Si el servicio gRPC de logs está caído, la redirección **302** sigue
  funcionando; solo se omite el registro de la visita.

## Estructura

```
.
├── app/
│   ├── main.py          # Endpoints POST /shorten y GET /{hash}
│   ├── db.py            # SQLite: tablas urls y visits
│   ├── base62.py        # Codificación/decodificación Base62
│   └── grpc_client.py   # Cliente gRPC (tolerante a fallos)
├── logs_service/
│   └── server.py        # Servidor gRPC de logs
├── proto/
│   └── logs.proto       # Definición del servicio LogService
├── generated/           # Stubs gRPC generados
├── scripts/
│   ├── init_db.py       # Inicializa la base de datos
│   └── gen_proto.py     # Regenera los stubs gRPC
├── tests/               # Pruebas con pytest
├── requirements.txt
└── README.md
```

## Requisitos

- Python 3.9 o superior
- pip

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.gen_proto   # solo si necesitas regenerar los stubs
python -m scripts.init_db     # crea url_shortener.db y fija el ID inicial
```

## Ejecución

Se necesitan **dos terminales** (con el entorno virtual activado).

Terminal 1 — servicio gRPC de logs:

```bash
python -m logs_service.server
```

Terminal 2 — API web:

```bash
uvicorn app.main:app --reload
```

La API queda en `http://localhost:8000` y la documentación interactiva en
`http://localhost:8000/docs`.

Variables de entorno opcionales:

| Variable       | Por defecto        | Descripción                          |
|----------------|--------------------|--------------------------------------|
| `DB_PATH`      | `url_shortener.db` | Ruta del archivo SQLite              |
| `GRPC_TARGET`  | `localhost:50051`  | Dirección del servicio gRPC de logs  |
| `GRPC_PORT`    | `50051`            | Puerto donde escucha el servidor gRPC|
| `GRPC_TIMEOUT` | `1.0`              | Timeout del cliente gRPC (segundos)  |

## Uso

Acortar una URL:

```bash
curl -X POST http://localhost:8000/shorten \
  -H 'Content-Type: application/json' \
  -d '{"long_url":"https://example.com/destino"}'
```

Respuesta:

```json
{
  "short_url": "http://localhost:8000/eRgfR",
  "hash": "eRgfR"
}
```

Redirección (HTTP 302):

```bash
curl -i http://localhost:8000/eRgfR
```

Ver las visitas registradas por gRPC:

```bash
sqlite3 url_shortener.db "SELECT * FROM visits;"
```

## Verificación rápida

Un solo comando levanta ambos servicios en puertos alternos con una base de
datos temporal, prueba `POST`/`GET`, confirma la visita registrada por gRPC y
ejecuta las pruebas:

```bash
./scripts/verify.sh
```

Salida esperada con una base limpia: hash `eRgfR`, `status=302`, una fila en
`visits` y `21 passed`.

## Pruebas

```bash
pytest -q
```

Las pruebas cubren:

- Ida y vuelta de Base62 y unicidad de hashes.
- Creación de URLs con ID inicial `597652313`.
- Redirección `302` con `Location` correcto.
- `404` para hashes inexistentes y `422` para URLs inválidas.
- Registro de visitas en la tabla `visits`.

## Repositorio

<https://github.com/Exoletica/T2-arqui>

Clonar y ejecutar:

```bash
git clone git@github.com:Exoletica/T2-arqui.git
cd T2-arqui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.init_db
./scripts/verify.sh
```

Para subir cambios:

```bash
git add .
git commit -m "descripción del cambio"
git push
```

## Notas

- `url_shortener.db` y `.venv/` están excluidos por `.gitignore`.
- Los stubs de `generated/` se incluyen en el repositorio para poder ejecutar el
  proyecto sin regenerarlos; si modificas `proto/logs.proto`, ejecuta
  `python -m scripts.gen_proto`.
