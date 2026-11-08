"""Acceso a colecciones de MongoDB."""

from __future__ import annotations

from typing import Any


def texts(connection) -> Any:
    """Devuelve la colección que contiene los textos."""
    return connection._database()[connection._settings.mongo_texts_collection]
