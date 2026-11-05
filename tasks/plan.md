# Implementation Plan: Persistence Microservice (`pdf-extractext`)

> Fase 2 del SDD, **versión 2**. Diseño completo en [`../SPEC.md`](../SPEC.md).
> Este archivo es el plan de ejecución.
>
> **Estado:** pendiente de aprobación. No se ha escrito código.
>
> **v3 (remediación post-code-review):** el release candidate fue **rechazado**.
> El plan de remediación **R1–R20** está al final de este archivo. La sección v2
> se conserva como historial de implementación.

## Overview

Microservicio FastAPI que persiste documentos de texto extraídos en MongoDB,
usando el checksum recibido como `_id`. Consume el contrato del orquestador Go en
`POST /texts` y `GET|PUT|DELETE /texts?checksum=`. Arquitectura estricta de 3
capas, autenticación por Bearer token, validación de entrada y documento OpenAPI
con Pydantic **en la frontera** (`app/api/`), RFC 9457 para todo error, y
detección de checksum duplicado con doble barrera (`exists()` + índice `_id_`).

## Changes From v1

| Cambio | Detalle |
|---|---|
| Checksum a **query param** | `?checksum=<valor>` en vez de `/texts/{checksum}`. El cliente Go pasa de `url.PathEscape` a `url.QueryEscape` |
| **Sin** validación de formato del checksum | Se elimina `INVALID_CHECKSUM` y `CHECKSUM_PATTERN` (Q1) |
| **Autenticación agregada** | Bearer token compartido; fase propia (Q4) |
| `PUT` estricto | `ausente = no enviado`; habilitada por `omitempty` en Go (Q7) |
| Sin listado | Sólo `GET /texts?checksum=` (Q5) |
| Matriz de errores | 13 → **11** filas |
| Plan de tareas | 15 → **17** tareas |

## Deviations Recorded During Execution

Decisiones tomadas mientras se ejecutaba T1, con su motivo. Se acumulan aquí
para que la desviación sea visible en vez de quedar implícita en el código.

| # | Desviación | Plan original | Motivo |
|---|---|---|---|
| D1 | `addopts = "--cov=app"` y el umbral pasa a invocarse explícitamente | `addopts = "--cov=app --cov-fail-under=85"` | Con el umbral en `addopts`, **todo** run incremental falla hasta que hay suficientes tests, lo que rompe el ciclo RED→GREEN de TDD. El gate se sigue aplicando en cada checkpoint: `uv run pytest --cov-fail-under=85` |
| D2 | Se agrega `pytest-asyncio` con `asyncio_mode = "auto"` | Solo `pytest`, `pytest-cov`, `httpx`, `ruff` | El servicio y el repositorio son `async` (usan `AsyncMongoClient`). El hermano Extract es síncrono y no lo necesitaba. Sin esto los tests de Capa 2 y 3 no se pueden escribir |
| D3 | `extend-exclude = ["*.md"]` en ruff | No estaba | `ruff format` reescribía los bloques de código de `SPEC.md`. Los snippets son ilustrativos, no fuente: formatearlos ensucia el documento de diseño |
| D4 | `uv.lock` se versiona (se destapa en `.gitignore`) | El `.gitignore` heredado lo tenía comentado | Es una aplicación, no una librería. Sin el lock, dos instalaciones resuelven dependencias distintas |
| D5 | `target-version = "py314"` | El hermano usa `py310` con `requires-python = ">=3.14"` (inconsistente) | Se alinea el target de ruff con el intérprete real declarado |
| D6 | AC de T1: "pytest sale 0" → "`--collect-only` colecta 0" | `uv run pytest` sale 0 con 0 tests | Imposible: pytest devuelve exit 5 (*no tests collected*) por diseño. El AC estaba mal escrito |

## Architecture Decisions

- **3 capas con dependencia hacia adentro.** `api → services → repositories`.
  `app/api/` nunca importa `pymongo`; `app/services/` tampoco. Sólo
  `app/repositories/` lo conoce. Composition root único en `app/main.py`.

- **El checksum ES el `_id`.** La unicidad la garantiza el índice `_id_` de
  MongoDB, no una comprobación en el código. Consecuencia: `text` y `checksum`
  son inmutables y `PUT` sólo toca `name` y `metadata`.

- **Doble barrera anti-duplicados.** Barrera 1 = `checksum_exists()` (cumple el
  requisito de interrumpir de inmediato y evita el trabajo de escritura).
  Barrera 2 = captura de `DuplicateKeyError` en el `insert`. **Ambas lanzan la
  misma excepción**, así que el `409` es idéntico sea cual sea la que se dispare,
  y la exactitud **no depende** del `exists()`. Ver SPEC §5.3.

- **`409 Conflict` para checksum duplicado.** RFC 9110 §15.5.10: el recurso ya
  existe. *No* `422`: el JSON es válido, la unicidad es regla de negocio. *No*
  `400`: el cliente no cometió un error sintáctico. Es además el código que el
  orquestador comprueba explícitamente.

- **Query param y no path param.** Al no validarse el formato del checksum, un
  valor con `/` rompería el matching de `{param}` en FastAPI (uvicorn decodifica
  `%2F` antes de rutear) y produciría un `404` silencioso. El query param
  elimina esa clase de bug. Beneficio extra: el checksum no aparece en los logs
  de acceso del path.

- **Autenticación en la Capa 1, con `detail` genérico y comparación en tiempo
  constante.** `secrets.compare_digest` evita que el tiempo de respuesta revele
  cuántos caracteres correctos lleva el token. El `detail` es idéntico si el
  token falta, está vacío, tiene otro esquema o es incorrecto: distinguirlo le
  daría un oráculo al atacante. Sin `403` — es un secreto compartido, no hay
  roles. `/health` y `/readyz` quedan abiertos para sondas de plataforma.

- **Pydantic en la frontera, no en el dominio (T18).** `app/api/models.py`
  declara el contrato de cable con `BaseModel`; los validadores usan
  `model_validate()` y OpenAPI se deriva con `model_json_schema()`, de modo que
  documento y validación son la misma declaración. `pydantic` no aparece en
  `app/services/`, `app/use_cases/`, `app/repositories/` ni `app/config.py`: hacia
  dentro cruza como dato ya validado (`model_dump()` → `dataclass` frozen). Tres
  reglas que acompañan a la decisión: **sin `response_model`** (Pydantic
  serializa `datetime` con microsegundos y la salida es RFC 3339 con
  milisegundos), **`Problem` sigue siendo un `dict`** (su `code` se lee de
  `ServiceError.__subclasses__()` en tiempo de ejecución, así que no hay tipo
  estático que derivar) y **las rutas siguen validando a mano**, que es lo único
  que mantiene el `400 VALIDATION_ERROR` en vez del `422` de FastAPI. Sustituye a
  la prohibición de v2, cuyo coste era escribir los schemas a mano (T17).

- **Errores de dominio llevan metadatos de cable.** `app/errors.py` declara
  `status`, `code`, `type_uri` y `title` como `ClassVar`. El handler traduce de
  forma declarativa: no hay escalera de `if/else` en el controlador.

- **La Capa 3 no conoce HTTP.** Lanza excepciones de dominio
  (`DuplicateKeyError → ChecksumAlreadyExistsError`, `DocumentTooLarge →
  PayloadTooLargeError`, `ServerSelectionTimeoutError → PersistenceError`). La
  traducción a `409`/`413`/`503` ocurre en la Capa 1.

- **`503` para fallos de Mongo, no `500`.** Es infraestructura caída: el
  orquestador puede reintentar. Un `500` le quitaría esa opción.

- **Fechas RFC 3339 UTC con `Z` y milisegundos.** `time.Time` de Go requiere
  RFC 3339. Se guarda BSON `Date` (ordenable) y se serializa en
  `serialization.py`.

- **`instance` = ruta + query, sin el valor del checksum.** Evita filtrar el
  host y evita que el checksum quede expuesto en los logs del cliente.

- **`SERVICE_API_TOKEN` sin default.** Si falta, la app no arranca. Se prefiere
  fallar rápido a levantar un servicio sin protección.

- **uv** como gestor de paquetes, igual que el servicio hermano.

## Dependency Graph

```
T1 scaffolding
 ├─► T2 errores (11 subclases) ──► T3 problem + handlers
 └─► T4 config + token ──► T5 auth middleware (401)
                                 │
T4 ──► T6 lifecycle Mongo        │
T2 ──► T7 puerto + Fake ────────┤
                                 ▼
                          T8 repo escritura
                                 ▼
                          T9 TextService.create
                                 ▼
                          T10 POST /texts + validators
                                 ▼
                          T11 test de carrera 409  ◄── CHECKPOINT CRÍTICO
                                 ▼
                    T12 GET ──► T13 PUT ──► T14 DELETE
                                 ▼
                          T15 middleware ──► T16 matriz de 11 errores
                                 ▼
                          T17 OpenAPI + README + cobertura
```

## Task List

### Phase 1: Foundation

- [ ] **T1: Project scaffolding** — `pyproject.toml` (uv, pytest-cov, ruff), árbol
      de paquetes, `.env.example`, `.gitignore`, `tests/conftest.py`.
- [ ] **T2: Jerarquía de errores** — `app/errors.py` con `ServiceError` base y las
      11 subclases, cada una con `status` / `code` / `type_uri` / `title`.
- [ ] **T3: Problem details + exception handlers** — `app/api/problem.py` y
      `app/api/exception_handlers.py` (RFC 9457, `application/problem+json`).

### Checkpoint: Foundation
- [ ] `uv sync` limpio; `uv run ruff check .` sin violaciones
- [ ] `uv run pytest` colecta
- [ ] Las 11 excepciones exponen el `status`/`code`/`type_uri` correctos
- [ ] Un `ServiceError` lanzado desde donde sea se serializa como problem details válido
- [ ] **Revisión humana antes de continuar**

### Phase 2: Autenticación

- [ ] **T4: Config + token** — `app/config.py` (dataclass sobre `os.environ`),
      `SERVICE_API_TOKEN` obligatoria sin default, fallo explícito al arrancar.
- [ ] **T5: Middleware de autenticación** — `app/api/auth.py`: Bearer,
      `secrets.compare_digest`, `401` con `detail` genérico y
      `WWW-Authenticate: Bearer`.

### Checkpoint: Auth
- [ ] Sin `SERVICE_API_TOKEN` la app **no arranca**, con error explícito
- [ ] Token ausente, vacío, con esquema distinto o incorrecto ⇒ `401` en los 4 casos
- [ ] El `detail` es **idéntico** en los 4 casos (sin oráculo)
- [ ] El token nunca aparece en logs ni en el cuerpo de respuesta
- [ ] `/health` y `/readyz` siguen accesibles sin token
- [ ] **Revisión humana antes de continuar**

### Phase 3: Core vertical slice — Create + duplicados

- [ ] **T6: Lifecycle de Mongo** — `app/repositories/mongodb.py`: cliente
      `AsyncMongoClient`, timeout, `ping`, índice sobre `updated_at`.
- [ ] **T7: Puerto + doble de test** — `app/services/ports.py` (`Protocol` +
      dataclasses) y `tests/fakes/fake_text_repository.py`.
- [ ] **T8: Repositorio Mongo — escritura** — `checksum_exists` e `insert`, con
      `DuplicateKeyError → ChecksumAlreadyExistsError` (Barrera 2) y
      `DocumentTooLarge → PayloadTooLargeError`.
- [ ] **T9: TextService.create** — orquestación: comando → `exists()` → `insert()`.
- [ ] **T10: Endpoint `POST /texts`** — `validators/create_text.py`,
      `validators/common.py`, `routers/texts.py`, `dependencies.py`, `main.py`.
- [ ] **T11: Test de carrera bajo concurrencia** — N peticiones paralelas con el
      mismo checksum ⇒ exactamente 1 `201` y N-1 `409`.

### Checkpoint: Core slice ★ el más importante del plan
- [ ] `POST /texts` devuelve `201` + `Location` + `{"message","checksum"}`
- [ ] Segundo `POST` con el mismo checksum devuelve `409` con el cuerpo de SPEC §6.3
- [ ] **T11 pasa:** bajo concurrencia hay exactamente un insert en MongoDB
- [ ] El `409` se emite tanto si salta la Barrera 1 como si salta la Barrera 2
- [ ] `pymongo` no se importa en `app/api/` ni en `app/services/`
- [ ] Un body con `checksum` de formato arbitrario (no-hex) se acepta y persiste
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa
- [ ] **Revisión humana antes de continuar**

### Phase 4: Verbos restantes

- [ ] **T12: `GET /texts?checksum=`** — `serialization.py` con RFC 3339 UTC `Z` y
      milisegundos; `400` si falta el query param; `404` si no existe.
- [ ] **T13: `PUT /texts?checksum=`** — `validators/update_text.py` con la
      semántica *ausente = no enviado*; `400 IMMUTABLE_FIELD`; `404`.
- [ ] **T14: `DELETE /texts?checksum=`** — `200` + `{"message","checksum"}`;
      `404` si `deleted_count == 0`.

### Checkpoint: CRUD completo
- [ ] Los 4 verbos funcionan end-to-end contra MongoDB real
- [ ] `GET` y `PUT` devuelven los **seis** campos de `models.Text`
- [ ] `created_at` se preserva en `PUT`; `updated_at` se actualiza
- [ ] `PUT` con `{}` ⇒ `400`; `PUT` con `{"name":"x"}` no borra `metadata`
- [ ] Checklist de contrato SPEC §8 satisfecha
- [ ] **Revisión humana antes de continuar**

### Phase 5: Endurecimiento y cierre

- [ ] **T15: Middleware** — eco de `X-Request-ID`, `415`, `413`, CORS, log de
      acceso. Orden: `401 → 415 → 413 → 400`.
- [ ] **T16: Matriz de errores completa** — test parametrizado sobre las 11 filas
      de SPEC §6.2, verificando `status` y `code`.
- [ ] **T17: OpenAPI, README y cobertura** — schemas a mano con `openapi_extra`,
      README operativo, cobertura ≥ 85%.

### Checkpoint: Complete
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa
- [ ] `uv run ruff check .` y `uv run ruff format .` limpios
- [ ] Las 11 filas de la matriz verificadas por test, sin `skip` ni `xfail`
- [ ] Checklist de contrato SPEC §8 en verde
- [ ] Criterios de éxito del SPEC cumplidos
- [ ] **Listo para revisión final del humano**

## Task Detail

### T1: Project scaffolding

**Description:** Base del proyecto replicando las convenciones de
`ExtractMicroservice-pdf-extractext`: `uv`, `pytest` + `pytest-cov`, `ruff`
(`line-length = 88`, select `["E","F","W","I","B","UP","SIM","C4"]`), layout de
tests espejo de `app/`. Agrega `pytest-asyncio` porque las capas 2 y 3 son async
(desviación D2). Los `__init__.py` de cada capa llevan docstring que **encoda la
dirección de dependencias**, que es la restricción central del diseño.

**Acceptance criteria:**
- [ ] `uv sync` completa y crea `uv.lock` versionado (D4)
- [ ] `uv run pytest --collect-only` colecta 0 items leyendo la config de
      `pyproject.toml` (D6: pytest devuelve exit 5 con 0 tests, por diseño)
- [ ] `uv run ruff check .` y `uv run ruff format --check .` pasan
- [ ] `.env.example` documenta las 7 variables de SPEC §2.5, con
      `SERVICE_API_TOKEN` marcada como obligatoria y sin valor por defecto
- [ ] `app.api`, `app.services` y `app.repositories` importan, y ninguno arrastra
      `pymongo`

**Verification:**
- [ ] `uv sync` · `uv run ruff check .` · `uv run ruff format --check .`
- [ ] `uv run pytest --collect-only`
- [ ] `uv run python -c "import app.api, app.services, app.repositories"`
- [ ] Manual: contrastar `.env.example` contra SPEC §2.5

**Dependencies:** None
**Files:** `pyproject.toml`, `.env.example`, `.gitignore`, `app/__init__.py`,
`app/api/__init__.py`, `app/services/__init__.py`, `app/repositories/__init__.py`,
`app/api/routers/__init__.py`, `app/api/validators/__init__.py`,
`tests/conftest.py`, 8 × `tests/**/__init__.py`
**Scope:** Medium

---

### T2: Jerarquía de errores

**Description:** `app/errors.py` con `ServiceError(Exception)` que lleva `status`,
`code`, `type_uri`, `title` como `ClassVar` y `detail` por instancia, más las 11
subclases de SPEC §6.2. Son el vocabulario compartido por las tres capas: la
Capa 3 las lanza, la Capa 2 decide, la Capa 1 traduce.

**Acceptance criteria:**
- [ ] Las 11 subclases existen con `status`/`code`/`type_uri`/`title` correctos
- [ ] `ChecksumAlreadyExistsError.status == 409`, `TextNotFoundError.status == 404`,
      `UnauthorizedError.status == 401`
- [ ] `ServiceError("detalle")` expone `.detail` y `str(exc)` lo incluye

**Verification:**
- [ ] `uv run pytest tests/unit/test_errors.py`
- [ ] Manual: contrastar la tabla de subclases contra SPEC §6.2

**Dependencies:** T1
**Files:** `app/errors.py`, `tests/unit/test_errors.py`
**Scope:** Small

---

### T3: Problem details + exception handlers

**Description:** `app/api/problem.py` construye el cuerpo como `dict` plano
(`type`, `title`, `status`, `detail`, `instance`, `code`) con `Content-Type:
application/problem+json`. `app/api/exception_handlers.py` registra handlers para
`ServiceError`, `StarletteHTTPException` (cubre 404/405) y `Exception` (catch-all
`500`). `detail` por defecto genérico; el detalle real sólo va al log del servidor.

**Acceptance criteria:**
- [ ] Todo error sale con `Content-Type: application/problem+json` y los 6 campos
- [ ] `instance` es ruta + query **sin el valor del checksum**
- [ ] Ninguna excepción interna se filtra: `detail` no contiene mensajes de driver
      ni stack traces
- [ ] `title` no incluye valores variables — el mismo error da el mismo `title`

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_problem.py`
- [ ] Manual: lanzar un `ServiceError` desde un test y revisar el body

**Dependencies:** T2
**Files:** `app/api/problem.py`, `app/api/exception_handlers.py`,
`tests/unit/api/test_problem.py`
**Scope:** Small

---

### T4: Config + token

**Description:** `app/config.py` con `Settings` como `@dataclass(frozen=True)` leído
de `os.environ` con los defaults de SPEC §2.5. `SERVICE_API_TOKEN` **no tiene
default**: si falta o está vacía, `get_settings()` lanza un error de
configuración explícito y la app no arranca. Se falla rápido en vez de exponer un
servicio sin protección.

**Acceptance criteria:**
- [ ] Los 6 defaults coinciden con SPEC §2.5
- [ ] Sin `SERVICE_API_TOKEN` la app **no arranca**, con mensaje explícito
- [ ] Un token vacío o sólo con espacios se trata como ausente

**Verification:**
- [ ] `uv run pytest tests/unit/test_config.py`
- [ ] Manual: `uvicorn` sin la variable ⇒ el proceso muere con error de config

**Dependencies:** T1
**Files:** `app/config.py`, `tests/unit/test_config.py`
**Scope:** Small

---

### T5: Middleware de autenticación

**Description:** `app/api/auth.py`. Extrae el esquema `Bearer` (comparación
case-insensitive según RFC 7235), valida el valor con `secrets.compare_digest`
contra `SERVICE_API_TOKEN`, y devuelve `401 UNAUTHORIZED` con
`WWW-Authenticate: Bearer` ante cualquier fallo. El `detail` es **idéntico** en
todos los casos de fallo para no dar un oráculo. Se registra en `app/main.py`
sobre `/texts`, dejando `/health` y `/readyz` abiertos.

**Acceptance criteria:**
- [ ] Token ausente, vacío, con esquema distinto o valor incorrecto ⇒ `401` en los
      4 casos, con el **mismo** `title` y `detail`
- [ ] La respuesta incluye `WWW-Authenticate: Bearer`
- [ ] El valor del token nunca aparece en el body, ni en el log, ni en la excepción
- [ ] `/health` y `/readyz` responden sin credenciales

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_auth.py`
- [ ] Manual: `curl -i localhost:8082/texts?checksum=x` sin header ⇒ `401`

**Dependencies:** T4
**Files:** `app/api/auth.py`, `app/main.py`, `tests/unit/api/test_auth.py`
**Scope:** Small

---

### T6: Lifecycle de Mongo

**Description:** `app/repositories/mongodb.py`: fábrica de `AsyncMongoClient` con
timeout, `ping` de comprobación y bootstrap del índice sobre `updated_at`, todo
ejecutado en el `lifespan` de FastAPI. Si Mongo no responde, la app **arranca
igualmente** y es `/readyz` quien reporta `503`: es preferible un proceso vivo
que responde probes a un proceso muerto.

**Acceptance criteria:**
- [ ] El `lifespan` hace `ping` y asegura el índice sobre `updated_at`
- [ ] Con Mongo inalcanzable la app arranca y `/readyz` devuelve `503`
- [ ] El cliente se cierra limpiamente al apagar la app

**Verification:**
- [ ] `uv run pytest tests/unit/test_mongodb_lifecycle.py`
- [ ] Manual: `MONGODB_URI` a un puerto muerto ⇒ app viva, `/readyz` en `503`

**Dependencies:** T4
**Files:** `app/repositories/mongodb.py`,
`tests/unit/test_mongodb_lifecycle.py`
**Scope:** Small

---

### T7: Puerto + doble de test

**Description:** `app/services/ports.py` con el `Protocol` `TextRepository`
(SPEC §4.1) y los dataclasses de dominio `StoredText` y `TextChanges`.
`tests/fakes/fake_text_repository.py` lo implementa en memoria, con barreras para
inyectar `DuplicateKeyError` y `DocumentTooLarge`. Al ser `Protocol` estructural,
el fake cumple el contrato sin herencia.

**Acceptance criteria:**
- [ ] El `Protocol` declara los 6 métodos de SPEC §4.1 con las firmas exactas
- [ ] `FakeTextRepository` satisface el Protocol vía `@runtime_checkable`
- [ ] El fake permite inyectar `DuplicateKeyError` y `DocumentTooLarge` a demanda,
      y cuenta llamadas para poder afirmar "insert no se invocó"

**Verification:**
- [ ] `uv run pytest tests/unit/use_cases/test_ports.py`
- [ ] Manual: `python -c "from app.services.ports import TextRepository"`

**Dependencies:** T2
**Files:** `app/services/ports.py`, `tests/fakes/fake_text_repository.py`,
`tests/unit/use_cases/test_ports.py`
**Scope:** Small

---

### T8: Repositorio Mongo — escritura

**Description:** `MongoTextRepository.checksum_exists()` con `find_one` proyectando
sólo `_id`, e `insert()` construyendo el documento con `_id = checksum` y mapeando
los errores del driver a excepciones de dominio (SPEC §5.4). Ésta es la Barrera 2,
la que garantiza la corrección del control de duplicados.

**Acceptance criteria:**
- [ ] `insert` escribe `_id == checksum` y guarda `created_at`/`updated_at` como
      BSON `Date`
- [ ] `DuplicateKeyError` (11000) se traduce a `ChecksumAlreadyExistsError`
- [ ] `DocumentTooLarge` y los errores de conexión se traducen según SPEC §5.4;
      ningún `PyMongoError` escapa sin traducir
- [ ] `app/repositories/` no importa nada de `app/api/`

**Verification:**
- [ ] `uv run pytest tests/integration/repositories/test_mongo_text_repository.py`
- [ ] Manual: `db.texts.findOne({_id: "<checksum>"})` tras un insert

**Dependencies:** T6, T7
**Files:** `app/repositories/mongo_text_repository.py`,
`app/repositories/serialization.py`,
`tests/integration/repositories/test_mongo_text_repository.py`
**Scope:** Medium

---

### T9: TextService.create

**Description:** Orquestación del caso de uso de creación (SPEC §4.2): invocar
`checksum_exists()`, cortar con `ChecksumAlreadyExistsError` si es cierto, si no
`insert()`. Punto único de la regla de negocio; no toca HTTP ni el driver.

**Acceptance criteria:**
- [ ] Si `checksum_exists()` es `True`, se lanza `ChecksumAlreadyExistsError` y
      **`insert()` no se invoca nunca** (verificable con el contador del fake)
- [ ] Si es `False`, devuelve el `StoredText` con `_id == checksum`
- [ ] La excepción de `insert()` propaga sin envolverse ni tragarse
- [ ] `app/services/` no importa `pymongo`

**Verification:**
- [ ] `uv run pytest tests/unit/services/test_text_service.py`
- [ ] Manual: `grep -r "pymongo" app/services/` ⇒ sin resultados

**Dependencies:** T7, T8
**Files:** `app/services/text_service.py`,
`tests/unit/services/test_text_service.py`
**Scope:** Small

---

### T10: Endpoint `POST /texts`

**Description:** Cerrar el primer camino vertical completo.
`validators/common.py` con las guardas compartidas (`require_str`,
`require_mapping`) usando `isinstance` + `TypedDict`. `validators/create_text.py`
convierte el `dict` crudo en `CreateTextCommand` o lanza `ValidationError`.
`routers/texts.py` lee `await request.json()`, valida, llama al servicio y
devuelve `201` + `Location: /texts?checksum=<escaped>`.

> **Superado por T18:** `require_mapping` desapareció y la validación de tipos
> la ejecuta `CreateTextBody` en vez de bloques `isinstance`; el esquema del
> componente `CreateText` se deriva de ese mismo modelo. `require_str` sigue
> en pie para el query param. El resto de la descripción es la de la versión
> que se implementó.

**Acceptance criteria:**
- [ ] Body válido ⇒ `201`, `Location` y `{"message":"OK","checksum":...}`; el
      documento existe en MongoDB
- [ ] JSON malformado, no-objeto, tipo erróneo, campo requerido ausente o `checksum`
      vacío ⇒ `400` con el `code` correcto
- [ ] Un `checksum` de formato arbitrario (no-hex, con guiones, con mayúsculas)
      se **acepta y persiste** — no hay validación de formato
- [ ] `app/api/routers/texts.py` no importa `pymongo` ni `app.repositories`

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_texts_endpoint.py`
- [ ] Manual: `curl -i -X POST localhost:8082/texts -H 'Authorization: Bearer <tok>' -H 'Content-Type: application/json' -d '{...}'`

**Dependencies:** T3, T5, T9
**Files:** `app/api/validators/common.py`, `app/api/validators/create_text.py`,
`app/api/routers/texts.py`, `app/api/dependencies.py`, `app/main.py`
**Scope:** Medium

---

### T11: Test de carrera bajo concurrencia

**Description:** Prueba de que la doble barrera funciona. Lanzar N peticiones
`POST /texts` concurrentes con el mismo checksum contra MongoDB real y verificar
que exactamente una obtiene `201`, las otras N-1 obtienen `409`, y que la colección
contiene un único documento. Es la prueba de que la defensa anti-carrera no es
decorativa.

**Acceptance criteria:**
- [ ] Con N=10 concurrentes: exactamente 1 `201`, 9 `409`, 1 documento en MongoDB
- [ ] El test **falla** si se desactiva la Barrera 2 (verificable comentándola)
- [ ] Repite el escenario 20 veces sin flakiness

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_duplicate_race.py -v`
- [ ] Manual: commenting out the `DuplicateKeyError` handler debe romper el test

**Dependencies:** T10
**Files:** `tests/integration/api/test_duplicate_race.py`
**Scope:** Small

---

### T12: `GET /texts?checksum=`

**Description:** Cerrar la lectura. `serialization.py` convierte el documento BSON
al `dict` de la API con los seis campos que `models.Text` decodifica en Go, y
formatea las fechas como RFC 3339 UTC con `Z` y milisegundos. El router exige el
query param (`400` si falta) y devuelve `404` si el documento no existe.

**Acceptance criteria:**
- [ ] `checksum` existente ⇒ `200` con los seis campos poblados, sin nulos
- [ ] `created_at`/`updated_at` son RFC 3339 UTC con sufijo `Z` (los parsea Go)
- [ ] Query param ausente ⇒ `400 VALIDATION_ERROR`; documento inexistente ⇒
      `404 TEXT_NOT_FOUND`

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_get_text.py`
- [ ] Manual: `curl "localhost:8082/texts?checksum=x" | jq -e '.created_at | test("Z$")'`

**Dependencies:** T10
**Files:** `app/repositories/serialization.py`, `app/api/routers/texts.py`,
`tests/integration/api/test_get_text.py`
**Scope:** Small

---

### T13: `PUT /texts?checksum=`

**Description:** Cerrar la actualización parcial con la semántica estricta de
SPEC §4.3, ahora posible gracias a `omitempty` en el lado Go: *ausente* significa
inequívocamente *no enviado*. `validators/update_text.py` rechaza `text` o
`checksum` en el body con `400 IMMUTABLE_FIELD` (no se ignora en silencio) y un
body `{}` con `400` porque un no-op no es una operación válida. El repositorio usa
`find_one_and_update` con `return_document=AFTER`.

**Acceptance criteria:**
- [ ] `PUT` con `{"name":"nuevo"}` actualiza `name` y **conserva** `metadata`
- [ ] `PUT` con `{"name":""}` sobrescribe `name` con vacío (presente = enviado)
- [ ] `PUT` con `{}` ⇒ `400`; con `text` o `checksum` ⇒ `400 IMMUTABLE_FIELD`
- [ ] `created_at` se preserva, `updated_at` cambia, `checksum` inmutable
- [ ] Checksum inexistente ⇒ `404 TEXT_NOT_FOUND`

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_update_text.py tests/unit/services/test_text_service.py`
- [ ] Manual: `curl -X PUT "localhost:8082/texts?checksum=x" -d '{"name":""}'` y comprobar que `metadata` sobrevive

**Dependencies:** T12
**Files:** `app/api/validators/update_text.py`, `app/services/text_service.py`,
`app/api/routers/texts.py`, `tests/integration/api/test_update_text.py`
**Scope:** Medium

---

### T14: `DELETE /texts?checksum=`

**Description:** Cerrar el borrado. Traducir `deleted_count == 0` a
`TextNotFoundError` (`404`). Devolver `200` con `{"message":"OK","checksum":...}` —
**no** `204`, porque el `DeleteTextResponse` del orquestador tiene esa forma y su
propio mock devuelve `200`.

**Acceptance criteria:**
- [ ] Checksum existente ⇒ `200` con `{"message","checksum"}` y el documento
      desaparece de MongoDB
- [ ] Checksum inexistente ⇒ `404 TEXT_NOT_FOUND`
- [ ] El `404` se decide por `deleted_count`, no por un `exists()` previo

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_delete_text.py`
- [ ] Manual: `curl -X DELETE "localhost:8082/texts?checksum=x" -H 'Authorization: Bearer <tok>'`

**Dependencies:** T12
**Files:** `app/services/text_service.py`, `app/api/routers/texts.py`,
`tests/integration/api/test_delete_text.py`
**Scope:** Small

---

### T15: Middleware

**Description:** `app/api/middleware.py` con, **en este orden**: autenticación
(`401`), `ContentTypeMiddleware` (`415` en POST/PUT), `BodySizeLimitMiddleware`
(`413` por `MAX_TEXT_BODY_BYTES`), `RequestIdMiddleware` (eco de `X-Request-ID`),
CORS (encabezados `GET, POST, PUT, DELETE, OPTIONS`, como el orquestador) y log de
acceso con duración. Registrar todo en el `lifespan` de `app/main.py`.

**Acceptance criteria:**
- [ ] Orden correcto: `401 → 415 → 413 → 400` (SPEC §3.3)
- [ ] Un body de 11 MiB ⇒ `413`; `Content-Type: text/plain` en POST ⇒ `415`
- [ ] `X-Request-ID` entrante se devuelve igual; si falta, se genera uno
- [ ] CORS responde `204` a un `OPTIONS` con `Access-Control-Request-Method`

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_middleware.py`
- [ ] Manual: `curl -i -X POST localhost:8082/texts -H 'Authorization: Bearer <tok>' -H 'Content-Type: text/plain' -d '{}'`

**Dependencies:** T10
**Files:** `app/api/middleware.py`, `app/main.py`,
`tests/unit/api/test_middleware.py`
**Scope:** Medium

---

### T16: Matriz de errores completa

**Description:** Test de integración parametrizado que recorre las 11 filas de la
matriz de SPEC §6.2 y comprueba, para cada escenario, el `status` HTTP **y** el
`code`. Cubre además los `404`/`405` de ruta inexistente y la garantía —derivada de
`httpclient/client.go:39`— de que **todo** `status >= 300` devuelve un body JSON
con `type`, `title`, `status` y `detail`. Todas las peticiones llevan el Bearer
válido salvo en el caso explícito de `401`.

**Acceptance criteria:**
- [ ] Las 11 filas de SPEC §6.2 cubiertas con su `status` y `code` esperados
- [ ] Un test verifica la regla de `httpclient/client.go:39` para todo `>= 300`
- [ ] Sin casos `xfail` ni `skip`; el test corre también los endpoints protegidos
      sin credencial y verifica `401`

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_error_matrix.py -v`
- [ ] Manual: contrastar los IDs de los tests contra SPEC §6.2

**Dependencies:** T13, T14, T15
**Files:** `tests/integration/api/test_error_matrix.py`,
`tests/integration/api/conftest.py`
**Scope:** Medium

---

### T17: OpenAPI, README y cobertura

**Description:** Escribir a mano los schemas de request/response en `openapi_extra`
de cada ruta, para compensar la falta de generación automática, de modo que `/docs`
y `/openapi.json` sigan siendo útiles — incluyendo la documentación del header
`Authorization`. Redactar el README operativo (variables, arranque, contrato,
ejemplos `curl` con el token) y llevar la cobertura al umbral del 85%.

> **Superado por T18:** los cinco componentes de cuerpo ya no se transcriben; se
> derivan de `app/api/models.py`. De este trabajo sobrevive `publish()`, que
> corrige sobre el documento terminado lo que `openapi_extra` no puede (el `422`
> inventado, el `required` del `checksum`, los components), y `Problem`, que sigue
> escrito a mano porque su `enum` es una introspección en tiempo de ejecución.

**Acceptance criteria:**
- [ ] `/openapi.json` documenta request, response y seguridad de los 4 endpoints
      de `/texts`
- [ ] README con variables de entorno, arranque y ejemplo `curl` por endpoint
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa sin excluir código de
      producción para alcanzar el umbral

**Verification:**
- [ ] `uv run pytest --cov=app --cov-fail-under=85`
- [ ] `uv run ruff check .` · `uv run ruff format .`
- [ ] Manual: abrir `http://localhost:8082/docs` y comprobar los 4 endpoints

**Dependencies:** T16
**Files:** `app/api/routers/texts.py`, `README.md`, `SPEC.md`
**Scope:** Small

## Checkpoint Summary

| Punto | Tareas | Se verifica |
|---|---|---|
| Foundation | T1–T3 | Errores y problem details correctos; scaffolding limpio |
| **Auth** | T4–T5 | **Fail-fast sin token; `401` uniforme sin oráculo** |
| **Core slice** | T6–T11 | **`POST` + `409` de duplicados correcto bajo carrera** |
| CRUD completo | T12–T14 | Los 4 verbos y la compatibilidad con `models.Text` |
| Complete | T15–T17 | Matriz de errores, OpenAPI, cobertura, lint |

## Risks and Mitigations

| Riesgo | Impacto | Mitigación | Tarea |
|---|---|---|---|
| Carrera entre `exists()` e `insert()` | Alto | Doble barrera; el `409` depende del índice `_id_` | T8, T11 |
| Token ausente → servicio sin protección | Alto | Sin default: la app no arranca | T4 |
| Token filtrado en logs o respuestas | Alto | `detail` genérico; comparación en tiempo constante | T5 |
| Documento > 16 MiB (límite BSON) | Alto | Límite de 10 MiB + `DocumentTooLarge → 413` | T4, T8, T15 |
| `401` comparado con un `Problem` normal por el orquestador | Medio | El orquestador debe fallar rápido, sin reintento (SPEC §4.4) | T5, T16 |
| `time.Time` de Go no parsea el formato de fecha | Medio | RFC 3339 UTC con `Z` y milisegundos | T12 |
| Sin validación de checksum → `_id` inesperado | Medio | Se acepta string opaco; el query param elimina el problema de routing | T4, T10 |
| Los tests de integración no corren sin `mongod` | Medio | Marcar el directorio y documentar cómo levantar Mongo | T1, T8 |
| `pydantic` filtrándose al dominio | Medio | `pydantic` sólo en `app/api/`; grep que lo verifica | T18 |
| La prosa inglesa de Pydantic llega al `detail` | Medio | `detail` con vocabulario propio (`invalid <campo>`) | T18 |
| OpenAPI y validación divergen | Bajo | Ambos salen del mismo modelo; `test_openapi.py` compara cada componente con `schema_of()` | T18 |
| El contrato del orquestador cambia después | Medio | Checklist SPEC §8 + tests del cliente Go | T16 |

## Parallelization Opportunities

- **Paralelo seguro:** T2 y T4 tras T1; T5 y T6 tras T4.
- **Secuencial obligatorio:** T8 → T9 → T10 → T11 (cadena del camino crítico).
- **Paralelo tras T10:** T12, T13, T14 y T15 son independientes entre sí, pero
  tocan `routers/texts.py` y `main.py`: conviene serializarlos o usar ramas.
- **Coordinación:** cualquier cambio de contrato obliga a revisar SPEC §1 y §8 y a
  avisar al orquestador **antes** de implementar (cambios en §1.7).

## Open Questions

Ninguna abierta: las nueve decisiones (Q1–Q9) están tomadas y documentadas en
SPEC §11. El contrato de entrada **cambia** y requiere los cinco ajustes de
SPEC §1.7 en el cliente Go, que quedan pendientes de tu integración.

---

## Nota de handoff para el orquestador

Antes de conectar este servicio, el cliente Go necesita:

1. `?checksum=` con `url.QueryEscape` en lugar de path param con
   `url.PathEscape` (`client.go:42,47,52`).
2. `omitempty` en `UpdateTextRequest` (`dto/text.go`).
3. `PERSISTENCE_API_TOKEN` en la configuración.
4. `Authorization: Bearer <token>` en todas las requests (`httpclient/client.go`).
5. Manejo de `401` como **error de configuración con fail-fast**, sin reintento.

> **Estado (9-oct-2026):** los cinco ajustes más la reescritura de
> `persistence/client_test.go` están **hechos y verificados** en el orquestador Go
> (`go build ./... && go vet ./... && go test ./...` en verde). `PERSISTENCE_API_TOKEN`
> quedó como variable obligatoria (sin default) y debe coincidir con el
> `SERVICE_API_TOKEN` de este servicio.

---

# Plan de Remediación post-Code Review (v3)

> **Origen:** Informe de Code Review del release candidate.
> **Estado:** pendiente de aprobación. No se ha modificado código de producción.
> **Objetivo:** cerrar los **15 hallazgos** del informe y las recomendaciones de
> producción antes de reintentar el despliegue.
>
> **Regla de trabajo:** TDD. Cada tarea empieza por un test que reproduce el
> defecto; el test debe fallar antes del cambio y pasar después. Ninguna tarea se
> cierra con `skip`, `xfail`, `# type: ignore` nuevo ni cobertura excluida.

## Overview

El servicio ya implementa el CRUD y la suite v2 está en verde, pero el release
candidate no es apto para producción. La remediación se concentra en cinco
frentes, en este orden de riesgo:

1. **Contrato de errores:** `DocumentTooLargeError` y los fallos de `update`/
   `delete` deben responder `413`/`503`, nunca `500`, y el `detail` no debe
   filtrar mensajes de pymongo.
2. **Trazabilidad HTTP:** `X-Request-ID` debe existir en **todas** las respuestas,
   incluido `401`, y estar en el log de acceso y en todos los logs internos.
3. **Límite real de body:** `Transfer-Encoding: chunked` no puede evadir
   `MAX_TEXT_BODY_BYTES`.
4. **Alcance y configuración:** eliminar métricas, cerrar CORS, simplificar la
   configuración y declarar correctamente las dependencias.
5. **Calidad restante:** eliminar código muerto, corregir `_to_stored`,
   `_codes()`, `compare_digest`, Consul y alinear README/SPEC.

El contrato HTTP del orquestador Go **no cambia**. Los únicos cambios visibles
son correcciones: `413` donde antes había `500`, `503` donde antes había `500`,
`X-Request-ID` en respuestas que no lo tenían y ausencia de `/metrics`.

## Decisiones de arquitectura para la remediación

- **Errores de dominio siempre `ServiceError`.** `DocumentTooLargeError` hereda
  de `PayloadTooLargeError`; ningún error de persistencia queda como `Exception`
  genérica.
- **Un solo punto de traducción de `PyMongoError`.** Insert, lectura, update y
  delete comparten la misma política: `DocumentTooLarge → 413`,
  `DuplicateKey → 409`, resto de `PyMongoError → 503`. El mensaje del driver se
  registra en el servidor y nunca se devuelve en `detail`.
- **Request ID en el borde, después de CORS.** El orden externo pasa a ser
  `CORS → RequestId → AccessLog → Auth → ContentType → BodySize`. Se preserva
  `401 → 415 → 413 → 400`, pero ahora el `401` también lleva ID.
- **Contextvar para el request ID.** El middleware lo publica en
  `request.state` y en un `ContextVar`; un filtro de logging lo inyecta en todas
  las líneas de `app.*` sin pasarlo a mano por servicios y repositorios.
- **Sin métricas.** Se eliminan `app/metrics.py` y
  `app/api/routers/metrics.py`; no se agrega `prometheus_client`. La
  observabilidad requerida es logging + trazabilidad por `X-Request-ID`.
- **Configuración con una sola fuente.** `get_settings(environ)` lee únicamente
  el mapping recibido (o `os.environ` si es `None`), sin fallback silencioso a
  `os.getenv`; se eliminan alias y wrappers.
- **Consul no bloquea el event loop.** El registro se ejecuta con
  `asyncio.to_thread`, con retry/backoff o política fail-fast explícita. El
  parseo de KV falla con `ConsulConfigurationError`, no con `KeyError`.
- **CORS cerrado por defecto.** Si no hay clientes navegador, se elimina el
  middleware. Si los hay, se configuran orígenes explícitos; nunca `["*"]`.
- **Logs sin PII.** Nunca se registra el token, el texto completo ni metadata.
  El checksum se registra truncado o hasheado; la política se documenta.
- **Compatibilidad Go.** Se mantienen los seis campos, RFC 3339 con `Z` y
  milisegundos, `?checksum=`, `200` en DELETE y `409` uniforme.

## Mapa hallazgo → tarea

| Hallazgo del informe | Tarea(s) |
|---|---|
| 3.1 `update`/`delete` no traducen `PyMongoError` | **R2** |
| 3.2 `DocumentTooLargeError` termina en `500` | **R1** |
| 3.3 `PersistenceError(str(error))` filtra el driver | **R3** |
| 3.4 Trazabilidad `X-Request-ID` incompleta | **R4** |
| 3.5 Límite de body evadible con `chunked` | **R5** |
| 3.6 Registro en Consul bloqueante/fatal | **R9** |
| 3.7 Métricas fuera de alcance/dependencia no declarada | **R10** |
| 3.8 CORS wildcard | **R8** |
| 3.9 Configuración duplicada y dependencias | **R6, R7** |
| 3.10 `count()` e índice `updated_at` sin uso | **R11, R12** |
| 3.11 `_to_stored` inventa timestamps | **R13** |
| 3.12 `_codes()` solo mira subclases directas | **R14** |
| 3.13 `compare_digest` con `str` no ASCII | **R15** |
| 3.14 Parseo de Consul con `KeyError`/status redundante | **R9** |
| 3.15 README/SPEC desalineados | **R16** |
| 4.1 Tests de regresión | Cada tarea + **R20** |
| 4.2 Logging estructurado y sin PII | **R18** |
| 4.3 Timeouts/pool/retry de Mongo | **R17** |
| 4.4 Seguridad de borde y secretos | **R8, R9, R18, R19** |
| 4.5 Readiness y memoria | **R18** |
| 4.6 CI, cobertura y Docker | **R19** |
| 4.7 Confirmar ausencia de métricas | **R10** |

## Dependency Graph

```
R1 ─► R2 ─► R3
R4 ─► R5
R6 ─► R8
R6 ─► R11 ─► R17
R2 ─► R11
R2 ─► R13
R3 ─► R13
R6 ─► R12
R7 ─► R10
R4 ─► R18
R5 ─► R18
R17 ─► R18
R1..R15 ─► R16
R1..R19 ─► R20
```

**Paralelización segura:** R7, R14, R15 y R19 no comparten archivos con el resto
y pueden ejecutarse en paralelo. **Secuencial obligatorio:** R1→R2→R3 (mismo
repositorio/errores), R4→R5 (mismo middleware), R6→R8 (configuración/CORS),
R6→R11→R17 (configuración/Mongo), R2→R13 (repositorio) y R16/R20 al final.

## Task List

### Phase 1: Contrato de errores y persistencia

- [ ] **R1: `DocumentTooLargeError` es un `413` y el fake es fiel al dominio.**
- [ ] **R2: `update`/`delete` traducen todos los `PyMongoError`.**
- [ ] **R3: `PersistenceError` deja de filtrar el mensaje del driver.**

### Checkpoint 1: errores y persistencia

- [ ] `DocumentTooLarge` de Mongo responde `413`, no `500`.
- [ ] Fallo de Mongo en `PUT`/`DELETE` responde `503`, no `500`.
- [ ] Ningún `detail` de `503` contiene texto del driver.
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa.
- [ ] `uv run ruff check .` y `uv run ruff format --check .` pasan.

### Phase 2: Frontera HTTP y trazabilidad

- [ ] **R4: `X-Request-ID` de extremo a extremo, incluido `401`.**
- [ ] **R5: límite real de body contra `chunked`.**

### Checkpoint 2: HTTP y trazabilidad

- [ ] Un `401` lleva `X-Request-ID` y el log de acceso incluye ese ID.
- [ ] Un `X-Request-ID` inválido se reemplaza; uno válido se devuelve igual.
- [ ] Un body `chunked` mayor al límite responde `413`.
- [ ] El orden `401 → 415 → 413 → 400` sigue verificado por tests.
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa.

### Phase 3: Configuración, alcance e integraciones

- [x] **R6: configuración con una sola fuente y sin alias.**
- [x] **R7: dependencias declaradas correctamente (`python-dotenv`, sin `pydantic-settings`).**
- [ ] **R8: CORS cerrado por defecto o eliminado.**
- [ ] **R9: Consul no bloqueante, con retry y parseo seguro.**
- [ ] **R10: eliminar métricas y confirmar que `/metrics` es `404`.**

### Checkpoint 3: configuración y alcance

- [ ] `get_settings(environ)` no lee el entorno real cuando recibe un mapping.
- [ ] `uv sync --frozen` y `uv lock --check` pasan.
- [ ] `python-dotenv` es dependencia directa; `pydantic-settings` ya no está.
- [ ] No queda ninguna referencia a `prometheus_client` ni a métricas.
- [ ] Consul malformado produce `ConsulConfigurationError`, no `KeyError`.
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa.

### Phase 4: Calidad de código y datos

- [ ] **R11: eliminar `count()` del puerto, repositorio, fake y tests.**
- [ ] **R12: eliminar el índice `updated_at` sin uso.**
- [ ] **R13: `_to_stored` falla explícitamente ante documentos incompletos.**
- [ ] **R14: `_codes()` recorre subclases anidadas y deduplica.**
- [ ] **R15: `compare_digest` sobre bytes para tokens no ASCII.**

### Checkpoint 4: calidad

- [ ] No queda código muerto de `count()` ni el índice `updated_at`.
- [ ] Un documento corrupto no inventa timestamps ni texto vacío.
- [ ] El enum de `Problem.code` incluye códigos anidados una sola vez.
- [ ] Un token no ASCII responde `401`, no `500`.
- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa.

### Phase 5: Documentación y hardening de producción

- [ ] **R16: alinear README/SPEC con el código corregido.**
- [ ] **R17: timeouts, pool y política de retry de Mongo.**
- [ ] **R18: logging de producción sin PII y readiness con caché.**
- [ ] **R19: CI, cobertura, Docker, borde y auditoría de dependencias.**

### Checkpoint 5: documentación y hardening

- [ ] README/SPEC no contradicen el código ni entre sí.
- [ ] `timeoutMS`/`socketTimeoutMS` y `maxPoolSize` están configurados y probados.
- [ ] Los logs no contienen token, texto completo ni metadata.
- [ ] `/readyz` no golpea Mongo en cada sonda si la caché está vigente.
- [ ] CI ejecuta lint, formato y cobertura con umbral.

### Phase 6: Verificación final

- [ ] **R20: matriz manual, regresión completa y checklist de release.**

### Checkpoint Final

- [ ] `uv run pytest --cov=app --cov-fail-under=85` pasa.
- [ ] `uv run ruff check .` y `uv run ruff format --check .` pasan.
- [ ] Matriz manual de `curl` completa y documentada.
- [ ] No existe `/metrics`; no hay dependencia de métricas.
- [ ] **Revisión humana antes de reintentar el despliegue.**

## Task Detail

### R1: `DocumentTooLargeError` es un `413` y el fake es fiel al dominio

**Descripción:** Convertir `DocumentTooLargeError` en subclase de
`PayloadTooLargeError` para que el handler de `ServiceError` responda `413`.
Alinear `FakeTextRepository` para que un duplicado lance
`ChecksumAlreadyExistsError`, igual que el repositorio real, y retirar
`DuplicateKeyError` del vocabulario de producción si no tiene otro uso.

**Acceptance criteria:**
- [ ] `DocumentTooLargeError.status == 413` y `code == "PAYLOAD_TOO_LARGE"`.
- [ ] Un `DocumentTooLarge` del repositorio produce `413` con
      `application/problem+json`, no `500`.
- [ ] El fake de duplicado lanza `ChecksumAlreadyExistsError`; no hay
      `DuplicateKeyError` usado solo por tests.
- [ ] Los tests existentes de repositorio, puerto y matriz de errores pasan.

**Verification:**
- [ ] `uv run pytest tests/integration/repositories/test_mongo_text_repository.py`
- [ ] `uv run pytest tests/integration/api/test_error_matrix.py`
- [ ] `uv run pytest tests/unit/use_cases/test_ports.py`
- [ ] Test nuevo: `POST`/`PUT` con `DocumentTooLarge` inyectado ⇒ `413`.

**Dependencies:** None
**Files likely touched:** `app/errors.py`,
`app/repositories/mongodb_text_repository.py`,
`tests/fakes/fake_text_repository.py`,
`tests/integration/repositories/test_mongo_text_repository.py`,
`tests/integration/api/test_error_matrix.py`
**Estimated scope:** Small

---

### R2: `update`/`delete` traducen todos los `PyMongoError`

**Descripción:** Envolver `find_one_and_update` y `delete_one` con la misma
política de traducción que `insert`/`_find_one`. `update` debe capturar
`DocumentTooLarge` antes que `PyMongoError`; `delete` solo necesita
`PyMongoError`. Usar `ReturnDocument.AFTER` en lugar del booleano `True`.

**Acceptance criteria:**
- [ ] `update` traduce `DocumentTooLarge → DocumentTooLargeError` y
      `PyMongoError → PersistenceError`.
- [ ] `delete` traduce `PyMongoError → PersistenceError`.
- [ ] `PUT`/`DELETE` con Mongo caído responden `503`, no `500`.
- [ ] `return_document=ReturnDocument.AFTER` reemplaza a `True`.
- [ ] Tests de repositorio y de API cubren ambos verbos.

**Verification:**
- [ ] `uv run pytest tests/integration/repositories/test_mongo_text_repository.py -k "update or delete"`
- [ ] `uv run pytest tests/integration/api/test_error_matrix.py -k "503"`
- [ ] Test nuevo: `PUT` y `DELETE` con `ServerSelectionTimeoutError` ⇒ `503`.

**Dependencies:** R1
**Files likely touched:** `app/repositories/mongodb_text_repository.py`,
`tests/integration/repositories/test_mongo_text_repository.py`,
`tests/integration/api/test_error_matrix.py`
**Estimated scope:** Small

---

### R3: `PersistenceError` deja de filtrar el mensaje del driver

**Descripción:** Centralizar la traducción de `PyMongoError` en un helper que
registre el tipo/mensaje real en el servidor y devuelva `PersistenceError()` con
su `detail` por defecto. Eliminar todos los `PersistenceError(str(error))`.

**Acceptance criteria:**
- [ ] No queda ninguna llamada `PersistenceError(str(error))`.
- [ ] El `detail` de `503` es el valor por defecto y no contiene host, topología,
      query ni mensaje de pymongo.
- [ ] El error real se registra con operación y `request_id` (vía filtro de R4).
- [ ] Un test verifica que el body de `503` no contiene el texto del driver.

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_error_matrix.py -k "persistence"`
- [ ] `uv run pytest tests/integration/repositories/test_mongo_text_repository.py`
- [ ] `rg "PersistenceError\\(str\\(" app tests` ⇒ sin resultados.

**Dependencies:** R1, R2
**Files likely touched:** `app/repositories/mongodb_text_repository.py`,
`tests/integration/api/test_error_matrix.py`,
`tests/integration/repositories/test_mongo_text_repository.py`
**Estimated scope:** XS

---

### R4: `X-Request-ID` de extremo a extremo, incluido `401`

**Descripción:** Reordenar el stack para que `RequestIdMiddleware` sea más
externo que `AccessLogMiddleware` y `BearerAuthMiddleware`, manteniendo CORS
como el más externo. Publicar el ID en `request.state` y en un `ContextVar`,
inyectarlo en el formato de logging y eliminar la línea duplicada de
`RequestIdMiddleware`. Validar el header entrante con charset y longitud
acotados.

**Acceptance criteria:**
- [ ] Orden efectivo: `CORS → RequestId → AccessLog → BearerAuth →
      ContentType → BodySize`; se preserva `401 → 415 → 413 → 400`.
- [ ] `401`, `415`, `413`, `400`, `409`, `503` y `500` llevan `X-Request-ID`.
- [ ] Un ID válido se devuelve igual; uno inválido o demasiado largo se
      reemplaza por uno generado.
- [ ] El log de acceso incluye `request_id` y no hay dos líneas de request-id
      por petición.
- [ ] Los logs de auth, exception handlers, servicio y repositorio incluyen
      `request_id` automáticamente.
- [ ] Tests: `401` con header, acceso con ID, header inválido saneado.

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_middleware.py -k "request_id or access_log"`
- [ ] `uv run pytest tests/unit/api/test_auth.py -k "request_id"`
- [ ] Manual: `curl -i localhost:8082/texts?checksum=x` sin token ⇒ `401` +
      `x-request-id`.
- [ ] Manual: `curl -i -H "X-Request-ID: test-123" ...` ⇒ eco `test-123`.

**Dependencies:** None
**Files likely touched:** `app/main.py`, `app/api/middleware.py`,
`app/logging_setup.py`, `tests/unit/api/test_middleware.py`,
`tests/unit/api/test_auth.py`
**Estimated scope:** Medium

---

### R5: Límite real de body contra `chunked`

**Descripción:** Reemplazar el middleware que solo lee `Content-Length` por uno
ASGI que cuente bytes reales, rechace `413` al superar el límite y repita el body
al downstream. Mantener el rechazo temprano por `Content-Length` cuando exista.

**Acceptance criteria:**
- [ ] Un body `chunked` mayor a `MAX_TEXT_BODY_BYTES` responde `413` antes de
      llegar al router.
- [ ] Un body declarado con `Content-Length` mayor al límite se rechaza sin
      leerlo.
- [ ] Un body válido dentro del límite sigue llegando intacto a `request.json()`.
- [ ] El test usa un ASGI `receive` con `more_body=True`; no depende de `httpx`
      para simular chunked.
- [ ] No se rompe el orden `401 → 415 → 413 → 400`.

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_middleware.py -k "body_size or chunked"`
- [ ] Manual: `curl -i -X POST ... -H "Transfer-Encoding: chunked" --data-binary @archivo-grande` ⇒ `413`.

**Dependencies:** R4
**Files likely touched:** `app/api/middleware.py`,
`tests/unit/api/test_middleware.py`
**Estimated scope:** Medium

---

### R6: Configuración con una sola fuente y sin alias

**Descripción:** Simplificar `get_settings` para que lea solo el mapping
recibido (o `os.environ`), sin mezclar `os.getenv`. Eliminar las propiedades
alias `mongodb_*` y `get_settings_from_values`; actualizar `mongodb.py` y
`main.py` para usar `mongo_*` y `get_settings(values)`.

**Acceptance criteria:**
- [ ] `get_settings(environ)` no consulta el entorno real si recibe un mapping.
- [ ] Los defaults y la obligatoriedad de `PERSISTENCE_API_TOKEN` se mantienen.
- [ ] No existen `mongodb_uri`, `mongodb_database`,
      `mongodb_texts_collection` ni `mongodb_timeout_ms`.
- [ ] `get_settings_from_values` fue eliminado y `main.py` usa `get_settings`.
- [ ] Tests: mapping inyectado sin token ⇒ `ConfigurationError` aunque el
      proceso tenga token; defaults correctos.

**Verification:**
- [ ] `uv run pytest tests/unit/test_config.py`
- [ ] `rg "mongodb_|get_settings_from_values" app tests` ⇒ sin resultados.
- [ ] `uv run pytest tests/unit/test_mongodb_lifecycle.py`

**Dependencies:** None
**Files likely touched:** `app/config.py`, `app/repositories/mongodb.py`,
`app/main.py`, `tests/unit/test_config.py`
**Estimated scope:** Medium

---

### R7: Dependencias declaradas correctamente

**Descripción:** Declarar `python-dotenv` como dependencia directa (se importa
en `app/config.py`), eliminar `pydantic-settings` (no se usa) y confirmar que
`prometheus_client` no se agrega. Regenerar `uv.lock`.

**Acceptance criteria:**
- [x] `pyproject.toml` incluye `python-dotenv` y ya no incluye
      `pydantic-settings`.
- [x] `uv lock`/`uv sync --frozen` pasan y `uv.lock` queda actualizado.
- [x] `uv tree` muestra `python-dotenv` como dependencia directa.
- [x] No hay `prometheus_client` en `pyproject.toml` ni en `uv.lock`.

**Verification:**
- [x] `uv lock --check`
- [x] `uv sync --frozen`
- [x] `uv tree | rg "python-dotenv|pydantic-settings|prometheus"`

**Dependencies:** None
**Files likely touched:** `pyproject.toml`, `uv.lock`
**Estimated scope:** XS

---

### R8: CORS cerrado por defecto o eliminado

**Descripción:** Eliminar `allow_origins=["*"]`. Si no hay clientes navegador,
quitar `CORSMiddleware`; si los hay, agregar `CORS_ALLOW_ORIGINS` como lista
explícita y configurar el middleware con esa lista. Mantener `X-Request-ID` en
`allow_headers` cuando CORS exista.

**Acceptance criteria:**
- [ ] No queda `allow_origins=["*"]` en el código.
- [ ] Por defecto no se permite ningún origen cruzado.
- [ ] Si se configura un origen permitido, el preflight responde solo para ese
      origen; un origen no permitido no recibe `Access-Control-Allow-Origin`.
- [ ] Tests de CORS actualizados o eliminados si el middleware se retira.
- [ ] README documenta la decisión y la variable, si aplica.

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_middleware.py -k "cors or preflight"`
- [ ] `uv run pytest tests/unit/test_config.py -k "cors"`
- [ ] Manual: `curl -i -H "Origin: https://evil.example" ...` ⇒ sin
      `access-control-allow-origin: *`.

**Dependencies:** R6
**Files likely touched:** `app/main.py`, `app/config.py`,
`tests/unit/test_config.py`, `tests/unit/api/test_middleware.py`
**Estimated scope:** Small

---

### R9: Consul no bloqueante, con retry y parseo seguro

**Descripción:** Ejecutar `register_service` con `asyncio.to_thread` para no
bloquear el event loop. Definir política de fallo: retry/backoff acotado o
fail-fast explícito documentado. Endurecer `load_prefix` para capturar
`KeyError`/`TypeError`/`ValueError`/`UnicodeDecodeError` y lanzar
`ConsulConfigurationError`. Eliminar la comprobación redundante de
`response.status`.

**Acceptance criteria:**
- [ ] El registro no bloquea el event loop; se ejecuta en un hilo.
- [ ] Un fallo transitorio tiene retry/backoff o un fail-fast documentado y
      testeado.
- [ ] Una respuesta KV malformada produce `ConsulConfigurationError`, no
      `KeyError`/`TypeError`.
- [ ] Un prefijo vacío o sin claves tiene una política explícita (fallar o
      documentar el fallback).
- [ ] Se eliminó `if response.status // 100 != 2`.
- [ ] Tests de respuesta malformada, retry y no bloqueo.

**Verification:**
- [ ] `uv run pytest tests/unit/test_consul.py`
- [ ] Test nuevo: `load_prefix` con `[{}]` ⇒ `ConsulConfigurationError`.
- [ ] Test nuevo: `register_service` que falla una vez y luego responde ⇒ retry
      (si se elige esa política).

**Dependencies:** R4
**Files likely touched:** `app/main.py`, `app/consul.py`,
`app/consul_agent.py`, `tests/unit/test_consul.py`
**Estimated scope:** Medium

---

### R10: Eliminar métricas y confirmar `/metrics` `404`

**Descripción:** Borrar `app/metrics.py` y `app/api/routers/metrics.py`, no
montar `/metrics` y no agregar `prometheus_client`. Confirmar con test que la
ruta responde `404` y que no queda ninguna referencia.

**Acceptance criteria:**
- [ ] Los dos archivos de métricas fueron eliminados.
- [ ] No hay imports de `prometheus_client` ni de `app.metrics`.
- [ ] `/metrics` responde `404` (o `401` si se decide mantener una ruta
      inexistente protegida; el requisito es que no exista endpoint de métricas).
- [ ] `pyproject.toml`/`uv.lock` no contienen `prometheus_client`.
- [ ] README/SPEC no prometen métricas.

**Verification:**
- [ ] `rg "metrics|prometheus" app pyproject.toml uv.lock README.md SPEC.md`
- [ ] `uv run pytest tests/integration/api/test_error_matrix.py -k "metrics"`
- [ ] Manual: `curl -i localhost:8082/metrics` ⇒ `404`.

**Dependencies:** R7
**Files likely touched:** `app/metrics.py`,
`app/api/routers/metrics.py`, `pyproject.toml`,
`tests/integration/api/test_error_matrix.py`
**Estimated scope:** XS

---

### R11: Eliminar `count()` del puerto, repositorio, fake y tests

**Descripción:** Quitar `count()` de `TextRepository`, `MongoTextRepository`,
`FakeTextRepository` y tests. Ningún endpoint ni servicio lo usa. Resolver el
drift de SPEC: si se necesita un probe de repositorio, implementar `ping` con
propósito; si no, eliminar la fila.

**Acceptance criteria:**
- [ ] No existe `count()` en `app/` ni en `tests/fakes/`.
- [ ] Los tests que contaban llamadas ya no lo referencian.
- [ ] SPEC y código coinciden (`ping` o eliminación de la fila).
- [ ] La suite sigue verde.

**Verification:**
- [ ] `rg "count\\(" app tests` ⇒ sin resultados en el puerto/repositorio.
- [ ] `uv run pytest tests/unit/use_cases/test_ports.py tests/integration/repositories/test_mongo_text_repository.py`

**Dependencies:** R2, R6
**Files likely touched:** `app/use_cases/ports.py`,
`app/repositories/mongodb_text_repository.py`,
`tests/fakes/fake_text_repository.py`,
`tests/unit/use_cases/test_ports.py`,
`tests/integration/repositories/test_mongo_text_repository.py`
**Estimated scope:** Small

---

### R12: Eliminar el índice `updated_at` sin uso

**Descripción:** Quitar `create_index("updated_at")` de `MongoConnection.start`.
Ninguna consulta filtra ni ordena por `updated_at`; todas las búsquedas son por
`_id`. Si se prevé un listado futuro, el índice se agregará junto con la consulta
que lo use.

**Acceptance criteria:**
- [ ] `MongoConnection.start` no crea el índice `updated_at`.
- [ ] No se pierde ninguna garantía de unicidad: `_id` sigue siendo la clave.
- [ ] Tests de lifecycle actualizados y verdes.
- [ ] `/readyz` sigue funcionando con Mongo arriba/abajo.

**Verification:**
- [ ] `rg "create_index|updated_at" app/repositories/mongodb.py`
- [ ] `uv run pytest tests/unit/test_mongodb_lifecycle.py`

**Dependencies:** R6
**Files likely touched:** `app/repositories/mongodb.py`,
`tests/unit/test_mongodb_lifecycle.py`
**Estimated scope:** XS

---

### R13: `_to_stored` falla explícitamente ante documentos incompletos

**Descripción:** Dejar de inventar `created_at`/`updated_at` con `now()` y
`text` vacío. Si falta un campo obligatorio, registrar el problema y lanzar un
error de dominio explícito; si se quiere distinguir corrupción de
indisponibilidad, crear `CorruptDocumentError(ServiceError)` con `500`.

**Acceptance criteria:**
- [ ] `_to_stored` no usa `datetime.now()` ni `or ""` para campos obligatorios.
- [ ] Un documento sin `text`/`created_at`/`updated_at` produce un error
      explícito y logueado, no una respuesta con datos falsos.
- [ ] Un documento válido sigue mapeando los seis campos correctamente.
- [ ] Test de documento incompleto y test de documento válido.

**Verification:**
- [ ] `uv run pytest tests/integration/repositories/test_mongo_text_repository.py -k "stored or corrupt"`
- [ ] `uv run pytest tests/integration/api/test_get_text.py`

**Dependencies:** R2, R3
**Files likely touched:** `app/repositories/mongodb_text_repository.py`,
`tests/integration/repositories/test_mongo_text_repository.py`
**Estimated scope:** XS

---

### R14: `_codes()` recorre subclases anidadas y deduplica

**Descripción:** Reemplazar `ServiceError.__subclasses__()` por un recorrido
recursivo que incluya subclases anidadas, con `set` para evitar duplicados. El
enum de `Problem.code` debe seguir siendo estable y completo.

**Acceptance criteria:**
- [ ] `_codes()` incluye `PAYLOAD_TOO_LARGE` una sola vez aunque
      `DocumentTooLargeError` sea subclase de `PayloadTooLargeError`.
- [ ] Un error nuevo anidado aparece en el enum sin tocar `schemas.py`.
- [ ] `test_openapi.py` sigue comparando el enum contra las clases reales.
- [ ] No cambia el orden alfabético del enum.

**Verification:**
- [ ] `uv run pytest tests/integration/api/test_openapi.py`
- [ ] `uv run pytest tests/unit/test_errors.py`

**Dependencies:** R1
**Files likely touched:** `app/api/schemas.py`,
`tests/integration/api/test_openapi.py`
**Estimated scope:** XS

---

### R15: `compare_digest` sobre bytes para tokens no ASCII

**Descripción:** Codificar ambos valores a UTF-8 antes de
`secrets.compare_digest` para que un token no ASCII produzca `401` en lugar de
`TypeError`/`500`, manteniendo la comparación en tiempo constante.

**Acceptance criteria:**
- [ ] Un token configurado no ASCII y presentado correctamente no lanza
      `TypeError`.
- [ ] Un token incorrecto sigue respondiendo `401` uniforme.
- [ ] La comparación sigue siendo `compare_digest` sobre bytes.
- [ ] Tests con token ASCII y no ASCII.

**Verification:**
- [ ] `uv run pytest tests/unit/api/test_auth.py -k "token or unicode"`
- [ ] Manual: configurar un token con `ñ`/emoji y probar `curl`.

**Dependencies:** None
**Files likely touched:** `app/api/auth.py`, `tests/unit/api/test_auth.py`
**Estimated scope:** XS

---

### R16: Alinear README/SPEC con el código corregido

**Descripción:** Actualizar la documentación después de R1–R15. Corregir el
nombre canónico del token, la afirmación sobre `X-Request-ID` en el log de
acceso, el ejemplo de milisegundos, la ausencia de métricas, CORS, variables de
configuración y el drift `ping`/`count`. Documentar la política de Consul y de
retry de Mongo.

**Acceptance criteria:**
- [ ] README documenta `PERSISTENCE_API_TOKEN` como canónico y
      `SERVICE_API_TOKEN` como alias.
- [ ] README dice la verdad sobre `X-Request-ID` y el log de acceso.
- [ ] El ejemplo de fecha usa milisegundos (`...789Z`), no microsegundos.
- [ ] README/SPEC confirman que no hay `/metrics`.
- [ ] SPEC y código coinciden en `ping`/`count`, `413` por documento y `503` en
      `PUT`/`DELETE`.
- [ ] No hay contradicciones entre README y SPEC.

**Verification:**
- [ ] Revisión manual cruzada README ↔ SPEC ↔ `app/`.
- [ ] `rg "metrics|SERVICE_API_TOKEN|X-Request-ID|count\\(|ping" README.md SPEC.md`
- [ ] `uv run ruff check .` no se ve afectado por docs (`*.md` excluido).

**Dependencies:** R1–R15
**Files likely touched:** `README.md`, `SPEC.md`
**Estimated scope:** Small

---

### R17: Timeouts, pool y política de retry de Mongo

**Descripción:** Agregar configuración para `timeoutMS`/`socketTimeoutMS` y
`maxPoolSize`, pasarla al `AsyncMongoClient` y documentarla en `.env.example`.
Definir una política explícita de retry para errores transitorios: solo lecturas
idempotentes o ninguna, para no duplicar escrituras.

**Acceptance criteria:**
- [ ] `Settings` expone `mongo_socket_timeout_ms` y `mongo_max_pool_size` (o
      nombres equivalentes) con defaults seguros.
- [ ] `AsyncMongoClient` recibe `timeoutMS`/`socketTimeoutMS` y `maxPoolSize`.
- [ ] `.env.example` y README documentan las variables.
- [ ] Tests verifican que los valores llegan al cliente.
- [ ] La política de retry está escrita y no reintenta escrituras no
      idempotentes sin control.

**Verification:**
- [ ] `uv run pytest tests/unit/test_config.py tests/unit/test_mongodb_lifecycle.py`
- [ ] `rg "timeoutMS|socketTimeoutMS|maxPoolSize" app .env.example README.md`

**Dependencies:** R6, R11
**Files likely touched:** `app/config.py`, `app/repositories/mongodb.py`,
`.env.example`, `tests/unit/test_config.py`, `README.md`
**Estimated scope:** Medium

---

### R18: Logging de producción sin PII y readiness con caché

**Descripción:** Completar la observabilidad: logs estructurados/consistentes
con `request_id`, eventos de negocio seguros en create/update/delete y errores
con contexto. Nunca registrar token, texto completo ni metadata; el checksum se
trunca o hashea. Añadir caché con TTL corto al `ping` de `/readyz` para no
golpear Mongo en cada sonda.

**Acceptance criteria:**
- [ ] Create/update/delete emiten un log de negocio con `request_id`, checksum
      seguro y resultado, sin texto ni metadata.
- [ ] Los errores de persistencia se loguean con operación y `request_id`.
- [ ] No hay token, texto completo ni metadata en ningún log.
- [ ] `/readyz` cachea el resultado por un TTL configurable (default 1 s).
- [ ] Tests de logs y de caché de readiness.

**Verification:**
- [ ] `uv run pytest tests/unit/services/test_text_service.py -k "log"`
- [ ] `uv run pytest tests/unit/test_mongodb_lifecycle.py -k "readyz"`
- [ ] `uv run pytest tests/unit/test_logging_setup.py`
- [ ] `rg "logger.*text|logger.*metadata|logger.*token" app` ⇒ sin resultados.

**Dependencies:** R4, R5, R17
**Files likely touched:** `app/logging_setup.py`, `app/services/text_service.py`,
`app/repositories/mongodb_text_repository.py`, `app/api/routers/health.py`,
tests de servicio/health
**Estimated scope:** Medium

---

### R19: CI, cobertura, Docker, borde y auditoría de dependencias

**Descripción:** Asegurar que el gate de calidad se ejecuta siempre: lint,
formato, tests con cobertura ≥ 85 y `uv sync --frozen`. Endurecer el contenedor
con `read_only`, `cap_drop: [ALL]`, `security_opt: no-new-privileges` y límites
de memoria si son compatibles. Confirmar en el borde (Traefik) que hay TLS y
rate limiting; si no, registrar la deuda con owner y criterio de aceptación.
Documentar que la rotación de token queda fuera de esta release.

**Acceptance criteria:**
- [ ] CI ejecuta `uv run ruff check .`, `uv run ruff format --check .` y
      `uv run pytest --cov=app --cov-fail-under=85`.
- [ ] `uv sync --frozen` y `uv lock --check` pasan en CI.
- [ ] No hay dependencias no declaradas ni `prometheus_client`.
- [ ] Dockerfile/compose mantienen non-root, healthcheck y graceful shutdown;
      se agregan las opciones de hardening compatibles.
- [ ] TLS y rate limiting están verificados en Traefik o registrados como deuda
      con owner, umbral y fecha.
- [ ] La rotación de token está documentada como fuera de alcance, con su
      mitigación operativa.
- [ ] `docker compose config` valida.

**Verification:**
- [ ] `uv run pytest --cov=app --cov-fail-under=85`
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `docker compose config`
- [ ] `uv tree` y `rg "prometheus" pyproject.toml uv.lock`
- [ ] Revisión de la configuración de Traefik: TLS + rate limit.

**Dependencies:** None
**Files likely touched:** `pyproject.toml`, `Dockerfile`, `docker-compose.yml`,
workflow de CI o configuración de Traefik si existe
**Estimated scope:** Medium

---

### R20: Matriz manual, regresión completa y checklist de release

**Descripción:** Ejecutar la verificación final end-to-end y actualizar
`tasks/todo.md`. Confirmar que cada hallazgo tiene su test de regresión y que el
contrato del orquestador Go no cambió.

**Acceptance criteria:**
- [ ] Suite completa, lint, formato y cobertura pasan.
- [ ] Matriz manual de `curl` completa: `401` con ID, `415`, `413` chunked,
      `409`, `404`, `503` en `PUT`/`DELETE`, `404` en `/metrics`.
- [ ] `X-Request-ID` válido se eco; inválido se reemplaza; access log lo incluye.
- [ ] CORS no devuelve `*`.
- [ ] README/SPEC revisados; no hay contradicciones.
- [ ] `tasks/todo.md` actualizado y **revisión humana** registrada.

**Verification:**
- [ ] `uv run pytest --cov=app --cov-fail-under=85`
- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv sync --frozen && uv lock --check`
- [ ] `curl -i localhost:8082/texts?checksum=x` ⇒ `401` + `x-request-id`
- [ ] `curl -i -H "X-Request-ID: test-123" ...` ⇒ eco
- [ ] `curl -i -X POST ... -H "Transfer-Encoding: chunked" ...` ⇒ `413`
- [ ] `curl -i -X PUT ...` con Mongo caído ⇒ `503`
- [ ] `curl -i -X DELETE ...` con Mongo caído ⇒ `503`
- [ ] `curl -i localhost:8082/metrics` ⇒ `404`
- [ ] `curl -i -H "Origin: https://evil.example" ...` ⇒ sin CORS `*`

**Dependencies:** R1–R19
**Files likely touched:** `tasks/plan.md`, `tasks/todo.md`
**Estimated scope:** Small

## Risks and Mitigations

| Riesgo | Impacto | Mitigación | Tarea |
|---|---|---|---|
| Reordenar middleware rompe `401 → 415 → 413 → 400` | Alto | Test de orden existente + test nuevo de `401` con ID | R4 |
| Bufferizar el body para medir `chunked` aumenta memoria | Medio | Límite duro; test de carga; alternativa de rechazo en Traefik | R5 |
| Retry de Consul oculta una caída prolongada | Medio | Política explícita, logs y timeout acotado | R9 |
| Retry de Mongo duplica escrituras | Alto | No reintentar escrituras no idempotentes; solo lecturas | R17 |
| Eliminar CORS rompe un cliente navegador no inventariado | Medio | Confirmar con el humano; configurar orígenes explícitos si existe | R8 |
| Cambios de config rompen alias `MONGODB_*`/`SERVICE_API_TOKEN` | Medio | Tests de alias y defaults; documentar migración | R6, R16 |
| Eliminar `count()`/índice rompe tests o expectativas de SPEC | Bajo | Actualizar tests y SPEC en la misma tarea | R11, R12, R16 |
| El fake sigue divergiendo del repositorio real | Medio | Hacer que lance `ChecksumAlreadyExistsError` y cubrir con tests de contrato | R1 |
| La cobertura cae al eliminar métricas | Bajo | Recalcular umbral sobre código real; no excluir código | R10, R19 |
| Logs de negocio filtran texto o metadata | Alto | Revisión de campos permitidos + test de logs | R18 |

## Open Questions

1. **Consul:** ¿el fallo de registro debe impedir el arranque (fail-fast) o el
   servicio debe arrancar sin registro y reintentar en background? El plan deja
   ambas opciones, pero hay que elegir una antes de R9.
2. **CORS:** ¿existe algún cliente navegador real? Si no, R8 elimina el
   middleware; si sí, hay que definir la lista de orígenes.
3. **`DocumentTooLargeError`:** el plan elige heredar de
   `PayloadTooLargeError`. ¿Se prefiere eliminarlo y lanzar
   `PayloadTooLargeError` directamente desde el repositorio?
4. **`count()`/`ping`:** el plan elimina `count()` porque no se usa. ¿Se quiere
   un `ping` real en el puerto para futuros probes?
5. **Readiness:** ¿el TTL de caché de `/readyz` debe ser configurable o alcanza
   con 1 s fijo?
6. **Retry de Mongo:** ¿se acepta no reintentar automáticamente ninguna
   escritura y delegar en el orquestador? El plan recomienda esa opción.
7. **Secretos:** ¿la rotación de token queda fuera de esta release? El plan
   asume que sí; solo documenta la recomendación.

## Definition of Done de la remediación

- [ ] Los 15 hallazgos del informe tienen un test de regresión que falla sin el
      fix y pasa con él.
- [ ] No queda ningún `500` donde el contrato exige `413`/`503`.
- [ ] `X-Request-ID` está en todas las respuestas y en todos los logs de `app.*`.
- [ ] No existe endpoint ni dependencia de métricas.
- [ ] CORS no usa `*`.
- [ ] No hay dependencias no declaradas.
- [ ] `uv run pytest --cov=app --cov-fail-under=85`, `ruff check` y
      `ruff format --check` pasan.
- [ ] README/SPEC coinciden con el código.
- [ ] Revisión humana aprobada antes de reintentar el despliegue.
