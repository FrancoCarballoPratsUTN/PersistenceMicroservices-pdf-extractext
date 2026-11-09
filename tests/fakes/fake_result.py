"""Resultado de reconocimiento que pymongo devuelve tras una escritura."""

from __future__ import annotations

from typing import Any


class _Result:
    """El pequeño reconocimiento que pymongo devuelve tras una escritura."""

    def __init__(self, *, inserted_id: Any = None, deleted_count: int = 0) -> None:
        self.inserted_id = inserted_id
        self.deleted_count = deleted_count
