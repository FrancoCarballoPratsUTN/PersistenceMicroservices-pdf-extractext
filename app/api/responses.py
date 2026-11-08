"""Helpers de respuestas de la API."""

from __future__ import annotations


def ok_response(checksum: str) -> dict[str, str]:
    """Devuelve el cuerpo de acknowledge para POST y DELETE."""
    return {"message": "OK", "checksum": checksum}
