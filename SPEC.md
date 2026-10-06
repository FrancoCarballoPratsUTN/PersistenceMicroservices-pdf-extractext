# SDD — Persistence Microservice (`pdf-extractext`)

> **Fase 1 (Requisitos) + Fase 2 (Planning) — versión 3.** Documento de diseño
> para revisión humana. **No contiene código de implementación.**
>
> Cambios respecto de v1: checksum pasa a **query param**, se elimina la
> validación de formato del checksum, se **agrega autenticación por Bearer
> token**, y `PUT` adopta semántica estricta *ausente = no enviado*.
>
> Cambios respecto de v2: §2.3 pasa de *"Sin Pydantic"* a *"Pydantic en la
> frontera, no en el dominio"*. El contrato de cable se declara con `BaseModel`
> y OpenAPI se deriva de esos modelos. Inmediatamente después de esa decisión se
> añadieron **tres** reglas que la reemplazan, porque un `BaseModel` en la firma
> de una ruta arrastra consecuencias que la prohibición inicial no tenía: sin
> `response_model` (serializa `datetime` con microsegundos), `Problem` sigue
> siendo un `dict` (su `code` se lee en tiempo de ejecución), y las rutas siguen
> validando a mano (un modelo en la firma reactiva el `422` de FastAPI). Ver
> §2.3 y D-T18.1…D-T18.8 en `tasks/t18-pydantic.md`.

---

## 0. Corrección normativa

El enunciado original citaba **RFC 9475** para Problem Details. Es un error de
numeración: **RFC 9475** es *"Messaging Use Cases and Extensions for STIR"*
(telefonía segura, IETF, dic-2023), sin relación con APIs HTTP.

| | |
|---|---|
| RFC 7807 (2016) | Problem Details for HTTP APIs — *obsoleto* |
| **RFC 9457** (jul-2023) | **Problem Details for HTTP APIs** — vigente |

Los cinco campos pedidos (`type`, `title`, `status`, `detail`, `instance`) son
exactamente los miembros canónicos de **RFC 9457 §3.1**. `code` es un miembro de
extensión, permitido por §3.2, y se mantiene por consistencia con el servicio
hermano `ExtractMicroservice-pdf-extractext`, que ya cita RFC 9457.

RFC secundarias usadas: **RFC 9110** (semántica de códigos de estado) y
**RFC 6750** (`WWW-Authenticate: Bearer`).

---

## 1. Contrato de entrada — análisis del orquestador

**Fuente:** `../Orquestador/orchator-microservices-pdf-extractext` (Go, módulo
`validationmicroservices-pdf-extractext`).

| Archivo | Qué aporta |
|---|---|
| `internal/clients/persistence/client.go` | Rutas, verbos, cuerpos |
| `internal/dto/text.go` | Forma exacta de los cuerpos |
| `internal/models/text.go` | Forma de las respuestas decodificadas |
| `internal/checksum/checksum.go` | Algoritmo del checksum |
| `internal/httpclient/client.go` | Semántica de errores y códigos |
| `internal/httpclient/problem.go` | Estructura que el orquestador parsea |
| `internal/config/config.go` | Base URL, timeouts, límites de tamaño |
| `internal/clients/persistence/client_test.go` | Códigos de estado esperados |

### 1.1 Transporte

| Parámetro | Valor | Origen |
|---|---|---|
| Base URL | `http://localhost:8082` (`PERSISTENCE_BASE_URL`) | `config.go:14` |
| Timeout del cliente | 10 s | `config.go:16` |
| Media type de entrada | `application/json` (POST y PUT) | `client.go:33,40` |
| Autenticación actual | **ninguna** | `httpclient/client.go:24-31` |

### 1.2 Rutas — versión 2 (checksum como query param)

| # | Verbo | Ruta v2 | Ruta v1 (rechazada) | Éxito |
|---|---|---|---|---|
| 1 | `POST` | `/texts` | `/texts` | `201` |
| 2 | `GET` | `/texts?checksum=<valor>` | `/texts/{checksum}` | `200` |
| 3 | `PUT` | `/texts?checksum=<valor>` | `/texts/{checksum}` | `200` |
| 4 | `DELETE` | `/texts?checksum=<valor>` | `/texts/{checksum}` | `200` |

**Por qué query param y no path param.** El checksum **no tiene formato
validado** (decisión Q1): llega como string libre. FastAPI hace *match* de
`{param}` contra un único segmento de path, y uvicorn decodifica `%2F` a `/`
**antes** de rutear. Un checksum con `/` rompería la resolución de ruta y
produciría un `404` silencioso e incorrecto. Con query param el valor viaja en
la *query string*, opaca a las reglas de segmentación de path, y se escapa con
`url.QueryEscape`.

Ventaja adicional: el valor nunca aparece en los logs de acceso del path, lo
que reduce la exposición accidental.

Coste: el cliente Go debe dejar de usar `url.PathEscape` y pasar a
`url.QueryEscape` (`client.go:42,47,52`).

**Parámetro ausente.** Si `checksum` no viene en la query string, es un error de
estructura de la petición → `400 VALIDATION_ERROR` (no `404`).

### 1.3 Cuerpos de entrada

```go
type CreateTextRequest struct {          // POST /texts
    Text     string          `json:"text"`
    Checksum models.Checksum `json:"checksum"`
    Name     string          `json:"name"`
    Metadata map[string]any  `json:"metadata"`
}

type UpdateTextRequest struct {          // PUT /texts?checksum=
    Name     string         `json:"name"`     // -> + omitempty  (ver §1.7)
    Metadata map[string]any `json:"metadata"` // -> + omitempty  (ver §1.7)
}
```

Ejemplo real de `POST /texts`:

```json
{
  "text": "contenido extraído del PDF...",
  "checksum": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
  "name": "contrato.pdf",
  "metadata": { "pages": 12, "duration_ms": 431, "producer": "pypdf" }
}
```

### 1.4 Forma de las respuestas

`internal/models/text.go` — el orquestador decodifica **estrictamente** estos
campos en `GET` y `PUT`. Los cinco son obligatorios; si faltan, quedan en su
valor cero y el orquestador observa datos vacíos.

```json
{
  "checksum":   "9f86d081...",
  "text":       "contenido extraído del PDF...",
  "name":       "contrato.pdf",
  "metadata":   { "pages": 12 },
  "created_at": "2026-10-01T12:34:56.789Z",
  "updated_at": "2026-10-01T12:34:56.789Z"
}
```

`POST` y `DELETE` devuelven `{"message":"OK","checksum":"..."}`. El cliente Go
pasa `out = nil` (`client.go:33,47`), así que no las lee, pero se devuelven por
coherencia y por si el contrato se endurece después.

### 1.5 Semántica del checksum (el `_id` de MongoDB)

`internal/checksum/checksum.go` produce **SHA-256 hexadecimal de 64 caracteres**
sobre el texto extraído. En la práctica ese es siempre el valor, pero
**este servicio no lo valida**: trata el checksum como un string opaco.

- Se usa como **`_id`** de MongoDB → la unicidad la garantiza el índice `_id_`.
- El checksum es **inmutable** (deriva del texto, y el texto no se edita), por eso
  `PUT` sólo toca `name` y `metadata`.
- **Única verificación en la capa de entrada:** que sea un `str`. Y que no esté
  vacío, porque un `_id` vacío es un documento inalcanzable por cualquier vía
  práctica. No se comprueba longitud, alfabeto ni digest.

### 1.6 Semántica de errores (lo que el orquestador exige de verdad)

`internal/httpclient/client.go:39-44` es la única regla dura:

```go
if response.StatusCode < 200 || response.StatusCode >= 300 {
    if problem, parseErr := ParseProblem(response.Body); parseErr == nil {
        return problem            // <- el cuerpo DEBE ser el problema
    }
    return fmt.Errorf("unexpected status %d from %s", ...)
}
```

Consecuencias de diseño:

1. **Todo `status >= 300` debe devolver JSON con `type`, `title`, `status` y
   `detail`.** Cualquier otra cosa degrada a un error genérico en el cliente.
2. `application/problem+json` es correcto (RFC 9457 §3) y el cliente Go lo lee
   sin problema: no negocia el media type.
3. Go ignora campos JSON desconocidos → `instance` y `code` son seguros.
4. `problem.go:9-14` declara sólo 4 campos, y los tests usan servidores mock
   propios: **el orquestador sólo comprueba `status`**, nunca `title` ni
   `detail`. Hay libertad total de redacción.
5. Códigos que el orquestador debe saber manejar: `409` en duplicado,
   `404` en inexistente. `401` es nuevo y requiere decisión de flujo (§4.3).

### 1.7 Cambios requeridos en el orquestador Go

El contrato de entrada **cambia**. Estos son los cambios exactos:

```go
// (1) internal/dto/text.go — vuelve inequívoco "ausente"
type UpdateTextRequest struct {
    Name     string         `json:"name,omitempty"`
    Metadata map[string]any `json:"metadata,omitempty"`
}

// (2) internal/config/config.go — nueva variable obligatoria
//     PERSISTENCE_API_TOKEN  (sin default; si falta, el servicio no arranca)

// (3) internal/httpclient/client.go — Authorization en TODAS las requests
func New(baseURL string, timeout time.Duration, token string) *Client
//     ...
//     request.Header.Set("Authorization", "Bearer "+c.token)

// (4) internal/clients/persistence/client.go — query param en vez de path
const textsPath = "/texts"

func (c *Client) queryPath(checksum models.Checksum) string {
    return textsPath + "?checksum=" + url.QueryEscape(checksum.String())
}
// Update/Delete/FindByChecksum usan c.queryPath(checksum) en vez de
// textsPath + "/" + url.PathEscape(checksum.String())

// (5) (opcional) internal/httpclient/problem.go — agregar el miembro instance
type Problem struct {
    Type     string `json:"type"`
    Title    string `json:"title"`
    Status   int    `json:"status"`
    Detail   string `json:"detail"`
    Instance string `json:"instance"` // <- nuevo, cosmético
}
```

El cambio (1) es el que habilita la semántica estricta de `PUT`: con
`omitempty`, *ausente* pasa a significar inequívocamente *no enviado*, y se
elimina la tabla espuria de `null`/`""` de la v1. Efecto secundario aceptado:
`omitempty` sobre `Name string` impide enviar `name: ""` a propósito, lo cual es
irrelevante en este dominio.

---

## 2. Arquitectura de 3 capas

### 2.1 Principio

Dependencia hacia adentro, en un solo sentido:

```
        ┌──────────────────────────────────────────────┐
        │  CAPA 1 · PRESENTACIÓN / ENTRADA  (app/api)  │
        │  HTTP · auth · middleware · validación        │
        │  NO conoce MongoDB                            │
        └───────────────────┬──────────────────────────┘
                            │  comando tipado
        ┌───────────────────▼──────────────────────────┐
        │  CAPA 2 · LÓGICA DE NEGOCIO  (app/services)  │
        │  orquestación · reglas · decisiones           │
        │  habla con el puerto, no con el driver        │
        └───────────────────┬──────────────────────────┘
                            │  puerto (Protocol)
        ┌───────────────────▼──────────────────────────┐
        │  CAPA 3 · ACCESO A DATOS  (app/repositories) │
        │  MongoDB · índices · mapeo de documentos     │
        └──────────────────────────────────────────────┘
```

Reglas innegociables:

- `app/api/` **nunca** importa `pymongo`. Recibe el `TextService` ya inyectado.
- `app/services/` **nunca** importa `pymongo`. Depende del `Protocol`.
- Solo `app/repositories/` sabe que existe MongoDB.
- Composition root único: `app/main.py`.
- La autenticación vive **enteramente** en la Capa 1: es una preocupación de
  transporte, no de negocio ni de datos. El `TextService` no sabe si hay token.

### 2.2 Validación: qué SÍ y qué NO

| concerns | Capa | Motivo |
|---|---|---|
| Ausencia o invalidez del Bearer token | **1** | Frontera HTTP |
| `Content-Type` distinto de `application/json` | **1** | Frontera HTTP |
| Tamaño del body > límite | **1** | Frontera HTTP |
| JSON mal formado o no es objeto | **1** | Estructura e integridad del JSON |
| Tipos de campo incorrectos | **1** | Estructura e integridad del JSON |
| Campos requeridos ausentes | **1** | Estructura e integridad del JSON |
| `metadata` no es un objeto JSON | **1** | Estructura e integridad del JSON |
| `checksum` ausente en la query string | **1** | Estructura de la petición |
| `checksum` no es `str` o está vacío | **1** | Estructura mínima; sin más |
| **Formato / longitud / alfabeto del checksum** | **ninguna** | **Fuera de alcance (Q1)** |
| Claves de `metadata` con `.` o `$` | **ninguna** | Riesgo aceptado (Q3) |
| **¿El checksum ya existe en MongoDB?** | **2** (consulta a 3) | **Regla de negocio** |
| `text` / `checksum` inmutables | **2** | Regla de negocio |
| Traducir excepción → HTTP | **1** | La capa 3 no conoce HTTP |

> El punto crítico: la **existencia** del checksum jamás se valida en la Capa 1.
> Un `POST` con un checksum bien formado puede ser rechazado con `409`: eso es
> un dato de negocio, no un error de sintaxis. Por eso el `409` **jamás** puede
> ser un `422` de validación.

### 2.3 Pydantic en la frontera, no en el dominio

**Requisito:** Pydantic valida y documenta el contrato de entrada y salida; el
dominio sigue hablando en tipos nativos.

La regla es una frontera, no una prohibición: `pydantic` vive en `app/api/` y
**nadie más**. Cruza hacia dentro sólo como dato ya validado
(`model_dump()` → `dataclass`). `app/services/`, `app/use_cases/` y
`app/repositories/` no importan `pydantic`; lo comprueba `tasks/todo.md`.

| Elemento | Dónde | Se usa |
|---|---|---|
| Modelos de entrada y salida | `app/api/models.py` | `BaseModel` |
| Validación de cuerpos | `app/api/validators/` | `model_validate` |
| Schemas de OpenAPI | `app/api/schemas.py` | `model_json_schema()` |
| Cuerpo de error | `app/api/problem.py` | `dict` plano (ver abajo) |
| Comando de servicio | `app/use_cases/ports.py` | `@dataclass(frozen=True, slots=True)` |
| Serialización de salida | `app/repositories/serialization.py` | `JSONResponse` (ver abajo) |
| Configuración | `app/config.py` | `dataclass` + `os.environ` |

Tres decisiones que el uso de Pydantic **no** cambió, y por qué:

- **No hay `response_model`.** Pydantic serializa `datetime` con microsegundos
  (`.789000Z`), y la salida del servicio es RFC 3339 **con milisegundos**. Los
  modelos sirven para el schema; los bytes los sigue escribiendo
  `serialization.py`.
- **`Problem` sigue siendo un `dict`.** Su `code` es una enumeración leída de
  `ServiceError.__subclasses__()` en tiempo de ejecución, y de una introspección
  en tiempo de ejecución no se deriva un tipo estático. Es el único componente
  de `/openapi.json` escrito a mano, y `tests/integration/api/test_openapi.py`
  compara su `enum` contra `app/errors.py`.
- **Las rutas siguen validando a mano.** Es la única forma de que un cuerpo
  inválido conteste `400 VALIDATION_ERROR` (problem details) y no el `422` que
  FastAPI inventaría. Un modelo en la firma de la ruta reactivaría el `422`.

Consecuencias:

- **Gana el schema de request y response en OpenAPI**, derivado de los mismos
  modelos que validan, de modo que documento y comportamiento no pueden
  separarse: `tests/integration/api/test_openapi.py` compara cada componente
  publicado con `schema_of()`.
- **Se pierde el `422` automático de FastAPI** — nunca hubo: el servicio responde
  `400 VALIDATION_ERROR` a propósito, y el documento declara exactamente los
  estados que cada operación puede contestar.
- **El `detail` de un `400` se construye con vocabulario propio**
  (`invalid <campo>`), nunca con la prosa inglesa de Pydantic
  (`"String should have at least 1 character"`), que además nombra tipos Python
  en un contrato HTTP.


### 2.4 Árbol de directorios

```
PersistenceMicroservices-pdf-extractext/
├── SPEC.md                        ← este documento
├── README.md
├── pyproject.toml                 ← uv + pytest + ruff (como el hermano)
├── uv.lock
├── .env.example
├── .gitignore
├── LICENSE
│
├── app/
│   ├── __init__.py
│   ├── main.py                    ← COMPOSITION ROOT: app factory + lifespan
│   ├── config.py                  ← Settings (dataclass + os.environ)
│   ├── errors.py                  ← ServiceError + 11 subclases
│   │
│   ├── api/                       ══ CAPA 1 · PRESENTACIÓN ══
│   │   ├── __init__.py
│   │   ├── dependencies.py        ← cableado de inyección (repository → service)
│   │   ├── auth.py                ← Bearer token: 401 Unauthorized
│   │   ├── middleware.py          ← request-id, content-type, body-size, CORS, log
│   │   ├── exception_handlers.py  ← Exception → JSONResponse problem+json
│   │   ├── models.py              ← 5 BaseModel: contrato de cable + schemas
│   │   ├── schemas.py             ← OpenAPI: 5 derivados + Problem a mano
│   │   ├── problem.py             ← constructores de cuerpos RFC 9457 (dict)
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── health.py          ← GET /health · GET /readyz  (abiertos)
│   │   │   └── texts.py           ← POST /texts · GET|PUT|DELETE /texts
│   │   └── validators/
│   │       ├── __init__.py
│   │       ├── common.py          ← checked(): BaseModel → 400 VALIDATION_ERROR
│   │       ├── create_text.py     ← dict → CreateTextCommand
│   │       └── update_text.py     ← dict → UpdateTextCommand
│   │
│   ├── services/                  ══ CAPA 2 · LÓGICA DE NEGOCIO ══
│   │   ├── __init__.py
│   │   ├── ports.py               ← TextRepository (Protocol) + dataclasses
│   │   └── text_service.py         ← create / find_by_checksum / update / delete
│   │
│   └── repositories/              ══ CAPA 3 · ACCESO A DATOS ══
│       ├── __init__.py
│       ├── mongodb.py              ← AsyncMongoClient, índice, lifecycle
│       ├── mongo_text_repository.py← implementación del Protocol
│       └── serialization.py        ← documento BSON ⇄ dict de la API
│
└── tests/                         ← replica el layout de app/
    ├── conftest.py
    ├── fakes/
    │   ├── __init__.py
    │   └── fake_text_repository.py ← doble en memoria para unit tests
    ├── unit/
    │   ├── test_config.py
    │   ├── test_errors.py
    │   ├── api/
    │   │   ├── test_problem.py
    │   │   ├── test_auth.py
    │   │   ├── test_validators.py
    │   │   └── test_middleware.py
    │   └── services/
    │       └── test_text_service.py
    └── integration/
        ├── api/
        │   ├── conftest.py
        │   ├── test_health_endpoint.py
        │   ├── test_texts_endpoint.py
        │   ├── test_duplicate_race.py
        │   └── test_error_matrix.py
        └── repositories/
            ├── conftest.py
            └── test_mongo_text_repository.py
```

### 2.5 Configuración

| Variable | Tipo | Def. | Propósito |
|---|---|---|---|
| `APP_NAME` | `str` | `Persistence Microservice` | título OpenAPI |
| `SERVICE_API_TOKEN` | `str` | **— (obligatoria)** | secreto Bearer compartido |
| `MONGO_URI` | `str` | `mongodb://localhost:27017` | conexión |
| `MONGO_DATABASE` | `str` | `pdf_extractext` | base de datos |
| `MONGO_TEXTS_COLLECTION` | `str` | `texts` | colección |
| `MONGO_TIMEOUT_MS` | `int` | `5000` | timeout de operaciones Mongo |
| `MAX_TEXT_BODY_BYTES` | `int` | `10485760` (10 MiB) | límite del body (riesgo B) |

`SERVICE_API_TOKEN` **no tiene default**: si falta o está vacía, la app **no
arranca** y falla al inicializar con un error explícito. Se prefiere fallar
rápido a levantar un servicio sin protección.

El token **nunca** se loguea, ni en debug, ni en el mensaje de error.

Códigos, títulos y URIs de problema **no** son configurables: son parte del
contrato HTTP y viven en `app/errors.py`.

---

## 3. Capa 1 — Presentación

### 3.1 Endpoints

```
ABIERTO   GET    /health    → 200 {"status":"ok"}
ABIERTO   GET    /readyz    → 200 {"status":"ok","mongo":"ok"}   (hace ping)
PROTEGIDO POST   /texts                              Content-Type: application/json
PROTEGIDO GET    /texts?checksum=<valor>
PROTEGIDO PUT    /texts?checksum=<valor>            Content-Type: application/json
PROTEGIDO DELETE /texts?checksum=<valor>
```

`/health` y `/readyz` quedan abiertos para sondas de plataforma (k8s, load
balancers) que no pueden llevar credenciales. `/readyz` revela si Mongo está
alcanzable, que es información aceptable en un entorno de red interna y
consistente con el orquestador, que también expone `/healthz` y `/readyz`
abiertos.

### 3.2 Autenticación

```
Header:  Authorization: Bearer <token>

Algoritmo:
  1. Extraer el esquema; si no es exactamente "Bearer" (case-insensitive)
     → Unauthorized
  2. Extraer el valor; si falta o está vacío → Unauthorized
  3. secrets.compare_digest(valor, SERVICE_API_TOKEN) — tiempo constante
  4. Falso en cualquiera de los pasos → Unauthorized
```

Respuesta de rechazo:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/problem+json
WWW-Authenticate: Bearer
```

```json
{
  "type": "/problems/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Missing or invalid bearer token.",
  "instance": "/texts",
  "code": "UNAUTHORIZED"
}
```

Decisiones de seguridad:

- **`detail` es idéntico** si el token falta, está vacío, tiene otro esquema o
  es incorrecto. Distinguir los casos le daría a un atacante un oráculo para
  enumerar tokens. El log del servidor sí registra el motivo real, sin el valor.
- **`secrets.compare_digest`** evita que el tiempo de respuesta revele cuántos
  caracteres correctos lleva el token.
- **No hay `403`**: es un secreto compartido, no hay roles ni autorización
  granular. Un único `401` basta y no se puede malinterpretar.
- El esquema se compara case-insensitivamente (`bearer` es válido según
  RFC 7235), el **valor** no: los tokens son sensibles a mayúsculas.

### 3.3 Orden de validación

De la más barata a la más costosa, para no gastar trabajo en peticiones que van
a fallar:

```
401 (auth) → 415 (content-type) → 413 (tamaño) → 400 (estructura) → [Capa 2]
```

La autenticación va **primero** a propósito: no se parsea ni se limita el body
de un llamador no autenticado. Es además la primera barrera contra abuso de
recursos.

### 3.4 Flujo de una petición (`POST /texts`)

1. `AuthMiddleware` — valida el Bearer; `401` si falla.
2. `RequestIdMiddleware` — lee o genera `X-Request-ID`, lo devuelve y lo loguea.
3. `ContentTypeMiddleware` — POST/PUT exigen `application/json`; si no, `415`.
4. `BodySizeLimitMiddleware` — `Content-Length` > `MAX_TEXT_BODY_BYTES` → `413`.
5. `await request.json()` → JSON inválido o no-`object` → `400`.
6. `validators/create_text.validate(raw)` — tipado nativo → `CreateTextCommand`
   o `ValidationError` → `400`.
7. `text_service.create(command)` → **Capa 2**.
8. `201` + `Location: /texts?checksum=<escaped>` + `{"message","checksum"}`.
9. Cualquier `ServiceError` lo serializa `exception_handlers` como
   problem details.

---

## 4. Capa 2 — Lógica de negocio

### 4.1 `TextRepository` (puerto)

```python
class TextRepository(Protocol):
    async def checksum_exists(self, checksum: str) -> bool: ...
    async def insert(self, document: StoredText) -> StoredText: ...
    async def get_by_checksum(self, checksum: str) -> StoredText | None: ...
    async def update(self, checksum: str, changes: TextChanges) -> StoredText | None: ...
    async def delete(self, checksum: str) -> bool: ...
    async def ping(self) -> bool: ...
```

`Protocol` estructural en vez de `ABC`: la Capa 2 no importa nada de la Capa 3,
y el `FakeTextRepository` de tests cumple el contrato sin herencia.

### 4.2 Reglas de negocio

| Regla | Excepción | HTTP |
|---|---|---|
| El `checksum` es la identidad y no se reasigna | `ImmutableFieldError` | 400 |
| `text` es inmutable tras la creación | `ImmutableFieldError` | 400 |
| No se puede crear un documento con `checksum` existente | `ChecksumAlreadyExistsError` | **409** |
| Operar sobre un `checksum` inexistente | `TextNotFoundError` | 404 |

### 4.3 Semántica de `PUT` (v2 — estricta)

Con `omitempty` en el lado Go (§1.7), *ausente* es inequívocamente *no enviado*.
Regla final, sin casos ambiguos:

| Valor recibido | Acción |
|---|---|
| `name` presente como `str` (incluido `""`) | sobrescribe `name` |
| `name` ausente o `null` | **sin cambio** |
| `metadata` presente como objeto | **reemplaza** `metadata` completo |
| `metadata` ausente o `null` | **sin cambio** |
| `metadata` presente y no es objeto | `400 VALIDATION_ERROR` |
| `text` o `checksum` presentes en el body | `400 IMMUTABLE_FIELD` |
| body ausente del todo (`{}`) | `400 VALIDATION_ERROR` (no-op no permitido) |

`updated_at` se actualiza siempre; `created_at` se preserva siempre.

La fila de `IMMUTABLE_FIELD` es **defensiva**: el `UpdateTextPayload` de Go no
tiene campo `text`, así que el orquestador no puede dispararla. Existe para
proteger contra un cambio futuro en el cliente o ante otro consumidor.

### 4.4 Respuesta a un `401` en el orquestador

Un `401` desde este servicio significa **error de configuración**, no un problema
de datos: el token está mal cableado, o el servicio está desincronizado con el
orquestador. El orquestador debería **fallar rápido y ruidosamente** (log de
error, sin reintento), no tratarlo como un error de negocio transitorio ni
reintentar en bucle.

---

## 5. Capa 3 — Acceso a datos

### 5.1 Driver

`pymongo` con `AsyncMongoClient` (API asíncrona oficial de PyMongo ≥ 4.9).
`motor` está en modo mantenimiento, por lo que **no** se usa.

### 5.2 Esquema del documento

```json
{
  "_id":        "9f86d081...",   // = checksum, string opaco
  "text":       "contenido extraído…",
  "name":       "contrato.pdf",
  "metadata":   { "pages": 12, "duration_ms": 431 },
  "created_at": ISODate("2026-10-01T12:34:56.789Z"),
  "updated_at": ISODate("2026-10-01T12:34:56.789Z")
}
```

- `_id` **es** el checksum ⇒ la unicidad la garantiza el índice `_id_` de
  MongoDB, no el código de aplicación.
- `created_at` / `updated_at` se guardan como BSON `Date` (ordenables,
  indexables) y se serializan a RFC 3339 UTC con `Z` y milisegundos.
- El mapeo documento ⇄ respuesta vive **solo** en `serialization.py`: el
  servicio nunca ve un `ObjectId` ni un `datetime` crudo.
- Las claves de `metadata` se guardan tal cual llegan. Riesgo aceptado (Q3):
  MongoDB 5+ tolera puntos y `$` en inserciones, pero podrían affect consultas
  con notación de punto en el futuro.

### 5.3 Control de duplicados: doble barrera

Éste es el punto más delicado del diseño. Un `exists()` seguido de un `insert()`
tiene una **condición de carrera**: dos peticiones concurrentes con el mismo
checksum pueden pasar ambas la comprobación y ambas intentar insertar.

Por eso hay **dos** barreras, y la segunda es la que manda:

```
┌─ Barrera 1 ────────────────────────────────────────────────┐
│ exists(checksum) == True  →  409 inmediato, sin escribir    │
│ (cumple el requisito de "interrumpir de inmediato" y       │
│  evita el trabajo de escritura)                            │
└────────────────────────────────────────────────────────────┘
                              │ si no existe
                              ▼
┌─ Barrera 2 ────────────────────────────────────────────────┐
│ insert({_id: checksum, ...})                                │
│   └─ DuplicateKeyError (código 11000)  →  409 idéntico     │
│ (atómica, garantizada por el índice; cierra la carrera)     │
└────────────────────────────────────────────────────────────┘
```

Ambas levantan **la misma** excepción `ChecksumAlreadyExistsError`, así que el
cliente ve un `409` uniforme sea cual sea la que se dispare. La exactitud del
sistema **no depende** del `exists()`: si se eliminara, el `409` seguiría siendo
correcto gracias a la Barrera 2.

### 5.4 Traducción de errores de Mongo

| Excepción del driver | Significado | HTTP resultante |
|---|---|---|
| `DuplicateKeyError` (`11000`) | `_id` ya existe | `409 CHECKSUM_ALREADY_EXISTS` |
| `pymongo.errors.DocumentTooLarge` | documento > 16 MiB | `413 PAYLOAD_TOO_LARGE` |
| `ServerSelectionTimeoutError` | Mongo inalcanzable | `503 PERSISTENCE_ERROR` |
| `ConnectionFailure` | red caída | `503 PERSISTENCE_ERROR` |
| `ExecutionTimeout` | operación lenta | `503 PERSISTENCE_ERROR` |
| `PyMongoError` (resto) | inesperado | `503 PERSISTENCE_ERROR` |

Este mapeo vive en la Capa 3 pero **se expresa con las excepciones de
`app/errors.py`**: la Capa 3 lanza errores de dominio, nunca HTTP. El acceso a
datos no conoce códigos de estado; la traducción ocurre en la Capa 1.

> `RepositoryError` se traduce a `503` y no a `500` porque es infraestructura
> caída: el orquestador puede reintentar. Un `500` le quitaría esa opción.

### 5.5 Arranque

En el `lifespan` de FastAPI: validar que `SERVICE_API_TOKEN` esté presente,
abrir el cliente Mongo, hacer `ping`, y asegurar el índice sobre `updated_at`.
El índice `_id_` es automático en MongoDB y no requiere acción.

---

## 6. Gestión de errores — RFC 9457

### 6.1 Estructura del cuerpo

Media type: **`application/problem+json`** (RFC 9457 §3).

```json
{
  "type":     "/problems/checksum_already_exists",
  "title":    "Checksum already exists",
  "status":   409,
  "detail":   "A document with checksum '9f86d081…' already exists.",
  "instance": "/texts",
  "code":     "CHECKSUM_ALREADY_EXISTS"
}
```

| Miembro | Regla aplicada |
|---|---|
| `type` | URI relativa `/problems/<snake_case>`, estable y documentada |
| `title` | Resumen corto y **genérico** de la clase de problema. Idéntico para todas las ocurrencias del mismo error |
| `status` | Código HTTP, repetido en el cuerpo para que sea autocontenido |
| `detail` | Explicación de **esta** ocurrencia. Puede incluir el checksum. **Nunca** stack traces ni mensajes del driver |
| `instance` | **Ruta + query** que disparó el error, no la URL completa: no se filtra el host ni el valor del checksum en los logs |
| `code` | Extensión estable y legible por máquina (RFC 9457 §3.2) |

`title` nunca incluye valores variables: si lo hiciera, los clientes no podrían
comparar errores por `title`. La información variable va en `detail`.

### 6.2 Matriz de errores planificada

| `code` | HTTP | `type` | `title` | Capa | Condición |
|---|---|---|---|---|---|
| **`CHECKSUM_ALREADY_EXISTS`** | **409** | `/problems/checksum_already_exists` | `Checksum already exists` | **2** | **`POST /texts` con checksum existente (Barrera 1 o 2)** |
| `TEXT_NOT_FOUND` | 404 | `/problems/text_not_found` | `Text not found` | 2 | `GET`/`PUT`/`DELETE` sobre checksum inexistente |
| **`UNAUTHORIZED`** | **401** | `/problems/unauthorized` | `Unauthorized` | 1 | **Bearer ausente, mal formado o inválido** |
| `VALIDATION_ERROR` | 400 | `/problems/validation_error` | `Request validation error` | 1 | JSON malformado, no-objeto, tipos erróneos, campo requerido ausente, `checksum` fuera de la query |
| `IMMUTABLE_FIELD` | 400 | `/problems/immutable_field` | `Immutable field` | 1 | `PUT` con `text` o `checksum` en el body |
| `PAYLOAD_TOO_LARGE` | 413 | `/problems/payload_too_large` | `Payload too large` | 1 / 3→2 | body > `MAX_TEXT_BODY_BYTES`, o documento > 16 MiB |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | `/problems/unsupported_media_type` | `Unsupported media type` | 1 | `Content-Type` ≠ `application/json` |
| `METHOD_NOT_ALLOWED` | 405 | `/problems/method_not_allowed` | `Method not allowed` | 1 | Verbo no soportado en la ruta |
| `NOT_FOUND` | 404 | `/problems/not_found` | `Resource not found` | 1 | Ruta inexistente |
| `PERSISTENCE_ERROR` | 503 | `/problems/persistence_error` | `Persistence unavailable` | 3→2 | MongoDB inalcanzable o error de servidor |
| `INTERNAL_ERROR` | 500 | `/problems/internal_error` | `Internal server error` | 1 | Excepción no prevista (catch-all) |

`PAYLOAD_TOO_LARGE` y `PERSISTENCE_ERROR` aparecen con dos orígenes porque
pueden producirse en capas distintas; el cuerpo de la respuesta es idéntico en
ambos casos, así que el cliente no necesita saber dónde se originó.

### 6.3 El caso `409` en detalle

**Disparador.** `POST /texts` cuyo `checksum` ya está en MongoDB.

**Detección.** Barrera 1 (`checksum_exists`) o Barrera 2 (`DuplicateKeyError`),
según cuál se dispare primero bajo concurrencia.

**Respuesta:**

```http
HTTP/1.1 409 Conflict
Content-Type: application/problem+json
X-Request-ID: 3f2a91c8e7b4d05a
```

```json
{
  "type": "/problems/checksum_already_exists",
  "title": "Checksum already exists",
  "status": 409,
  "detail": "A text document with checksum '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08' already exists.",
  "instance": "/texts",
  "code": "CHECKSUM_ALREADY_EXISTS"
}
```

**Por qué 409 y no otro código:**

| Código | ¿Correcto? | Motivo |
|---|---|---|
| **`409 Conflict`** | **Sí** | RFC 9110 §15.5.10: "conflict with the current state of the target resource". El recurso ya existe. Es además lo que el orquestador comprueba |
| `422 Unprocessable Content` | No | El JSON es perfectamente válido; la unicidad es regla de negocio, no de sintaxis |
| `400 Bad Request` | No | El cliente no cometió un error sintáctico |
| `412 Precondition Failed` | No | No hay precondición `If-None-Match` en juego |
| `200 OK` idempotente | No | El requisito es interrumpir y señalar el conflicto; el orquestador espera `409` |

**Efecto en la base de datos: ninguno.** No se escribe ni se modifica nada.

---

## 7. Diagrama de flujo conceptual

```
╔════════════════════════╗
║  ORQUESTADOR (Go)      ║  POST /texts  {"text","checksum","name","metadata"}
║  :8080                 ║  PERSISTENCE_BASE_URL → http://localhost:8082
╚═══════════╤════════════╝
            │  Authorization: Bearer <SERVICE_API_TOKEN>
            │  Content-Type: application/json
            │  X-Request-ID: 3f2a91c8e7b4d05a
            ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ CAPA 1 · PRESENTACIÓN                app/api/                       ┃
┃                                                                           ┃
┃  ① auth.py ── Bearer presente y correcto?                             ┃
┃                    ├── NO ──► 401 Unauthorized                        ┃
┃                    │        (WWW-Authenticate: Bearer)                 ┃
┃                    ▼ SÍ                                                 ┃
┃  ② middleware: X-Request-ID (eco) · Content-Type · límite de tamaño  ┃
┃                    ├── Content-Type ≠ json ───────► 415 ─────────────┤
┃                    ├── body > 10 MiB ─────────────► 413 ─────────────┤
┃                    ▼                                                    ┃
 ┃  ③ await request.json()              ← dict crudo, aún sin validar      ┃
 ┃                    ├── JSON inválido / no es dict ──► 400 ────────────┤
 ┃                    ▼                                                    ┃
 ┃  ④ validators/create_text.py        ← CreateTextBody.model_validate()  ┃
 ┃                    │  · text      : str, minLength 1                   ┃
 ┃                    │  · checksum  : str, minLength 1                   ┃
 ┃                    │                (SIN validación de formato)        ┃
 ┃                    │  · name      : str o null                        ┃
 ┃                    │  · metadata  : dict[str, Any] o null             ┃
 ┃                    │                                                ┃
 ┃                    └── viola una regla ────────────► 400 ────────────┤
 ┃                    ▼                                                 ┃
 ┃         CreateTextBody.model_dump() → CreateTextCommand (frozen)       ┃
╞════════════════════╪═══════════════════════════════════════════════════╡
            │            ╎  ◄── la Capa 1 NO consulta MongoDB ──►
            ▼            ╎
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ CAPA 2 · LÓGICA DE NEGOCIO             app/services/text_service.py   ┃
┃                                                                           ┃
┃         TextService.create(command)                                     ┃
┃                    │                                                    ┃
┃                    ▼                                                    ┃
┃  ┌─ BARRERA 1 ── repo.checksum_exists(checksum) ────────────────────┐  ┃
┃  │        │                                                           │  ┃
┃  │        ├── SÍ ──► raise ChecksumAlreadyExistsError ────────► 409 │  ┃
┃  │        │        (interrupción inmediata, sin escritura)          │  ┃
┃  │        ▼ NO                                                        │  ┃
┃  └───────────────────────────────────────────────────────────────────┘  ┃
┃                    ▼                                                    ┃
┃  ┌─ BARRERA 2 ── repo.insert(doc)  ◄── MongoDB                       ┐  ┃
┃  │        │                             ▲                            │  ┃
┃  │        ├── DuplicateKeyError (11000) ─┘ ──► raise ────────► 409  │  ┃
┃  │        │      (salto atómico del índice _id_;                     │  ┃
┃  │        │       cierra la carrera del exists)                      │  ┃
┃  │        ├── DocumentTooLarge ──────────────► raise ────────► 413  │  ┃
┃  │        ├── ServerSelectionTimeout / … ────► raise ────────► 503  │  ┃
┃  │        ▼                                                         │  ┃
┃  └───────── StoredText (con _id, created_at, updated_at) ────────────┘  ┃
╞════════════════════╪═══════════════════════════════════════════════════╡
            │            ╎
            ▼            ╎  ◄── ÚNICA capa que conoce pymongo ──►
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ CAPA 3 · ACCESO A DATOS                app/repositories/              ┃
┃                                                                           ┃
┃  mongo_text_repository.insert()                                         ┃
┃      doc = {                                                            ┃
┃        _id:       command.checksum,   ← ¡el checksum ES el _id!        ┃
┃        text:      command.text,                                       ┃
┃        name:      command.name,                                       ┃
┃        metadata:  command.metadata or {},                            ┃
┃        created_at: now (BSON Date),                                   ┃
┃        updated_at: now (BSON Date),                                   ┃
┃      }                                                                  ┃
┃      result = await collection.insert_one(doc)                        ┃
┃                    │                                                   ┃
┃                    ▼                                                   ┃
┃           ┌──────────────────┐                                         ┃
┃           │     MongoDB      │  textos                                ┃
┃           │   índice _id_    │  ← la unicidad la garantiza la BD,      ┃
┃           └──────────────────┘    no el código de aplicación           ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
            │
            │  Los errores de cualquier capa ascienden hasta
            │  exception_handlers (Capa 1), que los serializa
            │  como application/problem+json
            ▼
      201 Created
      Location: /texts?checksum=9f86d081...
      { "message": "OK", "checksum": "9f86d081..." }
```

### 7.1 Recorrido de los otros tres verbos

| Verb | Capa 1 | Capa 2 | Capa 3 | Resultado |
|---|---|---|---|---|
| `GET /texts?checksum=c` | auth (401) · `checksum` en query (400) | `get_by_checksum` | `find_one({_id: c})` | `200` + `models.Text` · o `404` si `None` |
| `PUT /texts?checksum=c` | auth (401) · query (400) · body (400) | decide qué campos cambian (§4.3) | `find_one_and_update($set, return_document=AFTER)` | `200` + documento actualizado · o `404` |
| `DELETE /texts?checksum=c` | auth (401) · query (400) | — | `delete_one({_id: c})` | `200` `{"message","checksum"}` · `404` si `deleted_count == 0` |

`GET` y `PUT` **sí** decodifican la respuesta en Go (`client.go:41,51`), así que
esos dos cuerpos **deben** incluir los seis campos de `models.Text` o el
orquestador los observará con valores vacíos.

---

## 8. Verificación de compatibilidad con el orquestador

Los tests de `internal/clients/persistence/client_test.go` fijan el contrato
desde el lado del consumidor. Esta tabla es la checklist de contrato; los tests
deben reescribirse en el cliente Go para las rutas con query param.

| Comportamiento exigido por el cliente | Cubierto por |
|---|---|
| `POST /texts` con los 4 campos, cuerpo `application/json` → `2xx` | T10, T16 |
| `POST` duplicado → `409` + body parseable como problem | T8, T11, T16 |
| `PUT /texts?checksum=c` → respuesta decodificable con `checksum` y `name` | T13, T16 |
| `PUT` sobre inexistente → `404` + problem | T13, T16 |
| `DELETE /texts?checksum=c` → `2xx` | T14, T16 |
| `GET /texts?checksum=c` → `checksum`, `text`, `name`, `metadata` | T12, T16 |
| `GET` sobre inexistente → `404` + problem | T12, T16 |
| Fallo de transporte → error de transporte, no un `Problem` falso | T3 |
| **Todo `status >= 300` devuelve body con los 4 campos mínimos** (regla de `httpclient/client.go:39`) | T16 |
| **`401` cuando falta el token** | T5, T16 |
| `created_at`/`updated_at` parseables por `time.Time` de Go | T12 |

---

## 9. Fuera de alcance

- Autenticación de usuario final, Refresh tokens, rotación de secretos.
- `403` / autorización granular por rol o por recurso.
- Listado de documentos (`GET /texts` sin filtro) y paginación.
- Reindexado, migraciones de esquema, versionado de documentos.
- Retries, circuit breaker o backoff (responsabilidad del cliente).
- Replicación, sharding, tuning de la colección.
- Pruebas de carga / rendimiento sostenido.
- Validación de formato del checksum y sanitización de claves de `metadata`.

---

## 10. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Condición de carrera entre `exists()` e `insert()` | **Alto** | Doble barrera (§5.3): el `409` depende del índice `_id_`, no del `exists()`; T11 lo verifica |
| Token ausente en el entorno → servicio sin protección | **Alto** | Sin default: la app **no arranca** (§2.5). Test de arranque |
| Token filtrado en logs o mensajes de error | **Alto** | `detail` genérico; el valor nunca se loguea; comparación en tiempo constante |
| Documento > 16 MiB (límite de BSON) | **Alto** | Límite de entrada a 10 MiB + `DocumentTooLarge → 413` |
| Sin validación de checksum → `_id` inesperado | Medio | Se acepta string opaco; SHA-256 hex es el único productor real; el query param elimina el problema de routing |
| Claves de `metadata` con `.` o `$` | Medio | Riesgo aceptado explícitamente (Q3); no afecta la inserción |
| `pydantic` filtrándose al dominio | Medio | La regla es `app/api/` y nadie más (§2.3); un grep lo verifica, como ya se hace con `pymongo` |
| Prosa inglesa de Pydantic en el `detail` de un `400` | Medio | El `detail` se construye con vocabulario propio (§2.3); hay test que lo fija |
| OpenAPI y validación divergen | Bajo | Ambos salen del mismo modelo: `test_openapi.py` compara cada componente publicado con `schema_of()` |
| Sondas de plataforma sin credenciales | Bajo | `/health` y `/readyz` quedan abiertos a propósito (§3.1) |
| Divergencia futura del contrato con el orquestador | Medio | §8 como checklist; los tests del cliente Go son la primera línea de defensa |
| Desalineación al cablear el token en Go | Medio | Fallo rápido en arranque + `401` inequívoco; el orquestador debe fallar ruidosamente (§4.4) |

---

## 11. Decisiones tomadas

| # | Decisión | Elegida | Consecuencia |
|---|---|---|---|
| Q1 | Validar formato del checksum | **No** | Se elimina `INVALID_CHECKSUM` y `CHECKSUM_PATTERN`. Sólo se verifica existencia en BD |
| Q2 | `PUT` con `text`/`checksum` | **Rechazar** `400 IMMUTABLE_FIELD` | No se ignora en silencio |
| Q3 | Claves de `metadata` con `.`/`$` | **Se aceptan** | Riesgo asumido; no hay sanitización |
| Q4 | Autenticación del orquestador | **Sí — Bearer token** | `SERVICE_API_TOKEN` obligatorio; fase propia en el plan |
| Q5 | `GET /texts` (listado) | **No** | Sólo `GET /texts?checksum=` |
| Q6 | Ubicación del checksum | **Query param** | `?checksum=`; el cliente Go pasa de `PathEscape` a `QueryEscape` |
| Q7 | `PUT` con campo ausente | **Sin cambio** | `omitempty` en Go hace la distinción inequívoca |
| Q8 | `metadata` | **Dict libre** | Como el contrato actual; sin cambios en el cliente |
| Q9 | Pydantic en el contrato (v2 lo prohibía) | **Sí, sólo en `app/api/`** | OpenAPI se deriva de los modelos; el dominio sigue en dataclasses; sin `response_model` ni `Problem(BaseModel)` (§2.3) |

---

## 12. Convenciones

- **Prosa de `SPEC.md` y `tasks/*.md`: español.**
- **Código, identificadores y docstrings: inglés** (igual que
  `ExtractMicroservice-pdf-extractext`).
- Docstrings estilo Google en toda función y clase pública.
- Type hints en todas las firmas.
- `ruff`, `line-length = 88`, select `["E","F","W","I","B","UP","SIM","C4"]`.
- Tests con `pytest`; cobertura `--cov=app --cov-fail-under=85`.
- Gestor de paquetes: `uv` (`pyproject.toml` + `uv.lock`).
- Comandos: `uv sync` · `uv run pytest` · `uv run ruff check .` · `uv run ruff format .`
