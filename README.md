# PersistenceMicroservices-pdf-extractext

Microservicio de persistencia para el orquestador `pdf-extractext`. Recibe el
texto extraído de un PDF y lo guarda en MongoDB, identificado por su `checksum`.

La especificación completa vive en [`SPEC.md`](SPEC.md); este README explica
cómo arrancarlo y cómo falar con él.

## Requisitos

- Python 3.14 o superior.
- MongoDB accesible (sólo para los verbos de `/texts`; las sondas arrancan sin él).

## Variables de entorno

Siete variables, seis con valor por defecto. `SERVICE_API_TOKEN` **no** tiene
valor por defecto: sin ella el proceso no arranca (SPEC 2.5).

| Variable | Por defecto | Qué es |
|---|---|---|
| `SERVICE_API_TOKEN` | — | Secreto compartido. **Obligatoria.** |
| `APP_NAME` | `Persistence Microservice` | Título del documento OpenAPI. |
| `MONGO_URI` | `mongodb://localhost:27017` | Cadena de conexión. |
| `MONGO_DATABASE` | `pdf_extractext` | Base de datos. |
| `MONGO_TEXTS_COLLECTION` | `texts` | Colección que guarda los documentos. |
| `MONGO_TIMEOUT_MS` | `5000` | Timeout de cada operación contra Mongo. |
| `MAX_TEXT_BODY_BYTES` | `10485760` | Tamaño máximo del body (10 MiB). |

Un valor numérico que no sea un entero positivo detiene el arranque: un timeout o
un límite de tamaño en cero desactivaría el límite en silencio.

## Arranque

```bash
uv sync
uv run uvicorn app.main:create_app --factory --port 8000 \
    --timeout-graceful-shutdown 20
```

La aplicación se construye con una fábrica (`--factory`) porque la configuración
se resuelve al construirla, no al importar el módulo.

`--timeout-graceful-shutdown 20` acota el apagado: ante un `SIGTERM`, Uvicorn
deja de aceptar peticiones, termina las que están en vuelo, ejecuta el `lifespan`
(que cierra el pool de MongoDB) y sale; si alguna se cuelga más de 20 s, el
proceso no se queda esperando indefinidamente. En el contenedor, el
`stop_grace_period: 30s` del `docker-compose.yml` deja holgura sobre ese límite
para que Docker no envíe `SIGKILL` antes de que el cierre termine.

Para las pruebas y el linter:

```bash
uv run pytest --cov=app --cov-fail-under=85
uv run ruff check .
uv run ruff format .
```

## Autenticación

Todas las rutas exigen `Authorization: Bearer <SERVICE_API_TOKEN>` salvo
`/health` y `/readyz`, que quedan abiertas para sondas de plataforma.

El esquema se compara sin distinguir mayúsculas; el valor, no. El `detail` del
`401` es idéntico si falta, está vacío, lleva otro esquema o es incorrecto, para
no darle a un atacante un oráculo que le permita enumerar tokens (SPEC 3.2).

```bash
curl -i http://localhost:8000/texts?checksum=abc
# HTTP/1.1 401 Unauthorized
# WWW-Authenticate: Bearer
```

## Contrato

| Verbo | Ruta | Éxito | Fallos |
|---|---|---|---|
| `GET` | `/health` | `200 {"status":"ok"}` | — |
| `GET` | `/readyz` | `200 {"status":"ok","mongo":"ok"}` | `503` |
| `POST` | `/texts` | `201` | `400` `401` `409` `413` `415` |
| `GET` | `/texts?checksum=<valor>` | `200` | `400` `401` `404` |
| `PUT` | `/texts?checksum=<valor>` | `200` | `400` `401` `404` `413` `415` |
| `DELETE` | `/texts?checksum=<valor>` | `200` | `400` `401` `404` |

`checksum` viaja como query param y no como path param: no tiene formato
validado, así que un valor con `/` rompería la resolución de la ruta y
produciría un `404` silencioso (SPEC 1.2). Si falta, la respuesta es
`400 VALIDATION_ERROR`, no `404`.

**Cuerpos de entrada.** `POST` recibe `text`, `checksum`, `name` y `metadata`.
`PUT` recibe sólo `name` y `metadata`; enviar `text` o `checksum` es
`400 IMMUTABLE_FIELD`, porque son la identidad del documento y no su contenido
(SPEC 4.3).

**Cuerpos de salida.** `GET` y `PUT` devuelven el documento completo
(`checksum`, `text`, `name`, `metadata`, `created_at`, `updated_at`). `POST` y
`DELETE` devuelven `{"message":"OK","checksum":"..."}`.

### Errores

Todo fallo es un documento `application/problem+json` (RFC 9457), con `type`,
`title`, `status`, `detail`, `instance` y `code`. No hay `422`: la validación de
entrada es de este servicio y responde `400` (SPEC 2.3).

| `code` | HTTP | Cuándo |
|---|---|---|
| `VALIDATION_ERROR` | 400 | JSON malformado, no-objeto, tipos erróneos, campo requerido ausente, `checksum` fuera de la query |
| `IMMUTABLE_FIELD` | 400 | `PUT` con `text` o `checksum` en el body |
| `UNAUTHORIZED` | 401 | Bearer ausente, mal formado o inválido |
| `METHOD_NOT_ALLOWED` | 405 | Verbo no soportado en la ruta |
| `NOT_FOUND` | 404 | Ruta inexistente |
| `TEXT_NOT_FOUND` | 404 | Checksum inexistente |
| `CHECKSUM_ALREADY_EXISTS` | 409 | `POST` con checksum existente |
| `PAYLOAD_TOO_LARGE` | 413 | Body mayor que `MAX_TEXT_BODY_BYTES`, o documento mayor que 16 MiB |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | `Content-Type` distinto de `application/json` |
| `INTERNAL_ERROR` | 500 | Excepción no prevista |
| `PERSISTENCE_ERROR` | 503 | MongoDB inalcanzable o con error |

`title` nunca incluye valores variables, para que un cliente pueda comparar
errores por `title`. Lo variable va en `detail`, y `detail` nunca incluye stack
traces ni mensajes del driver.

El orden de validación va de lo barato a lo caro: `401` → `415` → `413` →
`400`. Una petición que va a fallar no debe pagar un parseo de body antes de
descubrir que su token es inválido (SPEC 3.3).

## Documentación interactiva

`/docs`, `/redoc` y `/openapi.json` requieren token, como cualquier otra ruta
salvo las sondas:

```bash
open http://localhost:8000/docs
```

## Ejemplos

Con el token en una variable, para no repetirlo en cada llamada:

```bash
TOKEN=tu-secreto-compartido
```

### Crear un texto

```bash
curl -i -X POST http://localhost:8000/texts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "text": "contenido extraído del PDF...",
        "checksum": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        "name": "contrato.pdf",
        "metadata": { "pages": 12, "duration_ms": 431, "producer": "pypdf" }
      }'
# HTTP/1.1 201 Created
```

### Leer un texto

```bash
curl -s http://localhost:8000/texts?checksum=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08 \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "checksum": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "text": "contenido extraído del PDF...",
  "name": "contrato.pdf",
  "metadata": { "pages": 12, "duration_ms": 431, "producer": "pypdf" },
  "created_at": "2026-10-01T12:34:56.789000Z",
  "updated_at": "2026-10-01T12:34:56.789000Z"
}
```

### Actualizar nombre y metadatos

```bash
curl -i -X PUT "http://localhost:8000/texts?checksum=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "name": "contrato-v2.pdf", "metadata": { "pages": 12, "reviewed": true } }'
# HTTP/1.1 200 OK
```

Los campos ausentes se conservan. Intentar cambiar `text` o `checksum` es
`400 IMMUTABLE_FIELD`.

### Borrar un texto

```bash
curl -i -X DELETE "http://localhost:8000/texts?checksum=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08" \
  -H "Authorization: Bearer $TOKEN"
# HTTP/1.1 200 OK
```

### Sondas

```bash
curl -s http://localhost:8000/health
# {"status":"ok"}

curl -s http://localhost:8000/readyz
# {"status":"ok","mongo":"ok"}
```

`/health` no pregunta a MongoDB a propósito: una caída de la base de datos no
debe sacar el servicio de rotación. `/readyz` sí hace `ping`, y devuelve `503`
con un documento de problema cuando MongoDB no contesta.

### Un error, para ver la forma

```bash
curl -s -X POST http://localhost:8000/texts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text":"hola"}'
```

```json
{
  "type": "/problems/validation_error",
  "title": "Request validation error",
  "status": 400,
  "detail": "...",
  "instance": "/texts",
  "code": "VALIDATION_ERROR"
}
```

## Estructura

Tres capas, hacia dentro (SPEC 2.1): `app/api` (presentación) conoce
`app/services`, que conoce `app/repositories`. Ninguna capa mira hacia fuera.