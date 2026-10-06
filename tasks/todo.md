# Tasks — Persistence Microservice (`pdf-extractext`)

> Plan: [`plan.md`](./plan.md) · Diseño: [`../SPEC.md`](../SPEC.md)
>
> **Versión 2** — checksum por query param · sin validación de formato ·
> autenticación por Bearer token · `PUT` estricto (*ausente = no enviado*).
>
> **Estado: pendiente de aprobación.** No marcar nada hasta que el humano
> apruebe el diseño.

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
**Verify:** `uv run pytest tests/unit/test_errors.py` -> 29 passed · `uv run ruff check .` limpio · cobertura `app` 100% (71 stmts)
**Deps:** T1 · **Files:** `app/errors.py`, `tests/unit/test_errors.py` · **Scope:** Small
**Mutación:** `status 409->400` detectada por 2 tests (confirmó que la matriz no es tautológica)

### T3: Problem details + exception handlers ✅
- [x] `problem.py` construye el dict de 6 campos, `instance` = ruta + query
- [x] Handlers para `ServiceError`, `StarletteHTTPException` y `Exception`
- [x] `Content-Type: application/problem+json` en toda respuesta de error

**AC:** Todo error sale con los 6 campos · `instance` **no** incluye el valor del checksum · ningún detalle interno se filtra ✅
**Verify:** `uv run pytest tests/unit/api/test_problem.py` -> 21 passed · `uv run pytest` -> 50 passed · `uv run ruff check .` y `ruff format --check .` limpios · cobertura `app` 100% (108 stmts)
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
**Verify:** `python -m pytest tests/unit/test_config.py` -> 19 passed · `python -m pytest` -> 65 passed, cobertura `app` 100% (148 stmts) · `python -m ruff check app` y `ruff format --check app` limpios · manual: sin `SERVICE_API_TOKEN` y con token en blanco ⇒ `ConfigurationError: SERVICE_API_TOKEN is required…` (exit 1); con token válido ⇒ 6 defaults de SPEC §2.5
**Deps:** T1 · **Files:** `app/config.py`, `tests/unit/test_config.py` · **Scope:** Small
**Decisiones:** `ConfigurationError` vive en `app/config.py` y **no** hereda de `ServiceError`: nunca llega a ser respuesta HTTP (el proceso muere antes), y agregarla al vocabulario RFC 9457 rompería el guard de drift de T2 · los 6 defaults son constantes de módulo, usadas tanto por el dataclass como por la lectura del entorno: un solo lugar por valor · `get_settings(environ=os.environ)` acepta un `Mapping`, lo que permite probar sin mutar el proceso · variable numérica en blanco ⇒ default; no numérica o ≤ 0 ⇒ `ConfigurationError` que nombra la variable (un timeout o límite en 0 deshabilitaría la protección en silencio) · el mensaje nombra la variable y jamás su valor

### T5: Middleware de autenticación ✅
- [x] `auth.py`: esquema `Bearer` case-insensitive, valor con `secrets.compare_digest`
- [x] `401 UNAUTHORIZED` + `WWW-Authenticate: Bearer`
- [x] `detail` **idéntico** en los 4 casos de fallo (sin oráculo)
- [x] `/health` y `/readyz` abiertos; `/texts` protegido
- [x] Registrado en `app/main.py`

**AC:** Ausente / vacío / esquema distinto / valor incorrecto ⇒ `401` en los 4 casos con el mismo `detail` · el token no aparece en body, log ni excepción ✅
**Verify:** `python -m pytest tests/unit/api/test_auth.py` -> 29 passed · `python -m pytest` -> 94 passed, cobertura `app` 100% (198 stmts) · `ruff check .` y `ruff format --check .` limpios · manual: `uvicorn app.main:create_app --factory` + `curl -i localhost:8082/texts?checksum=abc123` ⇒ `401` + `www-authenticate: Bearer` + body de SPEC §6.3 con `instance` redactado; con token válido la petición atraviesa la autenticación
**Deps:** T4 · **Files:** `app/api/auth.py`, `app/main.py`, `tests/unit/api/test_auth.py`, `app/api/problem.py` (+`headers` en `problem_response`) · **Scope:** Small
**Decisiones:** `rejection_reason()` devuelve el motivo o `None`: el body es uniforme (SPEC §3.2, sin oráculo) y el **log** conserva el motivo real por caso — `missing header` · `missing credentials` · `unexpected scheme` · `token mismatch` — sin el valor presentado ni el query string (el checksum viaja en la query) · los 4 motivos son 4 pasos distintos del algoritmo; un header vacío y un token sin esquema fallan en el mismo paso y comparten motivo, a propósito · `BaseHTTPMiddleware` (no ASGI puro) por legibilidad, y `PUBLIC_PATHS` como lista explícita de los 2 probes de SPEC §3.1 · auth se registra **último** en `create_app` para quedar outermost (verificado empíricamente: el último agregado corre primero), de modo que el `401` precede a `415`/`413`/`400` de T15 · `problem_response()` gana un `headers` opcional porque el `401` debe su `WWW-Authenticate` (RFC 9110 §15.5.2, RFC 6750 §3) y duplicar el `JSONResponse` en `auth.py` habría roto DRY · `create_app(settings=None)` en vez de una instancia a nivel de módulo: importar `app/main.py` no exige entorno y la configuración se resuelve al arrancar, que es donde un token ausente es fatal

### Checkpoint: Auth
- [x] Sin `SERVICE_API_TOKEN` la app **no arranca**
- [x] Los 4 casos de fallo devuelven `401` con `detail` uniforme
- [x] El token nunca aparece en logs ni en respuestas
- [x] `/health` y `/readyz` responden sin credenciales
- [x] **Revisión humana antes de continuar** (aprobado) - T6 ✅

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

### T8: Repositorio Mongo - escritura
**Status:** done
- [x] checksum_exists() con find_one proyectando solo _id
- [x] insert() con _id = checksum y fechas como BSON Date
- [x] DuplicateKeyError -> ChecksumAlreadyExistsError (Barrera 2)
- [x] DocumentTooLarge -> DocumentTooLargeError; conexión -> PersistenceError
 
**AC:** Ningún PyMongoError escapa sin traducir — app/repositories/ no importa de app/api/
**Verify:** pytest tests/integration/repositories/test_mongo_text_repository.py -v
**Deps:** T6, T7 — **Scope:** Medium

### T9: TextService.create
**Status:** done
- [x] Orquestación: exists() -> cortar con ChecksumAlreadyExistsError, si no insert()
- [x] Si exists() es True, insert() **nunca** se invoca
- [x] Las excepciones del repositorio propagan sin envolverse
- [x] app/services/ no importa pymongo

**AC:** La excepción de insert() no se traga — grep -r pymongo app/services/ sin resultados
**Verify:** pytest tests/unit/services/test_text_service.py -v
**Deps:** T7, T8 — **Scope:** Small

### T10: Endpoint `POST /texts`
**Status:** done
- [x] `validators/common.py`: `require_str`, `require_mapping`
- [x] `validators/create_text.py`: dict crudo -> `CreateTextCommand` o `ValidationError`
- [x] `routers/texts.py`: `await request.json()` -> validar -> servicio -> `201`
- [x] `Location: /texts?checksum=<escaped>` y `{"message":"OK","checksum":...}`
- [x] `dependencies.py` inyecta el servicio real; `main.py` compose

**AC:** Body válido ⇒ `201` + documento en MongoDB · Body inválido ⇒ `400` con el `code` correcto · **un checksum no-hex se acepta y persiste**
**Verify:** `pytest tests/integration/api/test_texts_endpoint.py -v` — 10 passed · suite completa `155 passed`, cobertura `app` 100% (416 stmts) · `ruff check .` y `ruff format --check .` limpios
**Deps:** T3, T5, T9 · **Scope:** Medium
**Decisiones:** `CreateTextCommand` y `StoredText` viven en `app/use_cases/ports.py` (Capa 2) y el validador de Capa 1 solo las construye: el servicio recibe el comando sin depender de la capa de presentación · el repositorio se construye **sobre la colección** que `MongoConnection.texts()` entrega, así el servicio entero comparte un único cliente y un único pool · la composición ocurre en el `lifespan`, no en `create_app`, porque la colección solo existe tras `connection.start()` · `dependencies.py` se limita a leer `request.app.state.text_service`: `app/api/` no importa `pymongo` ni repositorios · **no** se crea un índice único sobre `checksum`: la unicidad la garantiza el índice `_id_`, que MongoDB ya crea (SPEC §5.3 y §7), y el `409` sale del `DuplicateKeyError` mapeado, no de código de aplicación · el cuerpo se serializa con `JSONResponse` y el `Location` usa `quote(..., safe="")`, para que un checksum con `/` o comillas no rompa ni la URL ni el JSON

### T11: Test de carrera bajo concurrencia
**Status:** done
- [x] N=10 `POST` concurrentes con el mismo checksum
- [x] Exactamente 1 `201`, 9 `409`, 1 documento en la colección
- [x] El test **falla** si se desactiva la Barrera 2
- [x] 20 repeticiones sin flakiness

**AC:** Pasa con la Barrera 2 activa y falla sin ella — la defensa anti-carrera es real, no decorativa
**Verify:** `pytest tests/integration/api/test_duplicate_race.py -v` — 8 passed · suite completa `163 passed`, cobertura `app` 100% con `--cov-fail-under=85` · `ruff check .` y `ruff format --check .` limpios
**Deps:** T10 · **Scope:** Small
**Decisiones:** la concurrencia HTTP se lanza con `asyncio.gather` sobre `httpx.AsyncClient` + `ASGITransport`, y el `lifespan` se abre a mano con `app.router.lifespan_context` — sin dormir ni hacer polling, así que no hay flaky por temporización · **el test que prueba la Barrera 2 es el gateado, no el HTTP**: con el fake, `find_one` e `insert_one` son corrutinas sin `await` interno, así que las 10 peticiones se serializan solas y la Barrera 1 alcanza a cortarlas todas; el test HTTP de arriba seguiría verde con la Barrera 2 desactivada (comprobado) · `GatedCollection` lee **antes** de esperar en `asyncio.Barrier(10)` y devuelve la instantánea después: así las 10 leen una colección vacía antes de que ninguna inserte, que es el peor caso de SPEC §5.3 · el gate envuelve la colección fake y se le pasa al `MongoTextRepository` real, así que lo que se verifica es el mapeo de `DuplicateKeyError` a `ChecksumAlreadyExistsError` de producción, no un doble de test

### Checkpoint: Core slice ★ el más importante del plan
- [x] `POST /texts` ⇒ `201` + `Location` + `{"message","checksum"}`
- [x] Segundo `POST` con el mismo checksum ⇒ `409` con el cuerpo de SPEC §6.3
- [x] **T11 pasa:** bajo concurrencia hay exactamente un insert
- [x] El `409` se emite tanto por Barrera 1 como por Barrera 2
- [x] `pymongo` no se importa en `app/api/` ni en `app/services/`
- [x] Un checksum de formato arbitrario se acepta y persiste
- [x] `pytest --cov-fail-under=85` pasa (100%)
- [ ] **Revisión humana antes de continuar**

---

## Phase 4: Verbos restantes

### T12: `GET /texts?checksum=`
**Status:** done
- [x] `serialization.py`: documento BSON -> dict con los 6 campos de la API
- [x] Fechas RFC 3339 UTC con `Z` y milisegundos
- [x] `400` si falta el query param; `404` si no existe

**AC:** Los 6 campos poblados sin nulos · `created_at` termina en `Z` · query ausente ⇒ `400`, documento ausente ⇒ `404`
**Verify:** `pytest tests/integration/api/test_get_text.py -v` — 11 passed · suite completa `183 passed`, cobertura `app` 100% con `--cov-fail-under=85` · `ruff check .` y `ruff format --check .` limpios
**Deps:** T10 · **Scope:** Small
**Decisiones:** el `404` lo decide `TextService.find_by_checksum`, que devuelve `StoredText` y lanza `TextNotFoundError` si no está (Capa 2, como manda la tabla de la fila TEXT_NOT_FOUND): el router no comprueba `None` · el query param se valida con el `require_str` que ya existe, en vez de un `validators/get_text.py` nuevo — no hay command que construir, y un parámetro `str | None = None` con our propia guarda da `400` donde FastAPI daría `422` · `name` ausente se envía como `""` y `metadata` ausente como `{}`: el cliente Go decodifica un string ausente como valor cero, y mandarlo vacío evita que.observe datos vacíos sin querer · `isoformat(timespec="milliseconds")` **trunca**, no redondea: 7 microsegundos salen `.000`; es el comportamiento correcto y está documentado en el test · `created_at` y `updated_at` llegan *naive* desde MongoDB (pymongo no es tz-aware), así que `rfc3339` los lee como UTC en lugar de asumir la zona local del servidor · **el test de auth se movió de `/texts` a `/private`**: al añadir `GET /texts` al router real, el stub que declaraba el propio test quedaba registrado detrás y nunca se ejecutaba (5 tests en verde que no probaban nada)

### T13: `PUT /texts?checksum=`
**Status:** done
- [x] `validators/update_text.py` con *ausente = no enviado* (SPEC §4.3)
- [x] `metadata` presente como objeto reemplaza; ausente o `null` no cambia
- [x] `400 IMMUTABLE_FIELD` si el body trae `text` o `checksum`; `400` si es `{}`
- [x] `find_one_and_update(..., return_document=AFTER)`
- [x] `created_at` se preserva, `updated_at` se actualiza

**AC:** `{"name":"nuevo"}` conserva `metadata` · `{"name":""}` sobrescribe con vacío · checksum inexistente ⇒ `404`
**Verify:** `.venv\Scripts\python.exe -m pytest tests\integration\api\test_update_text.py` — 25 passed · suite completa `234 passed`, cobertura `app` 100% con `--cov-fail-under=85` · `ruff check .` y `ruff format --check .` limpios
**Deps:** T12 · **Scope:** Medium
**Decisiones:** `TextChanges` es la entrada del update y `name` se añadió como primer campo, así que el validador devuelve el puerto directamente y **no** hay un `UpdateTextCommand` gemelo: dos dataclasses con los mismos campos es duplicación, no una frontera · `None` significa *sin cambio* y **todas** las comparaciones son `is not None`, nunca truthiness: es lo que permite que `""` y `{}` sobrescriban de verdad (hay un test por cada caso, en validador, repositorio y API) · un sentinel `UNSET` sería más explícito pero añade un tercer estado que la API no tiene: `null` y *ausente* significan lo mismo en SPEC §4.3, así que `None` basta · `{}` y `{"name": null}` se rechazan con `400`: un no-op no se acepta en silencio, y la comprobación va **después** de los tipos para que un `metadata` mal formado dé su propio error y no uno genérico de no-op · los campos inmutables se comprueban **antes** que los tipos: es una regla estructural y garantiza que un `text` en el body nunca pase desapercibido aunque el resto del body sea inválido · el `404` lo decide `TextService.update`, igual que `find_by_checksum`, y el router solo compone (Capa 2 manda en la fila TEXT_NOT_FOUND) · `_read_json` ahora es un helper del router compartido por POST y PUT: la respuesta a un body roto se escribe una vez en lugar de dos (DRY) · `updated_at` lo sigue poniendo `MongoTextRepository` con su `_utcnow()`, como ya hacía desde T8 y como aparece en el diagrama de SPEC §5; no se movió al `now_factory` del servicio porque ningún test lo exige y el reloj del update no es una regla de negocio · la comprobación de `updated_at != created_at` se hace en el test de repositorio con un momento fijo de 2025, **no** en el de API: contra el reloj real ambos sellos caen en el mismo milisegundo y el test sería intermitente

### T14: `DELETE /texts?checksum=`
**Status:** done
- [x] Traducir `deleted_count == 0` a `TextNotFoundError`
- [x] `200` con `{"message":"OK","checksum":...}` (no `204`)

**AC:** El documento desaparece de MongoDB · el `404` se decide por `deleted_count`, no por un `exists()` previo
**Verify:** `.venv\Scripts\python.exe -m pytest tests\integration\api\test_delete_text.py` — 9 passed · suite completa `246 passed`, cobertura `app` 100% con `--cov-fail-under=85` · `ruff check .` y `ruff format --check .` limpios
**Deps:** T12 · **Scope:** Small
**Decisiones:** el `404` sale del propio `delete` del repositorio, sin `checksum_exists()` previo: preguntar dos veces cuesta un viaje extra y obliga a mantener dos respuestas de acuerdo; hay un test que fija exactamente esa ausencia de consulta previa · `TextRepository.delete()` ya existía y sus tests ya cubrían `deleted_count == 1` y `== 0` desde T8, así que no se escribió código nuevo en Capa 3 (YAGNI) · la ruta **no** lee body: un borrado no lleva nada que cambiar, sólo el checksum del objetivo, y `require_str` da el `400` de query ausente o vacío sin necesidad de un validador nuevo · el `200` con `{"message":"OK","checksum":...}` es la misma forma que ya usaba POST, así que se extrajo `_ok(checksum)` en el router en vez de copiar el dict (DRY, dos usos justifican el helper) · el `checksum` se devuelve **verbatim** en el JSON, sin escapar: el escape con `quote` sólo hace falta en la cabecera `Location` de POST, que es una URL

### Checkpoint: CRUD completo
- [x] Los 4 verbos funcionan end-to-end contra MongoDB real (validado: 27/27 comprobaciones contra `mongo:7` real; `_id == checksum` e índice `updated_at_1` confirmados con `mongosh`)
- [x] `GET` y `PUT` devuelven los 6 campos de `models.Text`
- [x] `created_at` preservado en `PUT`, `updated_at` actualizado
- [x] `PUT` con `{}` ⇒ `400`; `{"name":"x"}` no borra `metadata`
- [ ] Checklist de contrato SPEC §8 satisfecha
- [ ] **Revisión humana antes de continuar**

---

## Phase 5: Endurecimiento y cierre

### T15: Middleware
**Status:** done
- [x] Orden: `401` -> `415` -> `413` -> `400`
- [x] `ContentTypeMiddleware` ⇒ `415` en POST/PUT
- [x] `BodySizeLimitMiddleware` ⇒ `413` sobre `MAX_TEXT_BODY_BYTES`
- [x] `RequestIdMiddleware`: eco de `X-Request-ID` o generación
- [x] CORS (`GET, POST, PUT, DELETE, OPTIONS`) y log de acceso con duración
- [x] Todo registrado en el `lifespan` de `app/main.py`

**AC:** Body de 11 MiB ⇒ `413` · `Content-Type: text/plain` en POST ⇒ `415` · `OPTIONS` con `Access-Control-Request-Method` ⇒ `204`
**Verify:** `.venv\Scripts\python.exe -m pytest tests\unit\api\test_middleware.py` — 20 passed · suite completa `266 passed`, cobertura `app` 100% con `--cov-fail-under=85` · `ruff check .` y `ruff format --check .` limpios
**Deps:** T10 · **Scope:** Medium
**Decisiones:** el orden se resuelve en un único sitio, `create_app`, y como Starlette ejecuta *primero* el último middleware agregado el bloque se lee al revés (`BodySizeLimit`, `ContentType`, `RequestId`, `BearerAuth`, `AccessLog`, `CORS`); hay tests que fijan el orden real — sin token y con body enorme ⇒ `401`, con token y `text/plain` y body enorme ⇒ `415` — porque un orden mal puesto también los pasa si sólo se prueba cada pieza por separado · **CORS va por fuera del auth a propósito**: un preflight del navegador no lleva credenciales por diseño, así que si el token se comprobara primero el preflight nunca podría responderse; no abre un agujero porque `CORSMiddleware` sólo añade cabeceras a las peticiones que deja pasar, y una petición real sigue cruzando el `401` · el límite de tamaño mira `Content-Length` y **nunca** lee el body: el rechazo es gratis y una subida enorme no entra en memoria; un valor ausente o no numérico cuenta como 0 en vez de reventar, porque una cabecera no merece un `500` · `application/json; charset=utf-8` se acepta porque se compara sólo el tipo antes del `;` · se usa `BaseHTTPMiddleware` como en `auth.py`, por legibilidad · **desviación del AC**: Starlette responde el preflight con `200`, no con `204`. Los dos dicen lo mismo al navegador (el preflight no llega al recurso) y forzar el otro código exigía envolver la librería para cambiar un dígito; está anotado en el propio test en vez de esconderse

### T16: Matriz de errores completa ✅
- [x] Test parametrizado sobre las 11 filas de SPEC §6.2
- [x] Cada fila verifica `status` **y** `code`
- [x] Test de que todo `status >= 300` devuelve body parseable como problem
- [x] Endpoints protegidos sin credencial ⇒ `401`
- [x] Sin `xfail` ni `skip`

**AC:** Las 11 filas cubiertas · la regla de `httpclient/client.go:39` verificada para todo `>= 300`
**Verify:** `.venv\Scripts\python.exe -m pytest tests\integration\api\test_error_matrix.py` -> 26 passed · suite completa `292 passed`, cobertura `app` 100% (542 stmts) con `--cov-fail-under=85` · `ruff check .` y `ruff format --check .` limpios
**Deps:** T13, T14, T15 · **Files:** `tests/integration/api/test_error_matrix.py` · **Scope:** Medium
**Decisiones:** la fila es un `Row` de datos (`status`, `code`, `provoke`) y no un test: las 11 se recorren dos veces, una comprobando `status`+`code` y otra la parseabilidad del cuerpo, y dos tests sobre la misma tabla no es duplicación sino una afirmación distinta sobre los mismos hechos · cada fila nombra **la petición que la provoca**, no la clase de error: lo que se prueba es que una petición real de un cliente cae en la fila que dice, que es justo lo que T2 (atributos de clase) y T3 (forma del body) dejan sin cubrir · los faults se inyectan en la **base de datos**, no en la app: un `find_error` en el cliente fake hace que el mapeo driver→status sea el de producción, sin un solo `patch` sobre `app/` · el `503` usa `ServerSelectionTimeoutError` (un `PyMongoError`, lo captura el repositorio) y el `500` un `RuntimeError` (no lo captura nadie y lo responde el catch-all): los dos extremos de la cadena de traducción quedan verificados de producción · la fila `500` es la única que pone `rethrow=False`, porque Starlette envía la respuesta y **vuelve a lanzar**, que es lo correcto en un servidor e ilegible en un test · `413` se provoca por la vía de Capa 1 (límite del body) con un `max_text_body_bytes` de 512 B, y no por el `DocumentTooLarge` de Capa 3, que ya tiene su propio test en T8 · los cuatro endpoints protegidos se comprueban anónimos en un test aparte, sin faults, porque es una promesa de T5 y no una fila de §6.2
**Mutación:** `status 409→400` detectada por la fila `CHECKSUM_ALREADY_EXISTS` · `code TEXT_NOT_FOUND→NOT_FOUND` detectada por la fila `TEXT_NOT_FOUND` · quitar `instance` de `build_problem` detectada por las 11 filas del test de parseabilidad — la matriz no es tautológica

### T17: OpenAPI, README y cobertura

> **Superado en parte por T18.** Los cinco componentes de cuerpo ya no se
> transcriben a mano: se derivan de `app/api/models.py`. La premisa de esta
> tarea —"SPEC §2.3 prohíbe Pydantic"- la cambió T18. Sobrevive de este trabajo
> `publish()`, que corrige sobre el documento terminado lo que `openapi_extra`
> no puede, y el `Problem` escrito a mano, cuyo `enum` es una introspección en
> runtime. El resto de la nota se conserva como historia: describe un
> razonamiento correcto bajo §2.3 v2.

- [x] Schemas de request/response a mano con `openapi_extra` — **superado por T18**
- [x] Documentar el header `Authorization` en el esquema
- [x] README: variables, arranque, contrato, `curl` con token por endpoint
- [x] Cobertura >= 85% sin excluir código de producción

**AC:** `/openapi.json` documenta request, response y seguridad de los 4 endpoints · README completo · umbral cumplido limpiamente
**Verify:** `.venv\Scripts\python.exe -m pytest --cov=app --cov-fail-under=85` -> 332 passed, cobertura `app` 100% (597 stmts) · `ruff check .` y `ruff format --check .` limpios · servidor real con `uvicorn app.main:create_app --factory`: `/health` abierto, `/openapi.json` y `/docs` -> 401 sin token, documento correcto con token
**Deps:** T16 · **Files:** `app/api/schemas.py` · `tests/integration/api/test_openapi.py` · `tests/unit/api/test_schemas.py` · `README.md` · **Scope:** Small
**Decisiones:** los schemas se escriben a mano porque SPEC §2.3 prohíbe Pydantic, y la consecuencia es que FastAPI no tiene de dónde leerlos: publica `{}` en cada respuesta · un `openapi_extra` de ruta **fusiona** con `deep_dict_update`, que concatena listas en vez de reemplazarlas (`fastapi/utils.py:111-116`), así que documentar `parameters` a mano duplicaba el `checksum`; en vez de pelearse con la fusión, las correcciones se aplican al documento ya construido · `FastAPI(openapi_extra=...)` acepta el argumento y **nunca lo mezcla** (`fastapi/openapi/utils.py:537-538` sólo aplica `route.openapi_extra`), así que components, el `422` inventado y el `required` del `checksum` se corrigen en `publish()`, sobre el documento final · el `checksum` se declara `str | None = None` en la firma para poder responder `400 VALIDATION_ERROR` en vez del `422` de FastAPI (SPEC §2.3); esa firma obliga a documentarlo como opcional, y `required: true` es la corrección de ese malentendido · el `enum` de `code` se deriva de `ServiceError.__subclasses__()` y un test lo compara con `ALL_ERROR_CLASSES`: el documento no puede separarse de `app/errors.py` sin que salte un test · también se borran `HTTPValidationError` y `ValidationError`, que ya no referencia nadie y cuyo nombre choca con nuestro propio `VALIDATION_ERROR` · la tabla `OPERATIONS` del test es la única fuente de verdad de qué estados documenta cada operación, y el test compara el conjunto **exacto**: un fallo que falta es un defecto tanto como uno inventado · `/docs` y `/openapi.json` exigen token como todo lo demás salvo las sondas (SPEC §3.1), así que el test los lee con credenciales, como lo haría un generador de clientes
**Mutación:** quitar `_require_the_checksum` -> 3 tests de `checksum` en rojo · quitar `"security": SECURITY` -> los 4 verbos protegidos en rojo · quitar `_drop_pydantic_validation` -> 4 tests en rojo, dos de ellos el nuevo de estados exactos en GET/PUT/DELETE (los verbos con `checksum`, que son los que disparan el `422` de FastAPI) · quitar el `503` de `/readyz` -> 2 tests en rojo: el gap que la primera redacción del test tenía, porque sólo comprobaba la forma de los fallos listados y nunca el conjunto

### T18: Pydantic en la frontera
**Status:** done
- [x] `pydantic>=2.13.5` como dependencia directa (`uv.lock` sin cambios de versión)
- [x] `app/api/models.py`: `CreateTextBody`, `UpdateTextBody`, `TextOut`,
      `AcknowledgementOut`, `ProbeOut` + `schema_of()`
- [x] `checked()` en `validators/common.py`: traduce el `ValidationError` de
      Pydantic al `ValidationError` nuestro; fuera `require_mapping`
- [x] `create_text.py` (42 → 32) y `update_text.py` (57 → 63 con `_mapping`)
      validan contra los modelos
- [x] `schemas.py` deriva los 5 componentes; `_PROBLEM` sigue a mano
- [x] SPEC §2.3 reescrita, §2.4 y §7 actualizados, aviso de versión a v3

**AC:** Los 5 componentes se derivan de los modelos · ningún componente lleva `title` · `required` exacto por componente · `minLength: 1` en `text`/`checksum` y `format: date-time` en las fechas · el `detail` nombra el campo · un body no-objeto da `"invalid body"` · `text`/`checksum` en `PUT` → `IMMUTABLE_FIELD` antes que validar tipos · `pydantic` ausente de `services`/`use_cases`/`repositories`/`config.py`
**Verify:** `.venv\Scripts\python.exe -m pytest --cov=app --cov-fail-under=85` -> 382 passed, cobertura `app` 100% (634 stmts) · `ruff check .` y `ruff format --check .` limpios · grep de `^\s*(from|import)\s+pydantic` → sólo `app/api/models.py` y `app/api/validators/common.py`
**Deps:** T17 (la premisa que cambia es SPEC §2.3) · **Files:** `app/api/models.py`, `app/api/validators/common.py`, `app/api/validators/create_text.py`, `app/api/validators/update_text.py`, `app/api/schemas.py`, `pyproject.toml` · `tests/unit/api/test_models.py`, `tests/unit/api/validators/test_common.py`, `tests/integration/api/test_openapi.py` · **Scope:** Medium · **Plan:** [`t18-pydantic.md`](./t18-pydantic.md)
**Decisiones:** el alcance lo fijó el humano como **A** (validación de entrada + OpenAPI); `config.py`, `ports.py`, `services` y `repositories` no se tocan · los tres modelos de respuesta **no validan nada** y aun así se declaran: existen para que el documento salga de una fuente y no de una transcripción, que es la parte del diseño que más derivaba · `_PROBLEM` **no** se modela porque su `enum` se deriva en runtime de `ServiceError.__subclasses__()`, cosa que un `Literal` estático no puede expresar · el `detail` **interpola `location[0]`** en vez de mirar una tabla de campos: sin tabla no hay `KeyError` posible en el manejador de errores, y la tabla habría sido un segundo sitio donde olvidar un nombre · `require_str` se queda para el query param, y `response_model` de FastAPI no, porque Pydantic serializa `datetime` con microsegundos y rompería el RFC 3339 con milisegundos de SPEC §5.2
**Mutación:** quitar la guarda de `loc == ()` en `_detail` -> 2 tests de `invalid body` en rojo · cambiar `location[0]` por `location[-1]` -> cae el test del `loc` anidado (`{"metadata": {1: "x"}}`), que es el que distingue `metadata` de `invalid 1` · quitar `_untitled` -> los tests de `title` en rojo

### Checkpoint: Complete
- [x] `uv run pytest --cov=app --cov-fail-under=85` pasa — 382 passed, cobertura 100%
- [x] `uv run ruff check .` y `uv run ruff format .` limpios
- [x] Las 11 filas de la matriz verificadas por test
- [x] Checklist de contrato SPEC §8 en verde
- [x] Criterios de éxito del SPEC cumplidos
- [ ] **Listo para revisión final del humano**

---

## Decisiones cerradas (v2 → v3)

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
| Q9 | Pydantic en el contrato (v2 lo prohibía) | **Sí, sólo en `app/api/`**; SPEC §2.3 reescrita | T18 |

---

## Pendiente de tu integración (orquestador Go)

Este servicio **cambia** el contrato. Antes de conectarlo:

- [ ] `?checksum=` con `url.QueryEscape` en vez de path param (`client.go:42,47,52`)
- [ ] `omitempty` en `UpdateTextRequest` (`dto/text.go`)
- [ ] `PERSISTENCE_API_TOKEN` en la configuración
- [ ] `Authorization: Bearer <token>` en todas las requests (`httpclient/client.go`)
- [ ] `401` tratado como error de configuración con **fail-fast, sin reintento**
- [ ] Reescribir los tests de `persistence/client_test.go` para las rutas nuevas
