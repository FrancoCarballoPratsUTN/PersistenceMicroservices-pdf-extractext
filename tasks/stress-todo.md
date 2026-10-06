# Tasks — Pruebas de stress (Vegeta + k6)

> Plan: [`stress-plan.md`](./stress-plan.md)
>
> **Archivo nuevo.** `plan.md` / `todo.md` siguen intactos: pertenecen a la
> implementación del microservicio y tienen tareas sin cerrar.
>
> **v2 — sin observabilidad:** sin Grafana, sin Prometheus, sin dashboard,
> sin instrumentar `app/`. Sólo Vegeta + k6.
>
> **Estado: T1–T4 cerradas.** Falta sólo la revisión final humana
> (Checkpoint: Complete).

---

## Phase 1: Generadores de carga

### T1: `gen_targets.py` — seed y targets
**Status:** done ✅
- [x] Genera N checksums únicos (sha256) con `--count`, determinista con `--seed`
- [x] Siembra docs reales vía `POST /texts` con la flag `--load` (httpx); `409` cuenta como *ya existía*
- [x] Escribe targets de Vegeta: `post.txt` (bodies únicos) y `get/put/delete.txt` con `Authorization: Bearer`
- [x] Test unitario: unicidad, determinismo, formato exacto de los targets, guardas del CLI

**AC:** `--count 1000` ⇒ 1000 líneas únicas (verificadas por test) · mismo `--seed` ⇒ mismo fichero · token ausente ⇒ exit 2 sin escribir nada · `ruff check` limpio
**Verify:** `uv run pytest tests/stress` → **17 passed** · suite completa `399 passed`, cobertura `app` 100% con `--cov-fail-under=85` · `ruff check` y `ruff format --check` limpios
**Deps:** — · **Files:** `tests/stress/scripts/gen_targets.py`, `tests/stress/test_gen_targets.py`, + `__init__.py` de paquete · **Scope:** Small
**Decisiones:** la siembra HTTP es `--load` y no `--seed` (el plan usaba la misma palabra para dos cosas; `--seed` quedó como semilla RNG) · una sola fórmula `sha256("<semilla>:<índice>")` da unicidad **garantizada** por construcción, incluso sin semilla · `write_targets` devuelve `dict[verbo, Path]` para que el orquestador sepa qué escribió sin re-listar el disco · el formato de los targets es el **JSON de Vegeta** (`-format json`, un target por línea, body en base64) y no el HTTP legible: ver derivación S3 en `stress-plan.md` (el HTTP se traga el JSON como cabecera y muere con "bad method")

---

## Phase 2: Ataques

### T2: Scripts de Vegeta
**Status:** done ✅
- [x] `run-vegeta.ps1` con perfiles `smoke` (10 rps/10 s), `load` (100 rps/30 s), `stress` (300 rps/60 s)
- [x] Fail-fast: valida `vegeta` en PATH, `SERVICE_API_TOKEN` y `/health` antes de atacar
- [x] Resultados binarios (gob vía `-output`) + reporte text/json en `tests/stress/out/`
- [x] Exit ≠ 0 si el % de errores supera el umbral del perfil

**AC:** smoke ⇒ exit 0 con reporte de p50/p95/p99, RPS y códigos · servicio apagado ⇒ falla antes de atacar con mensaje claro · umbral roto ⇒ exit ≠ 0
**Verify:** manual E2E con servicio real + Mongo local: `run-vegeta.ps1 -Profile smoke` → exit 0 (4×100 peticiones, 100% 2xx, pre-clean incluido) · `-BaseUrl http://localhost:9999` → exit 1 antes de atacar · sin `SERVICE_API_TOKEN` → exit 1 · sin `vegeta` en PATH → exit 1 · umbral roto (corrida con 409) → exit 1 · `parse_targets`/tests en verde (17)
**Deps:** T1 · **Files:** `tests/stress/scripts/run-vegeta.ps1` · **Scope:** Small
**Decisiones:** targets en formato JSON de Vegeta (`-format json`) porque el HTTP legible no admite bodies inline — derivación S3 · `vegeta attack -output` en lugar de `cmd /c >` (más simple, binario seguro) · el informe `-type=json` es **un objeto agregado** (`requests`, `success`, `status_codes`), no filas: el umbral se calcula como `1 - success` (éxito = código en [200,400); los errores de transporte cuentan como fallo) · pre-limpieado con `--pre-clean` (S4): un `DELETE` por checksum purga y sondea a la vez (404 = ausente), porque una corrida crasheada o un `--load` previo convertiría todos los POST en 409

### T3: Scripts de k6 *(paralelo con T2)*
**Status:** done ✅
- [x] `utils.js` compartido: baseUrl, token desde `__ENV`, checksum único por iteración
- [x] `smoke.js` (< 1 min, thresholds estrictos), `load.js` (rampa → 100 VUs), `stress.js` (rampa → 500 VUs)
- [x] Ciclo completo POST → GET → PUT → DELETE por iteración, sin `409`
- [x] Thresholds (`http_req_duration p95`, `http_req_failed < 1%`) que provocan exit ≠ 0

**AC:** `k6 run smoke.js` ⇒ exit 0 · ningún `409` en smoke · stress con ≥ 500 VUs · salida `--out json` parseable · sin lógica duplicada entre escenarios
**Verify:** manual E2E: `k6 run --env SERVICE_API_TOKEN=… --out json=tests/stress/out/k6-smoke.json smoke.js` → **exit 0**, 564 iteraciones / 2256 checks 100%, `http_req_failed` 0.00%, p95 19.9 ms · `/health` devolvió 200 en los 5 sondeos durante el run · NDJSON de 9 MB parseado línea a línea con `json.loads` · sin token ⇒ exit 107 con mensaje claro (fail-fast en la carga del módulo) · `k6 inspect` de los tres escenarios parsea (smoke 1 VU/30 s, load →100, stress →500 con `checks`+`http_req_duration`+`http_req_failed` declarados)
**Deps:** T1 · **Files:** `tests/stress/scripts/k6/utils.js`, `smoke.js`, `load.js`, `stress.js` · **Scope:** Medium
**Decisiones:** checksum único = `sha256(randomBytes(16), "hex")` del módulo `k6/crypto` (sin dependencias externas; `k6/execution` probado y disponible si hiciera falta) · el guardas de token está en el **scope del módulo** de `utils.js`: falla antes de que arranque ningún VU (exit ≠ 0) y también en `k6 inspect` · el ciclo CRUD entero vive en `utils.js` y cada escenario sólo declara `options` + `export default crudCycle` (cero lógica duplicada) · `k6 v2.3.0` no tiene `k6/exec` (renombrado a `k6/execution`) y `sha256` exige la codificación de salida explícita

### Checkpoint: Carga reproducible
- [x] `gen_targets.py` con test en verde
- [x] Vegeta smoke deja resultados en `out/`
- [x] `k6 run smoke.js` exit 0 con thresholds en verde
- [x] **Revisión humana antes de continuar** (aprobada: seguir con T4)

---

## Phase 3: Orquestación y cierre

### T4: Orquestador + README + .gitignore
**Status:** done ✅
- [x] `run-stress.ps1`: checks (servicio/Mongo) → gen_targets → vegeta → k6 → resumen con rutas de `out/`
- [x] README: instalación (vegeta/k6), variables (`SERVICE_API_TOKEN`), cómo levantar el servicio y leer reportes
- [x] `.gitignore`: `tests/stress/out/` y targets generados
- [x] Fail-fast con mensajes claros si falta vegeta, k6 o el servicio

**AC:** `./tests/stress/run-stress.ps1 -Profile smoke -Scenario smoke` corre el pipeline completo sin pasos manuales · README suficiente para un nuevo · `git status` sin artefactos de stress
**Verify:** manual E2E: pipeline completo → **exit 0** (preflight → vegeta 4×100 en umbral → k6 1012 iteraciones/4048 checks 100% → resumen con 13 artefactos) · tres fail-fast probados: PATH sin herramientas ⇒ exit 1, sin `SERVICE_API_TOKEN` ⇒ exit 1, `/readyz` caído ⇒ exit 1, cada uno con mensaje de arreglo · `git check-ignore` marca `out/` (`.gitignore:223`) y `targets/` (`:224`) y `git add --dry-run tests/stress` sólo lista fuentes · `pytest` **399 passed / 100%** · `ruff check` y `ruff format --check` limpios
**Deps:** T2, T3 · **Files:** `tests/stress/run-stress.ps1`, `tests/stress/README.md`, `.gitignore` · **Scope:** Medium
**Decisiones:** el orquestador **delega** en `run-vegeta.ps1` (que ya hace gen_targets + pre-clean + ataque + umbral) en vez de reimplementar la cadena; la etapa k6 recibe `SERVICE_API_TOKEN` y `BASE_URL` por `--env` · preflight con **`/readyz`** en vez de comprobar docker: devuelve servicio *y* Mongo en una sola llamada (`{"status":"ok","mongo":"ok"}`) · fail-fast total: la primera etapa fallida detiene el pipeline (un umbral de vegeta roto ya invalida la corrida, no hace falta gastar los 30 s de k6) · verificación como en T2/T3: E2E manual sobre scripts PS (el stack de test del repo es pytest y no se le añade Pester); la lógica con tests vive en `gen_targets.py`

### Checkpoint: Complete
- [x] Un solo comando ejecuta el pipeline de principio a fin
- [x] `pytest --cov-fail-under=85` pasa
- [x] `ruff check .` y `ruff format .` limpios
- [x] README completo
- [ ] **Listo para revisión final del humano**

---

## Nota sobre decisiones abiertas

Dos puntos quedaron **asumidos** en el plan (ver `stress-plan.md`
§ Open Questions); si alguno no cuadra, avisar antes de implementar:

1. Perfiles/umbrales (smoke 10 rps, load 100 rps, stress 300 rps; p95 < 500 ms,
   error < 1 %) son puntos de partida.
2. ~~k6 siembra y consume documentos en la BD: pendiente decidir si el run
   deja los documentos de stress o los limpia con un flag `--cleanup`.~~
   **Resuelto (decisión humana): se dejan** — sin `--cleanup` ni purga al
   final; el `--pre-clean` previo al ataque se mantiene porque es validez de
   la medición, no limpieza.
