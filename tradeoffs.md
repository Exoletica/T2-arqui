# INF326 — Trade-offs de las dos arquitecturas

Ambas implementaciones utilizan Litestar, SQLite y el mismo alfabeto Base62.

## 1. HTTP 302 frente a HTTP 301

La principal diferencia entre ambas arquitecturas está en cómo se manejan las redirecciones y qué sucede cuando un usuario vuelve a utilizar una URL corta.

En la **Arquitectura 1 (A1)** se utiliza el código HTTP 302, que indica una redirección temporal. Esto permite que el navegador vuelva a consultar al acortador cada vez que se utiliza el enlace, especialmente porque la aplicación incorpora la cabecera `Cache-Control: no-store`. Su principal ventaja es que facilita el registro de visitas y permitiría modificar el destino de los enlaces en el futuro. Sin embargo, como desventaja significa que el servidor debe atender más solicitudes, y por lo tanto, su carga de trabajo.

Por otra parte, la **Arquitectura 2 (A2)** utiliza el código HTTP 301, que indica una redirección permanente. Esto permite que los navegadores guarden la redirección en su caché, evitando consultar nuevamente al acortador en algunas visitas. Como resultado, se puede reducir el tráfico hacia el servidor y mejorar los tiempos de respuesta. Pero esta ventaja también tiene una desventaja: si en el futuro se necesita cambiar la dirección original, algunos navegadores podrían seguir utilizando la redirección que guardaron anteriormente. Por eso, A2 resulta más adecuada para enlaces cuyo destino se espera que permanezca estable.

## 2. Registro gRPC frente a ausencia de registro por visita

Otra diferencia entre ambas arquitecturas es la manera en que manejan la información de las visitas realizadas a los enlaces.

En la Arquitectura 1 (A1), cada vez que llega una solicitud válida de redirección, se envía un mensaje mediante gRPC a un servicio encargado de registrar la visita. Este servicio guarda la fecha y hora mediante un timestamp, junto con la URL corta y su dirección original, en una base de datos SQLite independiente (visits.db). Esta separación permite mantener el registro de visitas como una responsabilidad distinta del acortador. Sin embargo, también requiere recursos adicionales y puede aumentar el tiempo de respuesta, ya que la llamada gRPC se realiza antes de completar la redirección. Si el servicio de registro no responde, A1 continúa con la redirección HTTP 302 después del fallo o del tiempo de espera configurado, que por defecto es de un segundo. En ese caso, la visita no queda registrada, porque actualmente no existe un mecanismo de reintentos.

En cambio, la Arquitectura 2 (A2) no utiliza gRPC ni registra cada visita. Esto simplifica su funcionamiento y reduce el trabajo necesario para responder a las solicitudes, especialmente cuando puede utilizar una respuesta almacenada en caché. Su principal desventaja es que no proporciona información sobre cuántas veces se utilizan los enlaces.

Por lo tanto, A1 resulta más conveniente cuando es importante conocer el uso de los enlaces, mientras que A2 es una alternativa más sencilla cuando se busca reducir el trabajo del servidor y no se necesita registrar cada visita.

## 3. Beneficios y costos del rate limiter

La Arquitectura 2 incorpora un **rate limiter**, cuya función es controlar la cantidad de solicitudes que puede realizar un cliente durante un período determinado.

Esta medida ayuda a proteger la aplicación frente a un número excesivo de peticiones, evitando que el servidor y la base de datos reciban una carga innecesaria. En la implementación, el límite predeterminado es de 60 solicitudes por minuto por dirección IP y se aplica tanto a la creación de URLs como a las redirecciones, incluso cuando estas se encuentran almacenadas en caché.

Cuando un cliente supera el límite permitido, el servidor responde con el código HTTP 429, indicando que se han realizado demasiadas solicitudes. Sin embargo, la protección también presenta algunas limitaciones. Por ejemplo, en una universidad es común que varios estudiantes utilicen una misma red y compartan una dirección IP pública. En ese caso, todos podrían consumir una misma cuota, provocando que algunos usuarios sean bloqueados temporalmente aunque individualmente hayan realizado pocas solicitudes. Por otra parte, una persona que utilice distintas direcciones IP podría distribuir sus peticiones y evitar parte de esta restricción.

## 4. Escenarios recomendados para una institución como la USM

Si la USM necesitara implementar un servicio de acortamiento de URLs, la elección entre ambas arquitecturas dependería principalmente del uso que se dará a los enlaces.

Se recomendaría la **Arquitectura 1** para campañas de eventos o publicaciones donde sea importante conocer la cantidad de visitas recibidas. Su sistema de registro mediante gRPC permitiría obtener información útil para evaluar el interés de los usuarios y apoyar futuras decisiones. También sería conveniente para enlaces cuyos destinos podrían cambiar más adelante. No obstante, la universidad tendría que considerar el mayor trabajo del servidor y que algunos registros podrían perderse si el servicio gRPC presenta fallos. Si se ampliara el análisis de visitas, también sería necesario establecer medidas para proteger y administrar adecuadamente esa información.

Por otra parte, se recomienda la **Arquitectura 2** para documentos material de consulta o páginas que no cambian frecuentemente. Su redirección HTTP 301 y el uso de caché permitirían reducir solicitudes y aprovechar mejor los recursos disponibles. Sin embargo, la universidad tendría que aceptar que esta arquitectura no registra cada visita y que modificar una redirección permanente puede resultar complicado cuando los navegadores ya la han almacenado. Además, sería importante ajustar el rate limiter considerando que numerosos estudiantes pueden compartir una misma dirección IP al utilizar las redes universitarias.
