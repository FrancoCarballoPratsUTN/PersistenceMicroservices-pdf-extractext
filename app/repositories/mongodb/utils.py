"""Utilidades compartidas del cliente de MongoDB."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import unquote, urlsplit

from pymongo import AsyncMongoClient

ClientFactory = Callable[..., AsyncMongoClient]


def redact_uri(uri: str) -> str:
    """Oculta las credenciales de una URI para que las contraseñas no lleguen al log."""
    parsed = urlsplit(uri)
    if parsed.password:
        return uri.replace(f":{unquote(parsed.password)}@", ":****@")
    return uri
