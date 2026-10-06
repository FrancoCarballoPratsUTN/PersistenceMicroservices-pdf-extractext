<#
.SYNOPSIS
    Ataque de stress con Vegeta contra el microservicio de persistencia.

.DESCRIPTION
    Orquesta el ciclo completo de un ataque Vegeta:

      1. Preflight   - vegeta en el PATH, SERVICE_API_TOKEN, /health vivo.
      2. Targets     - purga los documentos de corridas previas (--pre-clean,
                       para que el POST no mida 409) y genera los cuatro
                       ficheros con gen_targets.py (mismo --seed => mismos
                       checksums => el ciclo es determinista).
      3. Ataque      - un ``vegeta attack`` por verbo, en el orden dado.
      4. Umbral      - comparte el porcentaje de respuestas >= 400 o con error
                       de transporte contra el umbral del perfil; si lo supera,
                       el script sale con codigo 1.

    El orden por defecto (post, get, put, delete) es el ciclo de vida de los
    documentos: POST los crea, GET los lee, PUT los actualiza y DELETE los
    borra, de modo que una corrida completa no deja residuos en la base y la
    siguiente vuelve a empezar de cero.

.PARAMETER Profile
    smoke  -   10 rps / 10 s / umbral  1%
    load   -  100 rps / 30 s / umbral  5%
    stress -  300 rps / 60 s / umbral 10%

.PARAMETER NoPreClean
    Omite la purga previa de los documentos objetivo. Por defecto la purga
    solo se pide cuando hay POST entre los verbos (si no, borraria lo que
    GET/PUT deben leer); este interruptor la desactiva tambien ahi.

.EXAMPLE
    ./run-vegeta.ps1 -Profile smoke

.EXAMPLE
    ./run-vegeta.ps1 -Profile stress -Verbs post,get
#>
#Requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet("smoke", "load", "stress")]
    [string]$Profile = "smoke",

    [ValidateSet("post", "get", "put", "delete")]
    [string[]]$Verbs = @("post", "get", "put", "delete"),

    [string]$BaseUrl = "http://localhost:8082",

    # 0 => rate x duracion x 1.1: vegeta recicla los targets cuando se acaban,
    # y un target reciclado en POST es un 409 que infla el conteo de errores.
    [int]$Count = 0,

    [string]$TargetsDir = (Join-Path $PSScriptRoot ".." "targets"),
    [string]$OutDir = (Join-Path $PSScriptRoot ".." "out"),

    [switch]$ForceTargets,

    # Omite la siembra (--load) aunque el lazo la pidiera.
    [switch]$NoSeed,

    # Omite la purga de documentos de corridas previas (solo aplica con POST).
    [switch]$NoPreClean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Profiles = @{
    smoke  = @{ Rate = 10;   Seconds = 10; ThresholdPct = 1.0 }
    load   = @{ Rate = 100;  Seconds = 30; ThresholdPct = 5.0 }
    stress = @{ Rate = 300;  Seconds = 60; ThresholdPct = 10.0 }
}

function Fail([string]$Message) {
    Write-Host "FAIL: $Message" -ForegroundColor Red
    exit 1
}

# --- 1. Preflight -----------------------------------------------------------

$spec = $Profiles[$Profile]

if (-not (Get-Command vegeta -ErrorAction SilentlyContinue)) {
    Fail ("vegeta no esta en el PATH. Instalar con: " +
          "'go install github.com/tsenart/vegeta/v12@latest' o descargar el binario " +
          "desde https://github.com/tsenart/vegeta/releases")
}

$token = [System.Environment]::GetEnvironmentVariable("SERVICE_API_TOKEN")
if ([string]::IsNullOrWhiteSpace($token)) {
    Fail ("SERVICE_API_TOKEN no esta definida; el servicio rechaza cualquier " +
          "peticion sin ella. Exporta la variable (ver .env.example) antes de atacar.")
}

try {
    Invoke-WebRequest -Uri "$BaseUrl/health" -TimeoutSec 5 | Out-Null
} catch {
    Fail ("el servicio no responde en $BaseUrl/health. Levantarlo con: " +
          "'uv run uvicorn app.main:create_app --factory --port 8082' " +
          "(y MongoDB en localhost:27017)")
}

# --- 2. Targets ---------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $TargetsDir, $OutDir | Out-Null

$wanted = @($Verbs | ForEach-Object { Join-Path $TargetsDir "$_.txt" })
$missing = @($wanted | Where-Object { -not (Test-Path $_) })
$readVerbs = @("get", "put", "delete")
$needsDocs = [bool](@($Verbs | Where-Object { $readVerbs -contains $_ }).Count) `
    -and $Verbs[0] -ne "post"

# La purga es parte de la preparacion, no del artefacto: aunque los targets
# existan hay que ejecutarla, porque los 409 viven en la base, no en el disco.
$needsPreClean = ($Verbs -contains "post") -and -not $NoPreClean

if ($ForceTargets -or $missing -or $needsPreClean) {
    if ($Count -le 0) { $Count = [math]::Ceiling($spec.Rate * $spec.Seconds * 1.1) }

    $gen = Join-Path $PSScriptRoot "gen_targets.py"
    $genArgs = @(
        "run", "python", $gen,
        "--count", "$Count",
        "--base-url", $BaseUrl,
        "--seed", "42",
        "--out-dir", $TargetsDir
    )
    if ($needsPreClean) { $genArgs += "--pre-clean" }
    if ($needsDocs -and -not $NoSeed) { $genArgs += "--load" }

    Write-Host "targets: preparando $Count por verbo..."
    & uv @genArgs
    if ($LASTEXITCODE -ne 0) { Fail "gen_targets.py ha fallado (codigo $LASTEXITCODE)" }
}

# --- 3. Ataque + 4. Umbral ----------------------------------------------------

$failures = @()

foreach ($verb in $Verbs) {
    $targets = Join-Path $TargetsDir "$verb.txt"
    $results = Join-Path $OutDir "vegeta-$Profile-$verb.results"
    $report = Join-Path $OutDir "vegeta-$Profile-$verb.report.txt"
    $json = Join-Path $OutDir "vegeta-$Profile-$verb.report.json"

    Write-Host ""
    Write-Host "=== $verb @ $($spec.Rate) rps / $($spec.Seconds)s ===" -ForegroundColor Cyan

    # -format json: los targets los genera gen_targets.py en el formato que
    # admite cuerpos inline (el HTTP legible se come el JSON como cabecera).
    # -output escribe el gob binario sin pasar por `>` ni por cmd.
    & vegeta attack -format json -targets $targets `
        -rate $spec.Rate -duration "$($spec.Seconds)s" `
        -name $verb -output $results
    if ($LASTEXITCODE -ne 0) { Fail "vegeta attack ha fallado para '$verb' (codigo $LASTEXITCODE)" }

    & vegeta report -type=text $results | Out-File -FilePath $report -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Fail "vegeta report (text) ha fallado para '$verb'" }
    Get-Content $report | Write-Host

    & vegeta report -type=json $results | Out-File -FilePath $json -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Fail "vegeta report (json) ha fallado para '$verb'" }

    # `vegeta report -type=json` devuelve un unico objeto agregado (requests,
    # success, status_codes, errors), no una fila por peticion. success es la
    # fraccion con codigo en [200,400); los errores de transporte quedan en 0
    # y por eso caen del lado de los fallos.
    $data = Get-Content $json -Raw | ConvertFrom-Json
    $total = [int]$data.requests
    if ($total -eq 0) { Fail "el informe de '$verb' esta vacio: nada se ataco" }

    $bad = $total - [int][Math]::Round([double]$data.success * $total)
    $pct = [math]::Round(100.0 * $bad / $total, 2)
    $verdict = if ($pct -gt $spec.ThresholdPct) { "FAIL" } else { "ok  " }
    Write-Host ("{0}  {1}: {2}% errores ({3}/{4}), umbral {5}%" -f `
        $verdict, $verb, $pct, $bad, $total, $spec.ThresholdPct) `
        -ForegroundColor $(if ($pct -gt $spec.ThresholdPct) { "Red" } else { "Green" })

    if ($pct -gt $spec.ThresholdPct) {
        $failures += "$verb=$pct%"
    }
}

Write-Host ""
Write-Host "Resultados en: $OutDir" -ForegroundColor Cyan

if ($failures) {
    Fail ("umbral superado en: " + ($failures -join ", ") +
          " (perfil '$Profile', " + $spec.ThresholdPct + "%)")
}

Write-Host "ok: todos los verbos dentro del umbral del perfil '$Profile'." -ForegroundColor Green
exit 0
