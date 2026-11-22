# INF326 — Trade-offs de las dos arquitecturas

Ambas implementaciones utilizan Litestar, SQLite y el mismo alfabeto Base62.
Las diferencias siguientes son decisiones de este proyecto; no constituyen un
benchmark de rendimiento. No se modificó el contrato gRPC ni el mecanismo de IDs.

## 1. HTTP 302 frente a HTTP 301

A1 responde 302: comunica una redirección temporal y permite que solicitudes
posteriores vuelvan a pasar por el acortador. Esto favorece cambios futuros del
destino y observación de visitas, aunque la política efectiva de caché depende
también del cliente y de las cabeceras HTTP.

A2 responde 301: declara permanente la asociación. Navegadores y proxies pueden
reutilizarla y no volver a consultar el acortador, reduciendo tráfico y latencia.
Cambiar el destino posteriormente es difícil: invalidar la caché del servidor
no invalida una redirección ya retenida por un navegador. La aplicación actual
no ofrece una operación para editar o eliminar destinos.

## 2. Registro gRPC frente a ausencia de registro por visita

A1 hace una llamada gRPC por GET válido que llega al servidor y persiste timestamp,
URL corta y URL larga. El servicio separado permite desacoplar el registro del
HTTP, pero consume conexiones, tiempo y recursos en su Log DB SQLite independiente. La llamada es síncrona
con timeout (por defecto 1 segundo); su fallo no impide el 302. No hay reintentos
durables: una caída pierde ese evento. Por ello tampoco garantiza analítica exacta.

A2 no ejecuta llamadas gRPC. Reduce trabajo por redirección, especialmente en
hits de caché, pero no ofrece analítica de visitas. A1 y A2 comparten Shortener DB; el registro utiliza una Log DB independiente.
A2 nunca escribe en `visits`.

## 3. Caché del navegador frente a caché del servidor

La caché del navegador puede evitar completamente una nueva solicitud de red
al acortador. Su comportamiento depende del cliente y una redirección permanente
puede persistir más allá del TTL configurado en A2.

La caché del servidor actúa cuando una solicitud sí llega a Litestar. En A2 guarda
la respuesta 301 por hash durante 300 segundos por defecto y evita repetir el
SELECT a SQLite. No evita el transporte HTTPS ni el middleware de cuota.
El TTL de servidor no controla ni promete el TTL del navegador. Las pruebas
utilizan clientes que no siguen automáticamente redirecciones ni las retienen,
para poder observar de forma independiente el comportamiento del servidor.

## 4. Beneficios y costos del rate limiter

El límite de A2 protege la base y la aplicación frente a ráfagas de solicitudes,
incluidos POST, búsquedas inexistentes y hits de caché. Responde 429 antes de
consultar SQLite o servir la redirección. Un cliente puede reintentar tras el
reinicio indicado en las cabeceras `RateLimit-*`.

El costo incluye consultar/actualizar el contador, sincronizar accesos y reservar
memoria. La IP no equivale a una persona: usuarios de una red universitaria con
NAT pueden compartir cuota, mientras que un atacante con varias IP podría
repartir solicitudes. La ventana de un minuto permite ráfagas alrededor de sus
límites. No se confía en X-Forwarded-For; un proxy de producción requiere una
configuración explícita de confianza para preservar la identidad correcta.

## 5. Rendimiento frente a capacidad de obtener analítica

A2 reduce lecturas de SQLite gracias a la caché y elimina el RPC por visita; el
301 también puede reducir solicitudes que llegan al servidor. A1 conserva más
puntos de observación, pagando una lectura y una llamada RPC por visita válida.
La prueba automatizada demuestra reducción de consultas; no mide percentiles de
latencia ni rendimiento bajo carga. Para cuantificar la mejora se necesitaría
un benchmark representativo, con aciertos/fallos de caché y cuotas comparables.

## 6. Caché y cuotas en memoria

Los dos MemoryStore de A2 se crean por aplicación y no comparten estado con A1.
No requieren Redis ni otro servicio. Un reinicio elimina caché y cuotas, sin
perder URLs persistidas. Cada proceso o worker tiene almacenes independientes:
N workers pueden permitir aproximadamente N veces la cuota por cliente y no
comparten aciertos de caché.

La caché no tiene LRU ni un máximo de entradas. La implementación nativa elimina
objetos vencidos al acceder a su clave; entradas antiguas que no se vuelven a
consultar pueden permanecer en memoria. Un despliegue sostenido necesitaría
limpieza periódica, capacidad acotada y, si se escala horizontalmente, un almacén
compartido con cuota atómica. Los misses concurrentes también pueden repetir
lecturas antes de que exista una respuesta cacheada (sin protección antiestampida).

No se cachean POST ni errores: un hash inexistente que aparezca después será
visible de inmediato, y una cuota agotada no contamina la redirección válida.
Si alguien modifica directamente un destino en SQLite, A2 puede seguir ofreciendo
el valor anterior hasta el TTL; la caché externa de un 301 podría durar más.

## 7. SQLite compartido y concurrencia

Compartir el archivo conserva un espacio único de IDs entre ambas arquitecturas.
AUTOINCREMENT asigna IDs secuenciales y la restricción UNIQUE protege los hashes.
La inserción provisional y su actualización Base62 ocurren en una misma
transacción, como en A1. Los hashes existentes no se recalculan.

WAL favorece lecturas concurrentes mientras hay un escritor. SQLite mantiene un
solo escritor a la vez; Los POST de A1 y A2 compiten por escritura en Shortener DB; los registros
de visitas escriben en otra SQLite y no compiten por su mismo bloqueo. Los
timeouts existentes amortiguan contención breve, pero no eliminan el límite de
capacidad. Ambas aplicaciones deben utilizar el mismo DB_PATH si se desea
compartir URLs; gRPC usa LOG_DB_PATH con su propia tabla visits; con rutas distintas la persistencia se separa y los hashes
podrían coincidir entre archivos. Esta elección sirve para una tarea o despliegue
local pequeño; múltiples máquinas requerirían revisar la persistencia.

## 8. Impacto de HTTPS

TLS protege confidencialidad e integridad de las conexiones HTTP, incluidos los
destinos enviados por POST. Añade negociación criptográfica, gestión/renovación
de certificados y algo de CPU. La reutilización de conexiones amortigua parte del
costo. No hace seguro el contenido de una URL ni restringe quién puede acortarla.

El certificado local autofirmado incluye SAN para localhost y 127.0.0.1; los
navegadores advierten sobre su emisor. La integración verifica confianza
explícita y nombre de host, sin desactivar la validación TLS. En producción se
usaría un certificado emitido por una CA confiable y una política de renovación.
El gRPC interno conserva su contrato y transporte sin TLS en esta etapa local.
A1 puede seguir ejecutándose por HTTP para mantener compatibilidad y pruebas.

## 9. Escenarios recomendados para una institución como la USM

Recomendaría A1 para campañas de admisión, actividades de extensión o enlaces
institucionales que puedan necesitar cambios de destino y mediciones de uso.
Se debe aceptar que el registro actual pierde eventos cuando gRPC falla y que
no mide visitas que nunca llegan al servidor. Los datos de visitas requerirían
políticas institucionales de acceso y retención si se amplía la analítica.

Recomendaría A2 para enlaces estables de material público, documentación o
recursos permanentes, cuando interesa reducir consultas y proteger capacidad.
La institución debe aceptar menor observabilidad y la dificultad de revertir un
301. Ajustaría la cuota a redes con NAT para evitar perjudicar a cursos completos
que comparten IP. Para uso masivo o varios servidores revisaría SQLite y los
almacenes de memoria antes de extrapolar esta implementación académica.

## BONUS — Identificadores únicos en un entorno distribuido (solo propuesta)

Una alternativa sería un ID de 64 bits tipo Snowflake: timestamp relativo a una
época, identificador de nodo asignado de forma única y secuencia local dentro de
cada unidad temporal. Codificar ese entero en el mismo alfabeto Base62 mantiene
la idea de un hash derivado de ID, pero produciría enlaces de otra longitud.

Cada nodo debería reservar un identificador mediante un coordinador o una
configuración que garantice exclusividad. Si el reloj retrocede, el generador
debe detenerse o esperar hasta recuperar el último instante válido; si se agota
la secuencia, debe esperar la siguiente unidad temporal. También deben definirse
persistencia del último estado, reutilización segura de nodos y comportamiento
ante particiones. Estos costos operativos sustituyen la coordinación central de
una secuencia SQLite y merecen pruebas específicas.

La propuesta no se implementa: las dos aplicaciones siguen utilizando IDs SQLite
desde 597652313, sin modificar datos ni hashes existentes.
