"""Documento almacenado -> el dict con el que responde la API (T12).

El cliente en Go decodifica seis miembros por nombre y trata uno ausente como su
valor cero, así que este mapeo es un contrato, no una comodidad. Vive aquí para
que ningún otro módulo tenga que saber cómo un texto almacenado se convierte
en JSON (SPEC 5.2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.use_cases.ports import StoredText


def to_api_dict(item: StoredText) -> dict[str, Any]:
    """Devuelve los seis miembros que la API promete para un texto almacenado.

    Args:
        item: El texto tal y como salió de la base de datos.

    Returns:
        ``checksum``, ``text``, ``name``, ``metadata``, ``created_at`` y
        ``updated_at``, sin dejar ningún miembro nulo.
    """
    return {
        "checksum": item.checksum,
        "text": item.text,
        "name": item.name or "",
        "metadata": item.metadata or {},
        "created_at": rfc3339(item.created_at),
        "updated_at": rfc3339(item.updated_at),
    }


def rfc3339(moment: datetime) -> str:
    """Devuelve una marca de tiempo en UTC como ``2026-10-01T12:34:56.789Z``.

    Args:
        moment: La marca de tiempo que hay que representar. Una que no lleve
            zona se lee como UTC, que es lo que devuelve MongoDB.

    Returns:
        RFC 3339 en UTC, con milisegundos y sufijo ``Z``.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (
        moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
