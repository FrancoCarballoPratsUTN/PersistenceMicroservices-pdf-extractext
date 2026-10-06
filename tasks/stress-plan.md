# Implementation Plan: Pruebas de stress con Vegeta y k6

> **Archivo nuevo.** El plan original (`tasks/plan.md`) y su lista
> (`tasks/todo.md`) contienen tareas sin cerrar de otro trabajo (la
> implementación del microservicio) y **no se han tocado**. Este plan vive en
> `stress-plan.md` / `stress-todo.md`.
>
> **Estado:** pendiente de aprobación. No se ha escrito código.
>
> **v2 — sin observabilidad.** A petición del humano: **sin Grafana, sin
> Prometheus, sin dashboard, sin instrumentar `app/`.** Sólo la prueba de
> stress en sí (Vegeta + k6) con sus scripts. `app/` queda intacto.

## Overview

Batería de pruebas de stress para el microservicio de persistencia, alojada en
`tests/stress/` con los scripts en `tests/stress/scripts/`. Dos herramientas,
cero infraestructura:

- **Vegeta** — ataque HTTP a ciegas a un rate constante, con targets
  pre-generados. Reporte de latencia p50/p95/p99, RPS y códigos de estado en
  `tests/stress/out/`.
- **k6** — escenarios con rampas (smoke / load / stress) y **thresholds**
  que hacen salir con código ≠ 0 si se incumplen p95 o tasa de error.

Ambos generan carga contra el servicio local (`uvicorn` + MongoDB, como los
tests de integración) y dejan sus resultados en `out/`. No se toca `app/`:
este plan no añade dependencias ni cambios de producción.

## Architecture Decisions

### Desviaciones registradas durante la ejecución

| # | Desviación | Plan original | Motivo |
|---|---|---|---|
| S1 | La siembra HTTP es la flag `--load`; `--seed` es la semilla RNG | Un solo `--seed` para las dos cosas | La misma palabra para dos funciones distintas confunde la CLI; ahora `--seed 42` reproduce los checksums y `--load` crea los documentos |
| S2 | `tests/stress/` y `tests/stress/scripts/` llevan `__init__.py` | No especificado | El repo versiona `tests/` como paquetes (`pythonpath=["."]`), y así el test importa `tests.stress.scripts.gen_targets` sin trucos de path |
| S3 | Los targets de Vegeta se emiten en **formato JSON** (`vegeta attack -format json`, un target por línea, body en base64) | Targets en el formato HTTP legible (`METHOD URL`, cabeceras, cuerpo tras línea en blanco) | El formato HTTP de vegeta **no admite cuerpos inline**: la línea en blanco cierra la petición tras las cabeceras, el JSON se come como cabecera y vegeta muere con `bad method` (verificado con la v12.13.0; `lib/target.go` de vegeta sólo acepta body vía `@fichero` o `-body` global). El ataque E2E contra el servicio real confirmó el formato nuevo: 100% 2xx |
| S4 | `gen_targets.py` crece la flag `--pre-clean` y `run-vegeta.ps1` la purga por defecto cuando hay `POST` entre los verbos (interruptor `-NoPreClean`) | El ciclo post→get→put→delete era suficiente para no dejar residuos | El ciclo limpia al final, pero **una corrida crasheada deja documentos** y el siguiente POST mide 409 en vez de escritura (observado en E2E); un `--load` previo (siembra para corridas de lectura) produce el mismo efecto. Un `DELETE` por checksum sirve a la vez de purga y sondeo (404 = ausente, no aborta) |
| S5 | El umbral se calcula sobre `vegeta report -type=json` **agregado** (`1 - success`), no sobre filas por petición | Contar filas con `error` o `code >= 400` | El informe JSON de vegeta es un único objeto (`requests`, `success`, `status_codes`, `errors[]`), no una fila por request; `success` es la fracción con código en [200,400) y los errores de transporte (code 0) caen del lado de fallos, que es exactamente la semántica del umbral |

- **Los scripts van en `tests/stress/scripts/`** (el repo usa `tests/` en
  plural; ahí vive todo lo que corre contra el servicio).

- **No se sobrescribe `plan.md`/`todo.md`.** Tienen checkboxes sin cerrar de
  la fase de implementación; borrarlos destruiría estado de otra sesión.

- **Sin métricas de servicio.** Se descarta la instrumentación con
  `prometheus-fastapi-instrumentator`, Prometheus y el dashboard de Grafana
  (decisión v2 del humano). Lo que mide el éxito es lo que reportan las
  propias herramientas: exit codes, thresholds de k6 y el reporte de latencia
  de Vegeta. `app/` no se modifica en ningún task.

- **Vegeta no puede dinamizar bodies → targets pre-generados.** Los 4 verbos
  exigen checksum únicos (un repetido da `409` y contamina la medición), y
  Vegeta sólo lee un fichero de targets. El script `gen_targets.py` genera N
  checksums únicos, siembra los documentos vía `POST` y escribe los ficheros
  de targets para GET/PUT/DELETE. k6, en cambio, genera payloads únicos por
  iteración en JS.

- **k6 lleva thresholds en el propio script**, de modo que un run que no
  cumple p95/error-rate sale con código ≠ 0 y el orquestador lo detecta.

- **Resultados en `tests/stress/out/`**, gitignored (binarios de Vegeta, JSON
  de k6). Los targets generados también se ignoran: se regeneran.

- **PowerShell (.ps1)** como capa de orquestación: el host es Windows y
  `pwsh` está garantizado. `vegeta` y `k6` se asumen en el PATH; la
  instalación queda documentada en el README de stress.

## Dependency Graph

```
T1 gen_targets.py (seed + targets)  ◄── unittest propio
        │
        ├──► T2 run-vegeta.ps1   ┐
        └──► T3 scripts k6       ┘  (paralelos entre sí)
                    │
                    ▼
        T4 orquestador run-stress.ps1 + README + .gitignore
```

## Task List

### Phase 1: Generadores de carga

- [x] **T1: `gen_targets.py`** — genera checksums únicos, siembra docs y
      escribe los targets de Vegeta; test unitario del generador.

### Phase 2: Ataques

- [x] **T2: Scripts de Vegeta** — `run-vegeta.ps1` con perfiles
      smoke/load/stress y umbral de errores.
- [x] **T3: Scripts de k6** — `smoke.js`, `load.js`, `stress.js` con
      thresholds y payloads únicos. *(paralelo con T2)*

### Checkpoint: Carga reproducible
- [x] `gen_targets.py` produce N líneas únicas verificable por test
- [x] Vegeta smoke corre contra el servicio y deja resultados en `out/`
- [x] `k6 run smoke.js` sale con código 0 y thresholds en verde
- [x] **Revisión humana antes de continuar** (aprobada: seguir con T4)

### Phase 3: Orquestación y cierre

- [x] **T4: Orquestador + README** — `run-stress.ps1` (checks → seed →
      vegeta → k6 → resumen), README de uso e instalación, `.gitignore`
      para `out/` y targets.

### Checkpoint: Complete
- [x] Un solo comando ejecuta el pipeline completo de principio a fin
- [x] `uv run pytest --cov=app --cov-fail-under=85` pasa
- [x] `uv run ruff check .` y `uv run ruff format .` limpios
- [x] README documenta instalación de vegeta/k6 y cómo leer los resultados
- [ ] **Listo para revisión final del humano**

## Task Detail

### T1: `gen_targets.py` — seed y targets de Vegeta

**Description:** Script Python (corre con `uv run`, usa `httpx` que ya está en
dev-deps) que resuelve el problema de que Vegeta no puede generar bodies
únicos: (1) genera N checksums únicos `sha256`, (2) opcionalmente siembra los
documentos con `POST /texts` reales (`--seed`), (3) escribe los ficheros de
targets de Vegeta — `post.txt` con bodies únicos, y `get.txt` / `put.txt` /
`delete.txt` con el header `Authorization` leído de `SERVICE_API_TOKEN`. CLI
con `--count`, `--base-url`, `--seed` (reproducibilidad) y `--out-dir`.

**Acceptance criteria:**
- [x] `uv run python tests/stress/scripts/gen_targets.py --count 1000`
      produce 1000 líneas únicas en `post.txt` (test lo afirma)
- [x] El generador es determinista con `--seed` fijo: dos corridas dan
      exactamente el mismo fichero
- [x] `--seed` contra un servicio real crea 1000 docs y `GET` posterior de
      una muestra devuelve `200`
- [x] Los ficheros de GET/PUT/DELETE llevan
      `Authorization: Bearer <token>` tomado del entorno, nunca hardcodeado
- [x] El script pasa `ruff check` y `ruff format --check`

**Verification:**
- [x] `uv run pytest tests/stress/test_gen_targets.py`
- [x] Manual: corrida con `--seed` contra el servicio local y `curl` de
      comprobación sobre un checksum generado

**Dependencies:** None
**Files likely touched:**
- `tests/stress/scripts/gen_targets.py`
- `tests/stress/test_gen_targets.py`
**Estimated scope:** Small

---

### T2: Scripts de Vegeta

**Description:** `run-vegeta.ps1` que orquesta el ataque: valida que `vegeta`
está en el PATH y que el servicio responde (`/health`), llama a
`gen_targets.py` si no existen targets, y lanza `vegeta attack` con un perfil
(`smoke` 10 s @ 10 rps, `load` 30 s @ 100 rps, `stress` 60 s @ 300 rps),
guarda los resultados binarios y el reporte (`vegeta report -type=text` y
`-type=json`) en `tests/stress/out/`. Devuelve código ≠ 0 si el porcentaje de
errores supera el umbral del perfil (parseando el reporte JSON).

**Acceptance criteria:**
- [x] `./run-vegeta.ps1 -Profile smoke` contra el servicio local termina con
      `exit 0` y deja `out/vegeta-smoke.results` + `out/vegeta-smoke.json`
- [x] El reporte incluye latencia p50/p95/p99, RPS y desglose por código de
      estado
- [x] Sin `vegeta` en el PATH o sin servicio vivo, el script falla **antes**
      de atacar con un mensaje claro (fail-fast)
- [x] Umbral: un run contra un servicio apagado (o con target imposible)
      sale con código ≠ 0

**Verification:**
- [x] Manual: `./tests/stress/scripts/run-vegeta.ps1 -Profile smoke`
- [x] Manual: repetir con el servicio apagado ⇒ exit ≠ 0 y mensaje claro

**Dependencies:** T1
**Files likely touched:**
- `tests/stress/scripts/run-vegeta.ps1`
**Estimated scope:** Small

---

### T3: Scripts de k6

**Description:** Tres escenarios k6 en `tests/stress/scripts/k6/` que comparten
un módulo `utils.js` (baseUrl, token desde `__ENV.SERVICE_API_TOKEN`,
generación de checksum único por iteración con `crypto`):
`smoke.js` (< 1 min, VUs bajos, thresholds estrictos), `load.js` (rampa a
100 VUs modelando uso esperado) y `stress.js` (rampa a 500 VUs buscando el
punto de quiebre). Cada uno cubre el ciclo completo POST → GET → PUT → DELETE
con checksums únicos, y declara thresholds (`http_req_duration{p:n}<…`,
`http_req_failed rate < …`) que hacen que k6 salga con código ≠ 0 si se
incumplen. Salida adicional a JSON en `out/`.

**Acceptance criteria:**
- [x] `k6 run smoke.js --env SERVICE_API_TOKEN=…` sale con `code 0` contra el
      servicio local y cumple sus thresholds
- [x] Cada iteración usa un checksum único: ningún `409` aparece en el smoke
- [x] `stress.js` declara VUs ≥ 500 y thresholds que, si se incumplen,
      provocan exit ≠ 0
- [x] El módulo compartido no duplica lógica entre los 3 escenarios

**Verification:**
- [x] Manual: `k6 run tests/stress/scripts/k6/smoke.js` ⇒ exit 0
- [x] Manual: `--out json=out/k6-smoke.json` escribe resultados parseables
- [x] Manual: durante el run, `/health` sigue respondiendo (el servicio
      sobrevive al ataque)

**Dependencies:** T1
**Files likely touched:**
- `tests/stress/scripts/k6/utils.js`
- `tests/stress/scripts/k6/smoke.js`
- `tests/stress/scripts/k6/load.js`
- `tests/stress/scripts/k6/stress.js`
**Estimated scope:** Medium

---

### T4: Orquestador + README + .gitignore

**Description:** `run-stress.ps1` en la raíz de `tests/stress/` encadena el
pipeline completo: comprobación de que el servicio local responde y de que
`docker`/Mongo están disponibles si hace falta → `gen_targets.py` → Vegeta
(perfil elegido) → k6 (escenario elegido) → resumen final con las rutas de
los resultados en `out/`. `README.md` documenta instalación (`vegeta`, `k6`),
variables (`SERVICE_API_TOKEN`), cómo levantar el servicio y cómo leer los
reportes. `.gitignore` gana `tests/stress/out/` y los targets generados.

**Acceptance criteria:**
- [x] `./tests/stress/run-stress.ps1 -Profile smoke -Scenario smoke` ejecuta
      el pipeline completo sin pasos manuales intermedios
- [x] El README permite a alguien nuevo correr un smoke leyéndolo solo
- [x] `out/` y los targets generados no aparecen en `git status`
- [x] El script hace fail-fast con mensaje claro si falta vegeta, k6 o el
      servicio

**Verification:**
- [x] Manual: pipeline completo desde una terminal limpia
- [x] `uv run pytest --cov=app --cov-fail-under=85`
- [x] `uv run ruff check .` · `uv run ruff format .`
- [x] `git status` sin artefactos de stress

**Dependencies:** T2, T3
**Files likely touched:**
- `tests/stress/run-stress.ps1`
- `tests/stress/README.md`
- `.gitignore`
**Estimated scope:** Medium

## Checkpoint Summary

| Punto | Tareas | Se verifica |
|---|---|---|
| Carga reproducible | T1–T3 | Vegeta y k6 corren; targets únicos; thresholds funcionan |
| Complete | T4 | Pipeline de un solo comando; docs; lint |

## Risks and Mitigations

| Riesgo | Impacto | Mitigación | Tarea |
|---|---|---|---|
| Vegeta repite targets → tsunami de `409` en POST | Medio | Targets con checksums únicos generados = rate × duration con margen; los `409` se contabilizan aparte en el reporte | T1, T2 |
| Servicio local caído durante el run | Medio | Fail-fast en todos los scripts (`/health` antes de atacar) | T2–T4 |
| Mongo no disponible para escrituras | Medio | El orquestador comprueba `localhost:27017` antes de sembrar; README documenta cómo levantarlo | T1, T4 |
| k6 o vegeta ausentes del PATH | Bajo | Fail-fast con mensaje de instalación en README | T2–T4 |
| Resultados grandes ensuciando el repo | Bajo | `out/` y targets gitignored | T4 |
| Sin métricas de servicio, diagnóstico posterior limitado | Bajo | Asumido por decisión v2; el reporte de Vegeta y el JSON de k6 conservan latencia/códigos de cada run | — |

## Parallelization Opportunities

- **Paralelo:** T2 (Vegeta) y T3 (k6) tras T1 — no comparten ficheros.
- **Secuencial:** T1 primero (sin targets no hay ataque de Vegeta).

## Open Questions

- **Cerrado (v2):** sin Grafana, sin Prometheus, sin dashboard, sin tocar
  `app/`.
- **Asumido:** perfiles y umbrales (smoke 10 rps, load 100 rps, stress
  300 rps; p95 < 500 ms, error < 1 %) son puntos de partida revisables.
- **Cerrado (decisión humana):** los documentos de stress **se dejan** en la
  BD — no hay flag `--cleanup` ni purga al final del run. El ciclo de cada
  ataque (`POST → … → DELETE`) se sigue borrando a sí mismo y el
  `--pre-clean` sigue corriendo *antes* del ataque cuando hay `POST` entre
  los verbos, porque eso es validez de la medición, no limpieza.
