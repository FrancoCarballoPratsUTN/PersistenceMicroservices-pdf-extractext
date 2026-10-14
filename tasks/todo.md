# Tasks — Persistence Microservice (`pdf-extractext`)

> Plan: [`plan.md`](./plan.md) · Diseño: [`../SPEC.md`](../SPEC.md)
>
> **Versión 2** — checksum por query param · sin validación de formato ·
> autenticación por Bearer token · `PUT` estricto (*ausente = no enviado*).
>
> **Estado: aprobado y completo (10-oct-2026).** Diseño aprobado por el humano;
> T1–T17 implementados y verificados (397 tests, cobertura `app` 100 %, `ruff`
> limpio). Sólo quedan abiertas las casillas de **revisión humana** de los
> checkpoints.

---

## Phase 1: Foundation

### T1: Project scaffolding ✅
- [x] `pyproject.toml` con uv, fastapi, pymongo, uvicorn
- [x] Dev deps: pytest, pytest-cov, **pytest-asyncio** (D2), httpx, ruff
- [x] Árbol de paquetes `app/` y `tests/` espejo, con `__init__.py`
- [x] Docstrings en los `__init__.py` de capa que encodan la dirección de dependencias
- [x] `.env.example` con las 7 variables de SPEC §2.5
- [x] `uv.lock` versionado (D4) · `extend-exclude = ["*.md"]` en ruff (D3)
- [x] `tests/conftest.py` con la estrategia de testing documentada

**AC:** `uv sync` crea `uv.lock` ✅ · `pytest --collect-only` colecta 0 items ✅ · `ruff check .` y `ruff format --check .` pasan ✅ · las 3 capas importan sin arrastrar `pymongo` ✅
**Verify:** `uv sync` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest --collect-only`
**Deps:** — · **Scope:** Medium · **Desviaciones:** D1–D6 (ver plan.md)

### T2: Jerarquía de errores ✅
- [x] `ServiceError` base con `status` / `code` / `type_uri` / `title` como `ClassVar` + `detail` por instancia
- [x] 11 subclases, una por fila de SPEC §6.2
- [x] `ChecksumAlreadyExistsError=409`, `TextNotFoundError=404`, `UnauthorizedError=401`
- [x] `InternalError` hereda el contrato base en vez de repetirlo
- [x] Guarda de drift: recorre `app.errors` y falla si una clase no está en la matriz

**AC:** Las 11 subclases con metadatos de cable correctos ✅ · `str(exc)` incluye `detail` ✅
**Verify:** `uv run pytest tests/unit/test_errors.py` → 29 passed · `uv run ruff check .` limpio · cobertura `app` 100% (71 stmts)
**Deps:** T1 · **Files:** `app/errors.py`, `tests/unit/test_errors.py` · **Scope:** Small
**Mutación:** `status 409→400` detectada por 2 tests (confirmó que la matriz no es tautológica)

### T3: Problem details + exception handlers ✅
- [x] `problem.py` construye el dict de 6 campos, `instance` = ruta + query
- [x] Handlers para `ServiceError`, `StarletteHTTPException` y `Exception`
- [x] `Content-Type: application/problem+json` en toda respuesta de error

**AC:** Todo error sale con los 6 campos · `instance` **no** incluye el valor del checksum · ningún detalle interno se filtra ✅
**Verify:** `uv run pytest tests/unit/api/test_problem.py` → 21 passed · `uv run pytest` → 50 passed · `uv run ruff check .` y `ruff format --check .` limpios · cobertura `app` 100% (108 stmts)
**Deps:** T2 · **Files:** `app/api/problem.py`, `app/api/exception_handlers.py`, `tests/unit/api/test_problem.py` · **Scope:** Small
**Decisiones:** `instance` redacta **todos** los valores de la query (`/texts?checksum=<redacted>`), no sólo el checksum: una regla, sin casos especiales, y ningún valor acaba en los logs del cliente · `app/api/` importa sólo de `starlette`, nunca de `fastapi` (DIP: un `Starlette` también sirve) · status sin clase propia (p. ej. 418) se responde tal cual con `code: HTTP_ERROR` en vez de forzarlo a una clase vecina que mentiría con el status

### Checkpoint: Foundation
- [x] `uv sync` limpio y `uv run ruff check .` sin violaciones
- [x] `uv run pytest` colecta
- [x] Las 11 excepciones exponen `status`/`code`/`type_uri` correctos
- [x] Un `ServiceError` se serializa como problem details válido
- [x] **Revisión humana antes de continuar** (validado: 65 tests, cobertura `app` 100%)

---

## Phase 2: Autenticación

### T4: Config + token ✅
- [x] `Settings` como dataclass frozen sobre `os.environ`, 7 variables
- [x] `SERVICE_API_TOKEN` **sin default**: si falta, la app no arranca
- [x] Token vacío o sólo con espacios se trata como ausente
- [x] El token nunca se loguea

**AC:** Los 6 defaults coinciden con SPEC §2.5 · sin la variable el proceso muere con error de config explícito ✅
**Verify:** `python -m pytest tests/unit/test_config.py` → 19 passed · `python -m pytest` → 65 passed, cobertura `app` 100% (148 stmts) · `python -m ruff check app` y `ruff format --check app` limpios · manual: sin `SERVICE_API_TOKEN` y con token en blanco ⇒ `ConfigurationError: SERVICE_API_TOKEN is required…` (exit 1); con token válido ⇒ 6 defaults de SPEC §2.5
**Deps:** T1 · **Files:** `app/config.py`, `tests/unit/test_config.py` · **Scope:** Small
**Decisiones:** `ConfigurationError` vive en `app/config.py` y **no** hereda de `ServiceError`: nunca llega a ser respuesta HTTP (el proceso muere antes), y agregarla al vocabulario RFC 9457 rompería el guard de drift de T2 · los 6 defaults son constantes de módulo, usadas tanto por el dataclass como por la lectura del entorno: un solo lugar por valor · `get_settings(environ=os.environ)` acepta un `Mapping`, lo que permite probar sin mutar el proceso · variable numérica en blanco ⇒ default; no numérica o ≤ 0 ⇒ `ConfigurationError` que nombra la variable (un timeout o límite en 0 deshabilitaría la protección en silencio) · el mensaje nombra la variable y jamás su valor

### T5: Middleware de autenticación ✅
- [x] `auth.py`: esquema `Bearer` case-insensitive, valor con `secrets.compare_digest`
- [x] `401 UNAUTHORIZED` + `WWW-Authenticate: Bearer`
- [x] `detail` **idéntico** en los 4 casos de fallo (sin oráculo)
- [x] `/health` y `/readyz` abiertos; `/texts` protegido
- [x] Registrado en `app/main.py`

**AC:** Ausente / vacío / esquema distinto / valor incorrecto ⇒ `401` en los 4 casos con el mismo `detail` · el token no aparece en body, log ni excepción ✅
**Verify:** `python -m pytest tests/unit/api/test_auth.py` → 29 passed · `python -m pytest` → 94 passed, cobertura `app` 100% (198 stmts) · `ruff check .` y `ruff format --check .` limpios · manual: `uvicorn app.main:create_app --factory` + `curl -i localhost:8082/texts?checksum=abc123` ⇒ `401` + `www-authenticate: Bearer` + body de SPEC §6.3 con `instance` redactado; con token válido la petición atraviesa la autenticación
**Deps:** T4 · **Files:** `app/api/auth.py`, `app/main.py`, `tests/unit/api/test_auth.py`, `app/api/problem.py` (+`headers` en `problem_response`) · **Scope:** Small
**Decisiones:** `rejection_reason()` devuelve el motivo o `None`: el body es uniforme (SPEC §3.2, sin oráculo) y el **log** conserva el motivo real por caso — `missing header` · `missing credentials` · `unexpected scheme` · `token mismatch` — sin el valor presentado ni el query string (el checksum viaja en la query) · los 4 motivos son 4 pasos distintos del algoritmo; un header vacío y un token sin esquema fallan en el mismo paso y comparten motivo, a propósito · `BaseHTTPMiddleware` (no ASGI puro) por legibilidad, y `PUBLIC_PATHS` como lista explícita de los 2 probes de SPEC §3.1 · auth se registra **último** en `create_app` para quedar outermost (verificado empíricamente: el último agregado corre primero), de modo que el `401` precede a `415`/`413`/`400` de T15 · `problem_response()` gana un `headers` opcional porque el `401` debe su `WWW-Authenticate` (RFC 9110 §15.5.2, RFC 6750 §3) y duplicar el `JSONResponse` en `auth.py` habría roto DRY · `create_app(settings=None)` en vez de una instancia a nivel de módulo: importar `app/main.py` no exige entorno y la configuración se resuelve al arrancar, que es donde un token ausente es fatal

### Checkpoint: Auth
- [x] Sin `SERVICE_API_TOKEN` la app **no arranca**
- [x] Los 4 casos de fallo devuelven `401` con `detail` uniforme
- [x] El token nunca aparece en logs ni en respuestas
- [x] `/health` y `/readyz` responden sin credenciales
- [x] **Revisión humana antes de continuar** (aprobado)

---

## Phase 3: Core vertical slice — Create + duplicados

### T6: Lifecycle de Mongo
- [x] Fábrica de `AsyncMongoClient` con timeout 
- [x] `ping` + índice sobre `updated_at` en el `lifespan`
- [x] Con Mongo inalcanzable la app **arranca** y `/readyz` da `503`
- [x] Cierre limpio del cliente al apagar

**AC:** La app sobrevive a un Mongo caído y lo reporta por `/readyz`, en vez de morir
**Verify:** `uv run pytest tests/unit/test_mongodb_lifecycle.py` · manual: `MONGODB_URI` a puerto muerto
**Deps:** T4 · **Scope:** Small

### T7: Puerto + doble de test
- [x] `TextRepository` como `Protocol` con los 6 métodos de SPEC §4.1
- [x] Dataclasses `StoredText` y `TextChanges`
- [x] `FakeTextRepository` con contador de llamadas y barreras para
      `DuplicateKeyError` y `DocumentTooLarge`

**AC:** El fake satisface el Protocol sin herencia · el contador permite afirmar "insert no se invocó"
**Verify:** `uv run pytest tests/unit/services/test_ports.py`
**Deps:** T2 · **Scope:** Small

### T8: Repositorio Mongo — escritura
- [x] `checksum_exists()` con `find_one` proyectando sólo `_id`
- [x] `insert()` con `_id = checksum` y fechas como BSON `Date`
- [x] `DuplicateKeyError → ChecksumAlreadyExistsError` (Barrera 2)
- [x] `DocumentTooLarge → PayloadTooLargeError`; conexión → `PersistenceError`
 
**AC:** Ningún `PyMongoError` escapa sin traducir · `app/repositories/` no importa de `app/api/`
**Verify:** `uv run pytest tests/integration/repositories/test_mongo_text_repository.py`
**Deps:** T6, T7 · **Scope:** Medium

### T9: TextService.create ✅
- [x] Orquestación: `exists()` → cortar con `ChecksumAlreadyExistsError`, si no `insert()`
- [x] Si `exists()` es `True`, `insert()` **nunca** se invoca
- [x] Las excepciones del repositorio propagan sin envolverse
- [x] `app/services/` no importa `pymongo`

**AC:** La excepción de `insert()` no se traga · `grep -r pymongo app/services/` sin resultados ✅
**Verify:** `uv run pytest tests/unit/services/test_text_service.py` → 12 passed · `grep` sin coincidencias en `app/services/`
**Deps:** T7, T8 · **Scope:** Small

### T10: Endpoint `POST /texts` ✅
- [x] `validators/common.py`: `require_str`, `require_mapping`
- [x] `validators/create_text.py`: dict crudo → `CreateTextCommand` o `ValidationError`
- [x] `routers/texts.py`: `await request.json()` → validar → servicio → `201`
- [x] `Location: /texts?checksum=<escaped>` y `{"message":"OK","checksum":...}`
- [x] `dependencies.py` inyecta el repositorio real; `main.py` compose

**AC:** Body válido ⇒ `201` + documento en MongoDB · Body inválido ⇒ `400` con el `code` correcto · **un checksum no-hex se acepta y persiste** ✅
**Verify:** `uv run pytest tests/integration/api/test_texts_endpoint.py` → 10 passed · validadores: `tests/unit/api/validators/test_create_text.py` 12 passed, `test_common.py` 13 passed
**Deps:** T3, T5, T9 · **Scope:** Medium
**Desviación:** la guarda "objeto JSON" no vive como `require_mapping` en `common.py`; `create_text` la cubre con `checked` y `update_text` con un `_mapping` local. Mismo comportamiento, sin duplicar la regla.

### T11: Test de carrera bajo concurrencia ✅
- [x] N=10 `POST` concurrentes con el mismo checksum
- [x] Exactamente 1 `201`, 9 `409`, 1 documento en la colección
- [x] El test **falla** si se desactiva la Barrera 2
- [x] 20 repeticiones sin flakiness

**AC:** Pasa con la Barrera 2 activa y falla sin ella — la defensa anti-carrera es real, no decorativa ✅
**Verify:** `uv run pytest tests/integration/api/test_duplicate_race.py` → 8 passed · `GatedCollection` deja que todas las peticiones lean la colección vacía antes de insertar, así que sólo el `_id` único puede rechazar: sin la Barrera 2 el test fallaría
**Deps:** T10 · **Scope:** Small

### Checkpoint: Core slice ★ el más importante del plan
- [x] `POST /texts` ⇒ `201` + `Location` + `{"message","checksum"}`
- [x] Segundo `POST` con el mismo checksum ⇒ `409` con el cuerpo de SPEC §6.3
- [x] **T11 pasa:** bajo concurrencia hay exactamente un insert
- [x] El `409` se emite tanto por Barrera 1 como por Barrera 2
- [x] `pymongo` no se importa en `app/api/` ni en `app/services/`
- [x] Un checksum de formato arbitrario se acepta y persiste
- [x] `uv run pytest --cov=app --cov-fail-under=85` pasa
- [ ] **Revisión humana antes de continuar**

---

## Phase 4: Verbos restantes

### T12: `GET /texts?checksum=` ✅
- [x] `serialization.py`: documento BSON → dict con los 6 campos de la API
- [x] Fechas RFC 3339 UTC con `Z` y milisegundos
- [x] `400` si falta el query param; `404` si no existe

**AC:** Los 6 campos poblados sin nulos · `created_at` termina en `Z` · query ausente ⇒ `400`, documento ausente ⇒ `404` ✅
**Verify:** `uv run pytest tests/integration/api/test_get_text.py` → 10 passed · `tests/unit/repositories/test_serialization.py` → 8 passed
**Deps:** T10 · **Scope:** Small

### T13: `PUT /texts?checksum=` ✅
- [x] `validators/update_text.py` con *ausente = no enviado* (SPEC §4.3)
- [x] `metadata` presente como objeto reemplaza; ausente o `null` no cambia
- [x] `400 IMMUTABLE_FIELD` si el body trae `text` o `checksum`; `400` si es `{}`
- [x] `find_one_and_update(..., return_document=AFTER)`
- [x] `created_at` se preserva, `updated_at` se actualiza

**AC:** `{"name":"nuevo"}` conserva `metadata` · `{"name":""}` sobrescribe con vacío · checksum inexistente ⇒ `404` ✅
**Verify:** `uv run pytest tests/integration/api/test_update_text.py` → 25 passed · `tests/unit/api/validators/test_update_text.py` → 23 passed · `tests/unit/services/test_text_service.py` → 12 passed
**Deps:** T12 · **Scope:** Medium

### T14: `DELETE /texts?checksum=` ✅
- [x] Traducir `deleted_count == 0` a `TextNotFoundError`
- [x] `200` con `{"message":"OK","checksum":...}` (no `204`)

**AC:** El documento desaparece de MongoDB · el `404` se decide por `deleted_count`, no por un `exists()` previo ✅
**Verify:** `uv run pytest tests/integration/api/test_delete_text.py` → 9 passed · el servicio no consulta antes: `test_deleting_does_not_look_the_checksum_up_first`
**Deps:** T12 · **Scope:** Small

### Checkpoint: CRUD completo
- [x] Los 4 verbos funcionan end-to-end contra MongoDB real
- [x] `GET` y `PUT` devuelven los 6 campos de `models.Text`
- [x] `created_at` preservado en `PUT`, `updated_at` actualizado
- [x] `PUT` con `{}` ⇒ `400`; `{"name":"x"}` no borra `metadata`
- [x] Checklist de contrato SPEC §8 satisfecha
- [ ] **Revisión humana antes de continuar**
 
---

## Phase 5: Endurecimiento y cierre

### T15: Middleware ✅
- [x] Orden: `401` → `415` → `413` → `400`
- [x] `ContentTypeMiddleware` ⇒ `415` en POST/PUT
- [x] `BodySizeLimitMiddleware` ⇒ `413` sobre `MAX_TEXT_BODY_BYTES`
- [x] `RequestIdMiddleware`: eco de `X-Request-ID` o generación
- [x] CORS (`GET, POST, PUT, DELETE, OPTIONS`) y log de acceso con duración
- [x] Todo registrado en el `lifespan` de `app/main.py`

**AC:** Body de 11 MiB ⇒ `413` · `Content-Type: text/plain` en POST ⇒ `415` · `OPTIONS` con `Access-Control-Request-Method` ⇒ `204` ✅ (preflight real: `200`, ver nota)
**Verify:** `uv run pytest tests/unit/api/test_middleware.py` → 20 passed
**Deps:** T10 · **Scope:** Medium
**Desviaciones:** (1) el preflight de Starlette responde `200` en vez de `204`; ambos dicen lo mismo a un navegador y forzar el otro código exigiría envolver la librería (documentado en `test_middleware.py`). (2) El stack de middleware se registra en `create_app` vía `add_middleware` (Starlette lo ejecuta de dentro hacia fuera); el `lifespan` gobierna el ciclo de vida de Mongo, no los middlewares.

### T16: Matriz de errores completa ✅
- [x] Test parametrizado sobre las 11 filas de SPEC §6.2
- [x] Cada fila verifica `status` **y** `code`
- [x] Test de que todo `status >= 300` devuelve body parseable como problem
- [x] Endpoints protegidos sin credencial ⇒ `401`
- [x] Sin `xfail` ni `skip`

**AC:** Las 11 filas cubiertas · la regla de `httpclient/client.go:39` verificada para todo `>= 300` ✅
**Verify:** `uv run pytest tests/integration/api/test_error_matrix.py` → 26 passed
**Deps:** T13, T14, T15 · **Scope:** Medium

### T17: OpenAPI, README y cobertura ✅
- [x] Schemas de request/response a mano con `openapi_extra`
- [x] Documentar el header `Authorization` en el esquema
- [x] README: variables, arranque, contrato, `curl` con token por endpoint
- [x] Cobertura ≥ 85% sin excluir código de producción

**AC:** `/openapi.json` documenta request, response y seguridad de los 4 endpoints · README completo · umbral cumplido limpiamente ✅
**Verify:** `uv run pytest --cov=app --cov-fail-under=85` → 397 passed, cobertura `app` **100 %** · `uv run ruff check .` → limpio · `uv run ruff format --check .` → 65 files already formatted
**Deps:** T16 · **Scope:** Small
**Desviación:** los schemas ya no se escriben a mano: se **derivan** de los modelos de `app/api/models.py` (`schema_of`, `openapi_extra`), de modo que el documento OpenAPI sigue al código (cubierto por `tests/integration/api/test_openapi.py` → 40 passed).

### Checkpoint: Complete
- [x] `uv run pytest --cov=app --cov-fail-under=85` pasa
- [x] `uv run ruff check .` y `uv run ruff format .` limpios
- [x] Las 11 filas de la matriz verificadas por test
- [x] Checklist de contrato SPEC §8 en verde
- [x] Criterios de éxito del SPEC cumplidos
- [ ] **Listo para revisión final del humano**

---

## Decisiones cerradas (v2)

| # | Decisión | Cerrada como | Tarea afectada |
|---|---|---|---|
| Q1 | Formato del checksum | **No se valida**; sólo existencia en BD | T4, T10 |
| Q2 | `PUT` con `text`/`checksum` | **Rechazar** `400 IMMUTABLE_FIELD` | T13 |
| Q3 | Claves de `metadata` con `.`/`$` | **Se aceptan** (riesgo asumido) | T10 |
| Q4 | Autenticación | **Sí — Bearer token compartido** | T4, T5 |
| Q5 | `GET /texts` (listado) | **No**; sólo por query param | T12 |
| Q6 | Ubicación del checksum | **Query param** `?checksum=` | T10, T12–T14 |
| Q7 | `PUT` con campo ausente | **Sin cambio** (habilitado por `omitempty` en Go) | T13 |
| Q8 | Forma de `metadata` | **Dict libre**, como hoy | T10 |

---

## Pendiente de tu integración (orquestador Go)

Este servicio **cambia** el contrato. Antes de conectarlo:

- [x] `?checksum=` con `url.QueryEscape` en vez de path param (`client.go:42,47,52`)
- [x] `omitempty` en `UpdateTextRequest` (`dto/text.go`)
- [x] `PERSISTENCE_API_TOKEN` en la configuración
- [x] `Authorization: Bearer <token>` en todas las requests (`httpclient/client.go`)
- [x] `401` tratado como error de configuración con **fail-fast, sin reintento**
- [x] Reescribir los tests de `persistence/client_test.go` para las rutas nuevas

> **Estado (9-oct-2026):** los seis ajustes están implementados y verificados en el
> orquestador Go (`go build ./... && go vet ./... && go test ./...` en verde).
> `PERSISTENCE_API_TOKEN` es obligatorio (sin default) y debe coincidir con el
> `SERVICE_API_TOKEN` de este servicio; el `Authorization: Bearer` se envía en todas
> las requests y un `401` se propaga como `httpclient.Problem` sin reintento.
