# INF326 — Acortador de URLs (Arquitecturas 1 y 2)

Proyecto desarrollado en **Python y Litestar** que implementa dos arquitecturas para acortar URLs. Ambas utilizan **SQLite** y generan hashes **Base62** a partir de IDs consecutivos, comenzando en `597652313`.

## Integrantes y responsabilidades

> - **Catalina Muñoz:** 202073030-K.
> - **Matías Acuña:** 202210097-4.

## Diferencias entre arquitecturas

| Característica | Arquitectura 1 (A1) | Arquitectura 2 (A2) |
|---|---|---|
| Aplicación | `app.main:app` | `arquitectura2.main:app` |
| Puerto HTTPS de ejemplo | `8443` | `8444` |
| `POST /shorten` | HTTP 201 | HTTP 201 |
| `GET /{hash}` | **HTTP 302** (temporal) | **HTTP 301** (permanente) |
| Registro de visitas | Servicio **gRPC**, en `visits.db` | No registra visitas con gRPC |
| Caché | `Cache-Control: no-store` | Caché de respuestas en memoria, TTL de 300 s |
| Rate limiter | No | 60 solicitudes/minuto por IP (HTTP 429 al excederlo) |

Ambas aplicaciones comparten `url_shortener.db` (tabla `urls`). El servicio gRPC de A1 usa otra base de datos, `visits.db` (tabla `visits`). Cada servicio inicializa automáticamente su tabla cuando arranca.

## 1. Requisitos e instalación

Se necesita **Python 3.10 o superior**, `pip` y **OpenSSL**. Para los verificadores se utilizan también Bash y `curl`.

```bash
git clone https://github.com/Exoletica/T2-arqui.git
cd T2-arqui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Los archivos Python generados para gRPC ya están incluidos: **no es necesario generarlos manualmente**.

## 2. Crear los certificados HTTPS

Desde la raíz del proyecto:

```bash
./scripts/gen_certs.sh
```

Se crean `certs/localhost.crt` y `certs/localhost.key`, válidos para `localhost` y `127.0.0.1`. Son certificados autofirmados para uso local; no se debe compartir la clave privada. Los archivos de certificados no se incluyen en Git.

## 3. Iniciar las aplicaciones

Abrir **tres terminales** en la carpeta del proyecto. Activar el entorno virtual en cada una con `source .venv/bin/activate`.

**Terminal 1 — Servicio gRPC (registros de A1):**

```bash
python -m logs_service.server
```

**Terminal 2 — Arquitectura 1 (HTTPS, puerto 8443):**

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8443 --no-proxy-headers \
  --ssl-keyfile certs/localhost.key --ssl-certfile certs/localhost.crt
```

**Terminal 3 — Arquitectura 2 (HTTPS, puerto 8444):**

```bash
uvicorn arquitectura2.main:app --host 127.0.0.1 --port 8444 --no-proxy-headers \
  --ssl-keyfile certs/localhost.key --ssl-certfile certs/localhost.crt
```

**Nota:** A2 funciona sin el servicio gRPC. Para probar solo A2, basta con ejecutar la terminal 3.

## 4. Probar los endpoints

**Crear una URL corta en A1:**

```bash
curl --cacert certs/localhost.crt -i https://localhost:8443/shorten \
  -H 'Content-Type: application/json' \
  -d '{"long_url":"https://example.com/recurso"}'
```

La respuesta es **HTTP 201** e incluye `short_url` y `hash`. Para crear una URL en **A2**, cambiar el puerto `8443` por `8444`.

**Comprobar las redirecciones:** usar el hash entregado en la respuesta anterior. Por ejemplo, si el hash es `eRgfR`:

```bash
curl --cacert certs/localhost.crt -i https://localhost:8443/eRgfR
curl --cacert certs/localhost.crt -i https://localhost:8444/eRgfR
```

- **A1:** responde **302** con `Location` y `Cache-Control: no-store`; cada visita se envía al servicio gRPC.
- **A2:** responde **301** con `Location`; utiliza caché y aplica limitación de solicitudes.

El hash `eRgfR` es solo un ejemplo: corresponde al primer ID de una base limpia. Ambas arquitecturas comparten la base de URLs, por lo que se debe usar siempre el hash devuelto por el `POST`.

**Comprobar el estado de una aplicación:**

```bash
curl --cacert certs/localhost.crt https://localhost:8443/health
```

**Documentación interactiva:** `https://localhost:8443/schema/swagger` (A1) y `https://localhost:8444/schema/swagger` (A2).

## 5. Verificar el proyecto

Con el entorno virtual activo y desde la raíz:

```bash
python -m pytest -q
./scripts/verify.sh
./scripts/verify_a2.sh
```

- `pytest` ejecuta las pruebas automatizadas.
- `verify.sh` comprueba A1 con HTTP y gRPC.
- `verify_a2.sh` realiza una verificación de integración HTTPS de A1 y A2, incluidas la caché, el rate limiter y las bases SQLite separadas.

Los verificadores utilizan bases de datos temporales y no modifican las bases habituales del proyecto.

## 6. Archivos principales

| Ruta | Función |
|---|---|
| `app/` | Arquitectura 1 y operaciones compartidas de URLs/SQLite |
| `arquitectura2/` | Arquitectura 2: redirección 301, caché y rate limiter |
| `logs_service/` | Servicio gRPC y base de datos de visitas |
| `proto/` y `generated/` | Contrato gRPC y código Python generado |
| `scripts/` | Certificados, inicialización, respaldo y verificadores |
| `tests/` | Pruebas automatizadas |
| `tradeoffs.md` | Comparación de decisiones arquitectónicas y sus desventajas |

## 7. Configuración opcional

| Variable | Predeterminado | Uso |
|---|---|---|
| `DB_PATH` | `url_shortener.db` | Base de URLs compartida por A1 y A2 |
| `LOG_DB_PATH` | `visits.db` | Base de visitas del servicio gRPC; debe ser distinta de `DB_PATH` |
| `GRPC_TARGET` | `localhost:50051` | Dirección del servicio gRPC |
| `A2_RATE_LIMIT_PER_MINUTE` | `60` | Límite de solicitudes por IP |
| `A2_CACHE_TTL_SECONDS` | `300` | Duración de la caché de A2, en segundos |

Las cuotas y la caché de A2 están almacenadas en memoria, por proceso. Sus limitaciones y otras decisiones se explican en [tradeoffs.md](tradeoffs.md).

**Mantenimiento (no necesario para ejecutar el proyecto):** `python -m scripts.init_db` y `python -m scripts.init_log_db` inicializan las bases sin borrar datos. `python -m scripts.gen_proto` regenera el código gRPC si cambia `proto/logs.proto`. `python -m scripts.reset_dev_db` **reinicia las bases con respaldo previo y borra los datos activos de prueba**; solo debe utilizarse con A1, A2 y gRPC detenidos.
