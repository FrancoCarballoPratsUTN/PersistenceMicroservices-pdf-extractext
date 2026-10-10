"""Genera los targets de Vegeta y prepara los documentos del ataque.

Vegeta repite a ritmo constante un fichero de targets y no sabe inventar
cuerpos. Como el servicio responde ``409`` a un checksum repetido, aquí se
generan N checksums únicos, se escriben los cuatro ficheros de targets y, si
se pide, se purgan o siembran los documentos antes del ataque.

    uv run python tests/stress/scripts/gen_targets.py --count 1000 --seed 42
    uv run python tests/stress/scripts/gen_targets.py --count 100 --load
    uv run python tests/stress/scripts/gen_targets.py --count 1000 --pre-clean

``SERVICE_API_TOKEN`` es obligatoria: cada target lleva su ``Authorization`` y
sin él sólo se recogerían ``401``. Los targets se emiten en el formato JSON de
Vegeta (``-format json``) —un target por línea con el cuerpo en base64— porque
el formato HTTP legible no admite cuerpos en línea.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import httpx

VERBS = ("POST", "GET", "PUT", "DELETE")
DEFAULT_BASE_URL = "http://localhost:8082"
DEFAULT_OUT_DIR = Path("tests/stress/targets")
DEFAULT_COUNT = 1000


class LoadReport(NamedTuple):
    """Siembra: cuántos documentos se crearon y cuántos ya estaban."""

    created: int
    existing: int


class PreCleanReport(NamedTuple):
    """Purga: cuántos documentos se borraron y cuántos no existían."""

    deleted: int
    missing: int


def generate_checksums(count: int, seed: int | None = None) -> list[str]:
    """Devuelve ``count`` checksums únicos (sha256 de ``seed:índice``)."""
    if count < 1:
        raise ValueError(f"count must be positive, got {count}")
    effective = seed if seed is not None else int.from_bytes(os.urandom(8), "big")
    return [
        hashlib.sha256(f"{effective}:{index}".encode()).hexdigest()
        for index in range(count)
    ]


def build_targets(
    method: str, base_url: str, token: str, checksums: Sequence[str]
) -> str:
    """Compone el fichero de targets de Vegeta para un verbo (una línea cada uno)."""
    if method not in VERBS:
        raise ValueError(f"unknown verb: {method}")
    root = base_url.rstrip("/")
    return "".join(
        _target_line(method, root, token, index, checksum) + "\n"
        for index, checksum in enumerate(checksums)
    )


def _target_line(method: str, root: str, token: str, index: int, checksum: str) -> str:
    """Serializa una petición como un target JSON de Vegeta."""
    url = f"{root}/texts" if method == "POST" else _item_url(root, checksum)
    body = _body(method, index, checksum)
    headers = {"Authorization": [f"Bearer {token}"]}
    target: dict = {"method": method, "url": url, "header": headers}
    if body is not None:
        headers["Content-Type"] = ["application/json"]
        target["body"] = base64.b64encode(body.encode()).decode()
    return json.dumps(target, separators=(",", ":"))


def _item_url(root: str, checksum: str) -> str:
    return f"{root}/texts?checksum={quote(checksum, safe='')}"


def _body(method: str, index: int, checksum: str) -> str | None:
    """Cuerpo del verbo, o ``None`` si no lleva. El ``name`` del PUT nunca es
    vacío porque ``PUT {}`` responde ``400`` y sería un falso negativo."""
    if method == "POST":
        return _json({"checksum": checksum, "text": f"stress payload {index}"})
    if method == "PUT":
        return _json({"name": f"stress-{index}"})
    return None


def _json(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_targets(
    out_dir: Path, base_url: str, token: str, checksums: Sequence[str]
) -> dict[str, Path]:
    """Escribe un fichero por verbo y devuelve ``{verbo: ruta}``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for verb in VERBS:
        path = out_dir / f"{verb.lower()}.txt"
        targets = build_targets(verb, base_url, token, checksums)
        path.write_text(targets, encoding="utf-8")
        written[verb.lower()] = path
    return written


@contextmanager
def _http(client: httpx.Client | None) -> Iterator[httpx.Client]:
    """Entrega el cliente dado, o crea y cierra uno propio."""
    if client is not None:
        yield client
    else:
        with httpx.Client(timeout=10.0) as owned:
            yield owned


def pre_clean(
    base_url: str,
    token: str,
    checksums: Sequence[str],
    *,
    client: httpx.Client | None = None,
) -> PreCleanReport:
    """Borra los documentos objetivo para que el ``POST`` del ataque no mida
    ``409``. Un ``404`` cuenta como *ausente* y no aborta."""
    root = base_url.rstrip("/")
    deleted = missing = 0
    with _http(client) as http:
        for checksum in checksums:
            response = http.delete(_item_url(root, checksum), headers=_auth(token))
            if response.status_code == 404:
                missing += 1
            else:
                response.raise_for_status()
                deleted += 1
    return PreCleanReport(deleted=deleted, missing=missing)


def load_documents(
    base_url: str,
    token: str,
    checksums: Sequence[str],
    *,
    client: httpx.Client | None = None,
) -> LoadReport:
    """Crea los documentos con ``POST /texts``; un ``409`` cuenta como *ya
    existía* y no aborta, de modo que la siembra es reanudable."""
    root = base_url.rstrip("/")
    created = existing = 0
    with _http(client) as http:
        for index, checksum in enumerate(checksums):
            response = http.post(
                f"{root}/texts",
                json={"checksum": checksum, "text": f"stress payload {index}"},
                headers=_auth(token),
            )
            if response.status_code == 201:
                created += 1
            elif response.status_code == 409:
                existing += 1
            else:
                response.raise_for_status()
    return LoadReport(created=created, existing=existing)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: purga y/o siembra, y escribe los cuatro ficheros de targets.

    Devuelve ``2`` si falta el token (comprobado **antes** de escribir nada)
    o si los argumentos no tienen sentido.
    """
    args = _parse_args(argv)

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

    for verb, path in write_targets(
        args.out_dir, args.base_url, token, checksums
    ).items():
        print(f"{verb}: {path}")

    if args.load:
        report = load_documents(args.base_url, token, checksums)
        print(f"seed: {report.created} created, {report.existing} already present")

    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
