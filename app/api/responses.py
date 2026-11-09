"""Helpers de respuestas de la API."""

from __future__ import annotations


def ok_response(checksum: str) -> dict[str, str]:
    """Devuelve el cuerpo de acknowledge para POST y DELETE.

    Args:
        checksum: Checksum del texto afectado.

    Returns:
        Diccionario con el mensaje de acknowledge y el checksum.
    """
    return {"message": "OK", "checksum": checksum}
