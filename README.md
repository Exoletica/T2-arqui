# INF326 — Acortador de URLs: Arquitecturas 1 y 2

Dos aplicaciones ASGI independientes con **Litestar 2.25.0**, SQLite y hashes
Base62 derivados del ID. Comparten el contrato de creación y la persistencia,
pero ofrecen comportamientos distintos al redirigir.

| Característica | Arquitectura 1 | Arquitectura 2 |
|---|---|---|
| Entrada ASGI | `app.main:app` | `arquitectura2.main:app` |
| HTTPS local | `https://localhost:8443` | `https://localhost:8444` |
| `POST /shorten` | 201 | 201 |
| `GET /{hash}` | **302**, temporal | **301**, permanente |
| Registro por visita | Servicio gRPC | Sin llamadas gRPC |
| Caché de servidor | No | En memoria, TTL 300 s |
| Rate limiter | No | 60 solicitudes/minuto por IP |
| `GET /health` | 200, `{"status":"ok"}` | Igual, excluido del límite |

```text
A1: cliente → Litestar → SQLite → HTTP 302
                   └── gRPC LogVisit → servicio de logs → visits.db (tabla visits)
A2: cliente → RateLimitConfig → caché GET → HTTP 301
                                    └── miss → SQLite → guarda respuesta 301
Ambas: POST /shorten → validación común → SQLite ID → Base62 → HTTP 201
```

Los IDs empiezan en `597652313`, se incrementan secuencialmente y se codifican
con el alfabeto `0-9A-Za-z`. En una base limpia, el primer hash es `eRgfR`.
Ambas arquitecturas utilizan directamente [pybase62 1.0.0](https://pypi.org/project/pybase62/)
en `app/urls.py`, mediante `import base62` y `base62.encode(url_id)`, con el
alfabeto predeterminado. Se eliminó la implementación manual y no existe un
adaptador. La biblioteca se instala con `pip install -r requirements.txt`.
Se comprobó compatibilidad con la implementación anterior para 10.009 IDs y las
dos URLs almacenadas en la base local al realizar la sustitución.

La biblioteca tiene validaciones diferentes: `encode(-1)` devuelve `"0"`,
`decode("")` devuelve `0` y codificar tipos no enteros lanza `TypeError`.
SQLite genera IDs enteros positivos desde `597652313`; no se aceptan IDs del
cliente ni se decodifican hashes para buscar URLs, por lo que estas diferencias
no modifican el contrato HTTP. No se agregaron adaptadores de excepciones.

No se alteran los hashes ni las tablas existentes. La inicialización automática
al arrancar conserva URLs, visitas e IDs. `scripts/init_db.py` es opcional.
Si gRPC falla, A1 sigue redirigiendo con 302 y omite el registro fallido.
A1 y A2 comparten únicamente Shortener DB (`url_shortener.db`, tabla `urls`).
El servicio gRPC utiliza exclusivamente Log DB (`visits.db`, tabla `visits`)
con su propia conexión e inicialización en `logs_service/db.py`. A2 nunca
escribe visitas ni necesita ejecutar el servidor gRPC para funcionar.

## Estructura

```text
.
├── app/
│   ├── main.py              # A1: HTTP 302 y cliente gRPC
│   ├── http.py              # Modelos, validación y errores HTTP compartidos
│   ├── urls.py              # Inserción/búsqueda de URLs compartidas
│   ├── db.py                # Shortener DB: solo urls e ID inicial
│   └── grpc_client.py       # Cliente tolerante a fallos, exclusivo de A1
├── arquitectura2/
│   ├── __init__.py
│   └── main.py              # A2 y factory create_app(), caché y rate limiter
├── logs_service/
│   ├── server.py            # Servicio gRPC exclusivo de A1
│   └── db.py                # Log DB: conexión propia, tabla visits
├── proto/logs.proto         # Contrato sin cambios
├── generated/               # Stubs incluidos en el repositorio
├── certs/                   # Certificado/clave locales, ignorados por Git
├── scripts/
│   ├── init_log_db.py
│   ├── reset_dev_db.py      # Reinicialización con respaldo verificado
│   ├── init_db.py
│   ├── gen_proto.py
│   ├── gen_certs.sh
│   ├── verify.sh            # Verificador original A1 por HTTP
│   ├── verify_a2.sh         # Verificador HTTPS de coexistencia
│   └── verify_a2.py         # Procesos, comprobaciones y limpieza temporal
├── tests/
│   ├── test_api.py          # Cobertura original A1 conservada
│   ├── test_base62.py
│   ├── test_db_grpc.py
│   └── test_arquitectura2.py
├── requirements.txt
├── tradeoffs.md
└── README.md
```

Se eligió `arquitectura2.main:app` para mantener la entrada original de A1.
Solo se extrajeron el contrato HTTP y las operaciones SQLite a módulos pequeños;
A2 no importa `app.main` ni el cliente gRPC.

## Instalación desde cero

Requisitos: Python **3.10+**, pip y OpenSSL (probado con Python 3.12 y OpenSSL 3).
El verificador original también utiliza Bash y curl.

```bash
git clone https://github.com/Exoletica/T2-arqui.git
cd T2-arqui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

En una copia local existente, trabajar directamente sobre ella; no es necesario
clonar, actualizar ni reemplazar archivos. Las dependencias están fijadas:
Litestar 2.25.0, Pydantic 2.14.4, Uvicorn 0.34.0, grpcio/grpcio-tools 1.62.3,
protobuf 4.25.3, pytest 8.3.4, httpx 0.28.1 y pybase62 1.0.0. No se agregaron servicios externos.

Los stubs ya están incluidos. Solo si cambia `proto/logs.proto`:

```bash
python -m scripts.gen_proto
```

## Certificados autofirmados

Desde la raíz del proyecto:

```bash
./scripts/gen_certs.sh
openssl x509 -in certs/localhost.crt -noout -ext subjectAltName
```

Genera `certs/localhost.crt` y `certs/localhost.key`, con SAN para `localhost` y
`127.0.0.1`, vigencia de 365 días y permisos restringidos de escritura/lectura.
La carpeta `certs/` está excluida de Git. No compartir la clave privada.
El script evita sobrescribir archivos existentes. Para renovar de forma
reproducible, generar un par nuevo en otra carpeta ignorada:

```bash
./scripts/gen_certs.sh certs/renovado
```

En ese caso usar las rutas `certs/renovado/localhost.crt` y
`certs/renovado/localhost.key` en los comandos siguientes.
Los navegadores advertirán que el emisor no es confiable: es un certificado
local autofirmado aceptable para este entorno académico. Para curl usamos
`--cacert`, que verifica el certificado y su SAN sin desactivar TLS.

## Ejecución simultánea mediante HTTPS

Abrir tres terminales en la raíz del repositorio y activar `.venv` en cada una.
A1 y A2 usan la misma `url_shortener.db`; gRPC usa `visits.db`.
Si se configura `DB_PATH`, usar el mismo valor en A1 y A2. Configurar
`LOG_DB_PATH` en gRPC para cambiar su archivo; debe ser distinto de `DB_PATH`.
La conexión gRPC ya no depende de la conexión ni de la inicialización del acortador.

Terminal 1 — gRPC interno, sin TLS:

```bash
source .venv/bin/activate
python -m logs_service.server
```

Terminal 2 — Arquitectura 1:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8443 --no-proxy-headers \
  --ssl-keyfile certs/localhost.key --ssl-certfile certs/localhost.crt
```

Terminal 3 — Arquitectura 2:

```bash
source .venv/bin/activate
uvicorn arquitectura2.main:app --host 127.0.0.1 --port 8444 --no-proxy-headers \
  --ssl-keyfile certs/localhost.key --ssl-certfile certs/localhost.crt
```

El esquema y puerto de `short_url` proceden de la petición recibida. Al acceder
por HTTPS se generan URLs HTTPS de la aplicación correspondiente. Los puertos
8443/8444 pueden cambiarse sin modificar código.

Se mantiene la ejecución HTTP original de A1 para compatibilidad:

```bash
uvicorn app.main:app --reload --port 8000
```

Documentación automática de cada aplicación: `/schema/swagger`; esquema:
`/schema/openapi.json`. Ejemplos:
`https://localhost:8443/schema/swagger` y
`https://localhost:8444/schema/swagger`.

## Endpoints y ejemplos

Ambas reciben `{"long_url":"https://example.com/recurso"}` en `POST /shorten`,
aceptan HTTP/HTTPS, recortan espacios exteriores y responden **201**:

```bash
curl --cacert certs/localhost.crt -i https://localhost:8444/shorten \
  -H 'Content-Type: application/json' \
  -d '{"long_url":"https://example.com/recurso"}'
```

```json
{"short_url":"https://localhost:8444/eRgfR","hash":"eRgfR"}
```

El hash anterior solo corresponde a la primera URL de una base limpia. Usar el
hash devuelto por POST. Para A1 cambiar el puerto a 8443.

Comprobar la redirección sin seguirla (curl **sin `-L`**):

```bash
curl --cacert certs/localhost.crt -i https://localhost:8443/eRgfR  # 302
curl --cacert certs/localhost.crt -i https://localhost:8444/eRgfR  # 301
curl --cacert certs/localhost.crt https://localhost:8444/health
```

Ambas incluyen `Location` con la URL original. Un hash inexistente devuelve
**404** con `{"detail":"URL no encontrada"}`. URLs inválidas, campos ausentes,
valores incompatibles, cuerpos vacíos y JSON malformado devuelven **422** con la
lista de errores en `detail`, compatible entre ambas arquitecturas. Al exceder
la cuota de A2, **429** tiene prioridad y el endpoint no se ejecuta.

Para revisar las visitas exclusivas de A1:

```bash
sqlite3 visits.db 'SELECT id, timestamp, short_url, long_url FROM visits;'
sqlite3 url_shortener.db '.tables'  # urls (sin visits en una base nueva)
```

## Configuración y alcance del rate limiter y la caché

| Variable | Valor por defecto | Uso |
|---|---|---|
| `DB_PATH` | `url_shortener.db` en la raíz | A1 y A2: tabla urls |
| `LOG_DB_PATH` | `visits.db` en la raíz | Solo el servicio gRPC: tabla visits |
| `GRPC_TARGET` | `localhost:50051` | Cliente de A1 |
| `GRPC_PORT` | `50051` | Servidor gRPC |
| `GRPC_TIMEOUT` | `1.0` segundos | Cliente de A1 |
| `A2_RATE_LIMIT_PER_MINUTE` | `60` | Cuota común para POST y GET por IP en A2 |
| `A2_CACHE_TTL_SECONDS` | `300` | Vida de respuestas GET 301 en A2 |

Las dos variables de A2 deben ser enteros positivos; valores inválidos impiden
el arranque. Se leen al crear la aplicación: reiniciar el proceso para aplicar
cambios. Ejemplo: `A2_RATE_LIMIT_PER_MINUTE=10 A2_CACHE_TTL_SECONDS=30 uvicorn
arquitectura2.main:app --port 8444 ...` (añadir las opciones TLS anteriores).

**Rate limiter:** middleware nativo `RateLimitConfig`, ventana de un minuto
iniciada con la primera solicitud. POST y GET comparten el presupuesto de la IP,
incluidas solicitudes inválidas y respuestas desde caché. Devuelve 429 al
agotarlo y expone cabeceras `RateLimit-*`. `/health` y `/schema` están excluidos
mediante patrones anclados; rutas como `/healthExtra` siguen limitadas.
La identidad usa la IP de transporte, sin confiar en `X-Forwarded-For`.
Los comandos desactivan la interpretación de cabeceras proxy en Uvicorn;
si se despliega tras un proxy, configurar explícitamente cuáles son confiables.

**Caché:** mecanismo nativo `ResponseCacheConfig`, habilitado únicamente en el
GET de redirección. Clave `a2:redirect:{hash}`; se ignoran parámetros query porque
no cambian el destino. Solo se almacenan respuestas GET con estado **301**.
No se almacenan POST, 404, 429 ni otros errores. El middleware de cuota se
ejecuta antes de consultar la caché, por lo que un hit no evita el límite.
Los almacenes `MemoryStore` de cuotas y redirecciones son distintos y se crean
por instancia; A1 no los utiliza ni comparte estado con ellos.

Ambos almacenes son locales al proceso y se pierden al reiniciarlo. Con múltiples
workers cada uno tiene su propia cuota y caché; la cuota global puede superar
el valor configurado. La memoria no tiene límite LRU; los objetos vencidos se
retiran al acceder a su clave, de modo que claves nunca consultadas nuevamente
pueden ocupar memoria hasta reiniciar. Un despliegue mayor necesitaría políticas
de capacidad/limpieza y almacenamiento compartido; para esta tarea no se usa Redis.
Ver [tradeoffs.md](tradeoffs.md) para implicaciones de 301, analítica y concurrencia.

## Pruebas y verificadores

```bash
source .venv/bin/activate
pytest -q
./scripts/verify.sh
./scripts/verify_a2.sh
```

- Las pruebas anteriores de A1 se conservan íntegramente: 302, gRPC, 404/422,
  persistencia, inicialización y Base62.
- Las pruebas de A2 crean una aplicación nueva y una SQLite temporal por caso,
  sin contaminar cuotas ni caché de otros tests. Comparan validaciones con A1,
  verifican ausencia de gRPC, HTTPS en `short_url`, coexistencia y creación concurrente.
- La prueba de caché cuenta `SELECT` reales mediante `sqlite3.set_trace_callback`:
  primer GET = una consulta, segundo GET = ninguna adicional; tras adelantar
  un reloj simulado más allá del TTL vuelve a consultar. Las tres respuestas son
  301 con el mismo `Location`. No usa esperas reales. Comprueba claves por hash,
  errores no cacheados, cuota sobre hits y recuperación tras vencer la ventana.
- `verify.sh` se conserva y comprueba A1 por HTTP con gRPC real. Usa su base de
  verificación en un directorio propio de `/tmp`, con archivos separados de URLs y visitas.
- `verify_a2.sh` crea un directorio temporal propio con dos SQLite independientes, logs y certificados,
  elige puertos locales libres y levanta ambos servidores HTTPS y gRPC. Verifica
  confianza/SAN, POST 201, IDs compartidos, tres GET 302 con `Cache-Control: no-store`,
  tres eventos en Log DB y ninguna tabla visits en Shortener DB. Reinicia A1 y
  gRPC y verifica persistencia, además de 301 en A2, 422/404,
  caché y 429 incluso variando XFF. Usa un TTL real de 2 segundos en la integración
  y ejecuta además las pruebas de A2. Termina procesos y elimina sus recursos
  temporales tanto al finalizar como ante excepciones o interrupciones normales.

Los verificadores necesitan permiso para abrir sockets locales. En un sandbox
que lo impida, ejecutarlos fuera del entorno restringido. No se requiere acceso
a servicios externos durante las pruebas ni se toca la base real del proyecto.

## Referencias

- [RateLimitConfig de Litestar](https://docs.litestar.dev/2/reference/middleware/rate_limit.html).
- [Configuración de caché de respuestas](https://docs.litestar.dev/2/reference/config.html).
- [Almacenes de Litestar](https://docs.litestar.dev/2/usage/stores).
- [Repositorio](https://github.com/Exoletica/T2-arqui).

## Inicialización y reinicialización de desarrollo

Cada servicio inicializa solo su esquema al arrancar. También se pueden crear
las bases manualmente, sin borrar datos (comandos idempotentes):

```bash
source .venv/bin/activate
python -m scripts.init_db      # DB_PATH: urls; primer ID 597652313
python -m scripts.init_log_db  # LOG_DB_PATH: visits
```

A1 responde siempre 302 a un hash válido con `Location` y
`Cache-Control: no-store`; cada GET envía un evento gRPC con timestamp y las dos
URLs. Los eventos distintos pueden tener el mismo timestamp de segundos.

Para esta entrega los registros anteriores son datos de prueba. **No hay
migración de filas**: la instrucción de reinicialización sustituye la migración.
El código no elimina una tabla visits heredada al arrancar sobre una base vieja;
simplemente deja de usarla. No mueve ni duplica visitas automáticamente.

Para empezar desde cero, detener A1, A2 y gRPC (incluidos procesos con --reload).
Mantenerlos detenidos durante todo el comando, sin iniciar otros clientes SQLite:

```bash
python -m scripts.reset_dev_db
```

En Linux el script comprueba procesos y descriptores abiertos en `/proc`, rechaza
servicios conocidos activos y archivos en uso, y aborta si no puede inspeccionar
un proceso Python/SQLite relevante. Crear después un respaldo SQLite mediante la
API backup, verificar `integrity_check` y comparar el volcado completo precede a
cualquier reemplazo. Los respaldos, originales y posibles WAL/SHM se conservan en
`db_backups/reset-*/`, ignorado por Git; `manifest.json` registra rutas y conteos.
Después crea bases vacías con esquemas separados y reinicia la secuencia de URLs
en 597652313. No elimina registros sin respaldo ni toca otros archivos `.db`.
No utilizar este comando con servicios en ejecución; en entornos de permisos
restringidos puede ser necesario ejecutarlo fuera del sandbox.

Para recuperar datos, detener de nuevo los servicios, conservar las bases activas
y restaurar los snapshots verificados `shortener.db` y, si existía, `log.db` a
sus rutas originales. Un snapshot legacy del acortador conserva también sus
visitas antiguas. No hay un comando de migración: esos registros quedan en el
respaldo y no se copian a las bases nuevas. Los inicios y reinicios normales sí
conservan las URLs y visitas de las bases activas sin duplicar filas.
