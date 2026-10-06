"""Genera los targets de Vegeta y siembra los documentos que el ataque leerá.

Vegeta no dinamiza cuerpos: lee un fichero de targets y lo repite en bucle a la
velocidad que se le pida. Como los cuatro verbos de este servicio exigen un
checksum único —un repetido responde ``409`` y contamina la medición—, el
precio de esa simplicidad se paga aquí: se generan N checksums únicos, se
convierten en N peticiones bien formadas y, si hace falta, se crean los
documentos antes de que llegue el ataque.

Uso típico::

    uv run python tests/stress/scripts/gen_targets.py --count 1000 --seed 42
    uv run python tests/stress/scripts/gen_targets.py --count 100 --load
    uv run python tests/stress/scripts/gen_targets.py --count 1000 --pre-clean

``SERVICE_API_TOKEN`` es obligatoria: los cuatro ficheros llevan el header
``Authorization`` y un target sin él sólo produciría ``401`` en bucle.

Vegeta acepta dos formatos de targets (``-format http`` y ``-format json``).
Se emite el JSON: el HTTP legible no admite cuerpos en línea — la línea en
blanco cierra la petición tras las cabeceras, así que un JSON ahí se come
como cabecera y Vegeta muere con "bad method" —, mientras que el JSON lleva
el cuerpo codificado en base64 dentro del propio target, sin ambiguaciones.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import httpx

VERBS = ("POST", "GET", "PUT", "DELETE")
DEFAULT_BASE_URL = "http://localhost:8082"
DEFAULT_OUT_DIR = Path("tests/stress/targets")
DEFAULT_COUNT = 1000


def generate_checksums(count: int, seed: int | None = None) -> list[str]:
    """Devuelve ``count`` checksums únicos como cadenas hexadecimales de 64.

    Args:
        count: Cuántos checksums generar.
        seed: Semilla opcional. Con ella la corrida es reproducible bit a bit;
            sin ella se elige una al azar, con lo que sigue garantizada la
            unicidad.

    Returns:
        La lista de checksums, únicos por construcción: todos salen de la
        misma fórmula ``sha256("<semilla>:<índice>")`` y sólo el índice varía.

    Raises:
        ValueError: Si ``count`` no es positivo.
    """
    if count < 1:
        raise ValueError(f"count must be positive, got {count}")
    effective = seed if seed is not None else int.from_bytes(os.urandom(8), "big")
    return [_sha256(f"{effective}:{index}") for index in range(count)]


def _sha256(value: str) -> str:
    """Devuelve el hash hexadecimal de ``value``.

    Args:
        value: La cadena de entrada.

    Returns:
        El digest de 64 caracteres.
    """
    return hashlib.sha256(value.encode()).hexdigest()


def build_targets(
    method: str, base_url: str, token: str, checksums: Sequence[str]
) -> str:
    """Compone el fichero de targets de Vegeta para un verbo.

    Args:
        method: Uno de :data:`VERBS`.
        base_url: Raíz del servicio, p. ej. ``http://localhost:8082``.
        token: Bearer que acompaña a cada petición.
        checksums: Uno por petición; el índice también nombra el payload.

    Returns:
        Un target JSON por línea — el formato que ``vegeta attack -format
        json`` espera de un fichero ``-targets`` — con ``method``, ``url``,
        ``header`` y, si el verbo lleva cuerpo, ``body`` en base64.

    Raises:
        ValueError: Si ``method`` no es un verbo conocido. Un verbo inventado
            sólo podría producir targets que Vegeta ataque contra la nada.
    """
    if method not in VERBS:
        raise ValueError(f"unknown verb: {method}")
    root = base_url.rstrip("/")
    lines = [
        _target_line(method, root, token, index, checksum)
        for index, checksum in enumerate(checksums)
    ]
    return "\n".join(lines) + "\n"


def _target_line(method: str, root: str, token: str, index: int, checksum: str) -> str:
    """Construye la línea JSON de una petición.

    Args:
        method: Verbo de la petición.
        root: Raíz del servicio sin barra final.
        token: Bearer para la cabecera ``Authorization``.
        index: Posición del checksum, que nombra el payload de escritura.
        checksum: El checksum objetivo.

    Returns:
        Un target JSON compacto: ``method`` y ``url`` en ese orden, después
        ``header`` (siempre con ``Authorization``; ``Content-Type`` cuando el
        verbo lleva cuerpo) y ``body`` en base64 sólo si lo hay.
    """
    if method == "POST":
        url = f"{root}/texts"
    else:
        url = f"{root}/texts?checksum={quote(checksum, safe='')}"
    target: dict = {"method": method, "url": url}
    body = _body(method, index, checksum)
    headers = {"Authorization": [f"Bearer {token}"]}
    if body is not None:
        headers = {"Content-Type": ["application/json"], **headers}
    target["header"] = headers
    if body is not None:
        target["body"] = base64.b64encode(body.encode()).decode()
    return json.dumps(target, separators=(",", ":"))


def _body(method: str, index: int, checksum: str) -> str | None:
    """Devuelve el cuerpo JSON del verbo, o ``None`` si no lleva.

    Args:
        method: Verbo de la petición.
        index: Posición del checksum.
        checksum: El checksum a crear (POST) o actualizar (PUT).

    Returns:
        JSON compacto para POST y PUT; ``None`` para GET y DELETE. El ``name``
        del PUT nunca es vacío porque ``PUT {}`` responde ``400`` por contrato
        y un target que lo enviara sería un falso negativo en el informe.
    """
    if method == "POST":
        payload = {"checksum": checksum, "text": f"stress payload {index}"}
    elif method == "PUT":
        payload = {"name": f"stress-{index}"}
    else:
        return None
    return json.dumps(payload, separators=(",", ":"))


def write_targets(
    out_dir: Path, base_url: str, token: str, checksums: Sequence[str]
) -> dict[str, Path]:
    """Escribe un fichero por verbo en ``out_dir``.

    Args:
        out_dir: Carpeta destino; se crea si no existe.
        base_url: Raíz del servicio.
        token: Bearer para las cabeceras.
        checksums: Los que compartirán los cuatro ficheros.

    Returns:
        Un dict de verbo en minúscula a la ruta escrita, en el orden de
        :data:`VERBS`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for verb in VERBS:
        path = out_dir / f"{verb.lower()}.txt"
        path.write_text(
            build_targets(verb, base_url, token, checksums), encoding="utf-8"
        )
        written[verb.lower()] = path
    return written


class LoadReport(NamedTuple):
    """Resultado de la siembra: cuántos documentos se crearon y cuántos ya estaban."""

    created: int
    existing: int


class PreCleanReport(NamedTuple):
    """Resultado de la limpieza previa: cuántos borrados y cuántos no existían."""

    deleted: int
    missing: int


def pre_clean(
    base_url: str,
    token: str,
    checksums: Sequence[str],
    *,
    client: httpx.Client | None = None,
) -> PreCleanReport:
    """Borra los documentos objetivo si existen antes de atacar.

    Una corrida interrumpida a mitad del ciclo (o una siembra ``--load``
    previa) deja documentos que el ``POST`` del ataque contestará con
    ``409``: el umbral los contaría como errores y el informe mentiría. Un
    ``DELETE`` por checksum sirve a la vez de purga y de sondeo — el que no
    existía responde ``404`` y se cuenta como *ausente*, sin abortar.

    Args:
        base_url: Raíz del servicio.
        token: Bearer de la petición.
        checksums: Los documentos a purgar.
        client: Cliente opcional, para tests con ``MockTransport``. Si se
            omite se crea y cierra uno propio.

    Returns:
        Cuántos se borraron y cuántos no estaban.

    Raises:
        httpx.HTTPStatusError: ante cualquier otro código — un ``401`` o un
            ``503`` durante la limpieza debe detener el pipeline, no pasar
            desapercibido.
    """
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=10.0)
    deleted = missing = 0
    try:
        for checksum in checksums:
            response = http.delete(
                f"{base_url.rstrip('/')}/texts",
                params={"checksum": checksum},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 404:
                missing += 1
            else:
                response.raise_for_status()
                deleted += 1
    finally:
        if owns_client:
            http.close()
    return PreCleanReport(deleted=deleted, missing=missing)


def load_documents(
    base_url: str,
    token: str,
    checksums: Sequence[str],
    *,
    client: httpx.Client | None = None,
) -> LoadReport:
    """Crea los documentos con ``POST /texts`` antes del ataque de lectura.

    Un ``409`` cuenta como *ya existía* y no aborta: la siembra es
    reanudable, y reejecutarla después de un ataque previo no debería
    romper el pipeline.

    Args:
        base_url: Raíz del servicio.
        token: Bearer de la petición.
        checksums: Los documentos a crear.
        client: Cliente opcional, para tests con ``MockTransport``. Si se
            omite se crea y cierra uno propio.

    Returns:
        Cuántos se crearon y cuántos ya estaban.

    Raises:
        httpx.HTTPStatusError: ante cualquier otro código — un ``401`` o un
            ``503`` durante la siembra debe detener el pipeline, no pasar
            desapercibido.
    """
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=10.0)
    created = existing = 0
    try:
        for index, checksum in enumerate(checksums):
            response = http.post(
                f"{base_url.rstrip('/')}/texts",
                json={"checksum": checksum, "text": f"stress payload {index}"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 201:
                created += 1
            elif response.status_code == 409:
                existing += 1
            else:
                response.raise_for_status()
    finally:
        if owns_client:
            http.close()
    return LoadReport(created=created, existing=existing)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: genera y escribe los cuatro ficheros de targets.

    Args:
        argv: Argumentos de línea de comandos; ``None`` lee ``sys.argv``.

    Returns:
        ``0`` si todo se escribió; ``2`` si falta el token o los argumentos
        no tienen sentido. El token se comprueba **antes** de escribir
        cualquier fichero: targets sin ``Authorization`` sólo servirían para
        coleccionar ``401``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--load",
        action="store_true",
        help="Crear los documentos via POST antes de escribir los targets.",
    )
    parser.add_argument(
        "--pre-clean",
        action="store_true",
        help="Borrar los documentos objetivo (409 de corridas previas) antes de nada.",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("SERVICE_API_TOKEN", "").strip()
    if not token:
        print(
            "error: SERVICE_API_TOKEN is required; every target carries a "
            "Bearer header and without it Vegeta would only collect 401s.",
            file=sys.stderr,
        )
        return 2

    try:
        checksums = generate_checksums(args.count, args.seed)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.pre_clean:
        report = pre_clean(args.base_url, token, checksums)
        print(f"pre-clean: {report.deleted} deleted, {report.missing} absent")

    written = write_targets(args.out_dir, args.base_url, token, checksums)
    for verb, path in written.items():
        print(f"{verb}: {path}")

    if args.load:
        report = load_documents(args.base_url, token, checksums)
        print(f"seed: {report.created} created, {report.existing} already present")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
