# Pruebas de stress — Vegeta + k6

Ataques de carga contra el microservicio de persistencia para medir latencia,
tasa de errores y umbral de aguante. Dos herramientas, sin dashboards ni
métricas de infraestructura: todo vive en ficheros de `out/` y en los exit
codes.

| Herramienta | Qué mide | Cuándo |
|---|---|---|
| **Vegeta** | Ataque HTTP a tasa fija (rps) contra los cuatro verbos, con umbral de errores por perfil | Carga sostenida y contrato de la API |
| **k6** | Ciclo CRUD completo por iteración con VUs crecientes, thresholds declarados | Comportamiento bajo concurrencia creciente |

## Requisitos

- **Python 3.14 + uv** — el propio repo (ver `README.md` de la raíz).
- **Vegeta v12** y **k6 v2** en el `PATH` (ver instalación abajo).
- **MongoDB en `localhost:27017`** y el **servicio local levantado**.

### Instalar Vegeta

Opción A (Go): `go install github.com/tsenart/vegeta/v12@latest`

Opción B (binario): descargar `vegeta_*_windows_amd64.zip` de
<https://github.com/tsenart/vegeta/releases>, descomprimir y dejar
`vegeta.exe` en una carpeta del `PATH` (p. ej. `~/.local/bin`).

Comprobar: `vegeta -version` → v12.x

### Instalar k6

Opción A: `winget install k6`

Opción B (binario): descargar `k6-vX.Y.Z-windows-amd64.zip` de
<https://github.com/grafana/k6/releases>, descomprimir y dejar `k6.exe`
en el `PATH`.

Comprobar: `k6 version` → v2.x

### MongoDB y servicio

```powershell
# MongoDB (si el contenedor ya existe, basta con docker start mongo-smoke)
docker run -d --name mongo-smoke -p 27017:27017 mongo:7.0

# Servicio (en otra terminal, desde la raíz del repo)
$env:SERVICE_API_TOKEN = "tu-token-largo"
uv run uvicorn app.main:create_app --factory --port 8082
```

Comprobar que todo responde: `curl http://localhost:8082/readyz` debe dar
`{"status":"ok","mongo":"ok"}`. Sin `SERVICE_API_TOKEN` no arranca.

## Variables de entorno

| Variable | Obligatoria | Efecto |
|---|---|---|
| `SERVICE_API_TOKEN` | sí | Bearer que exige la API; los scripts fallan sin ella **antes** de atacar |
| `BASE_URL` | no | k6 la lee (`--env BASE_URL=...`); por defecto `http://localhost:8082`. Los scripts de PowerShell exigen `-BaseUrl` |

## Cómo correr

### Pipeline completo (lo normal)

```powershell
./tests/stress/run-stress.ps1 -Profile smoke -Scenario smoke
```

Preflight (vegeta, k6, token, `/readyz`) → Vegeta con umbral → k6 con
thresholds → resumen de artefactos en `out/`. Sale con `0` si todo pasó y
con `1` en cuanto algo falle (con el mensaje de la etapa culpable).

### Por partes

```powershell
# Sólo Vegeta
./tests/stress/scripts/run-vegeta.ps1 -Profile load          # o -Verbs get,put

# Sólo k6
k6 run --env SERVICE_API_TOKEN=$env:SERVICE_API_TOKEN `
       --out json=tests/stress/out/k6-smoke.json `
       tests/stress/scripts/k6/smoke.js

# Generar targets / preparar la base a mano
uv run python tests/stress/scripts/gen_targets.py --count 1000 --seed 42 --pre-clean
```

### Perfiles y escenarios

| Nombre | Vegeta (rps × s → umbral de errores) | k6 (VUs × duración → thresholds) |
|---|---|---|
| `smoke` | 10 × 10 s → ≤ 1 % | 1 VU × 30 s → `p95<500ms`, `failed<1%`, `checks>99%` |
| `load` | 100 × 30 s → ≤ 5 % | rampa a 100 VUs (30s/1m/30s) → mismos que smoke |
| `stress` | 300 × 60 s → ≤ 10 % | rampa a 500 VUs (1m/2m/30s) → `p95<1s`, `failed<10%`, `checks>90%` |

Los números son puntos de partida, no promesas: sube el umbral sólo si el
perfil lo justifica.

## Qué deja cada corrida en `out/`

| Fichero | Contenido |
|---|---|
| `vegeta-<perfil>-<verbo>.results` | Resultados binarios (gob) del ataque |
| `vegeta-<perfil>-<verbo>.report.txt` | Informe humano: latencias p50/p95/p99, RPS, códigos |
| `vegeta-<perfil>-<verbo>.report.json` | Objeto agregado: `requests`, `success`, `status_codes`, `errors[]` (de aquí sale el % de errores) |
| `k6-<escenario>.json` | NDJSON de k6: una línea JSON por evento/métrica |

Todo en `tests/stress/out/` (ignorado por git), igual que los targets
generados en `tests/stress/targets/`. Para leer un informe Vegeta: mira
`Success [ratio]` y `Status Codes`; para k6, la sección `█ THRESHOLDS` con
`✓`/`✗` y el código de salida.

## Decisiones que conviene saber

- **El ciclo de ataque es `POST → GET → PUT → DELETE`** (los cuatro verbos,
  en ese orden): POST crea, DELETE borra, y una corrida completa no deja
  residuos.
- **Los documentos se dejan en la base** (decisión de plan, sin flag
  `--cleanup`): lo que los ciclos no borran (p. ej. de una corrida
  interrumpida) queda ahí.
- **El pre-limpieado sí es automático**: cuando hay `POST` entre los verbos,
  `gen_targets.py --pre-clean` borra los checksums objetivo *antes* del
  ataque para que el POST mida escritura de verdad y no `409`. Interrumpe con
  `-NoPreClean` en `run-vegeta.ps1` si necesitas el estado previo intacto.
- **Los targets de Vegeta son JSON** (`-format json`): el formato HTTP
  legible de Vegeta no admite cuerpos inline, así que `gen_targets.py` emite
  un target por línea con el body en base64.

## Problemas frecuentes

| Síntoma | Causa y arreglo |
|---|---|
| `FAIL: 'vegeta' no esta en el PATH` / `'k6'` | La carpeta del binario no está en `PATH`; rehacer la instalación |
| `FAIL: SERVICE_API_TOKEN no esta definida` | `$env:SERVICE_API_TOKEN = "..."` antes de lanzar |
| `FAIL: no responde .../readyz` | Servicio o MongoDB caídos; ver arriba |
| `post: ... 409` en el informe de Vegeta | Residuos de una corrida previa; se purga solo con `--pre-clean` (activado por defecto) |
| `k6 ... script exception: SERVICE_API_TOKEN` | k6 no la recibió; pásala con `--env SERVICE_API_TOKEN=...` |
| `umbral superado` / thresholds `✗` | El servicio no aguantó el perfil: mira el `report.txt`/salida de k6, es un **resultado**, no un fallo de instalación |
