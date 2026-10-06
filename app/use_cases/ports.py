"""Puertos de la capa de casos de uso (Capa 2).

Este módulo define los contratos (puertos) de los que dependen los casos de uso.
La capa de infraestructura implementa esos puertos, manteniendo las
dependencias apuntando hacia dentro (Clean Architecture).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class CreateTextCommand:
    """Una petición ya validada para almacenar un texto (SPEC 1.3).

    Vive aquí, en la Capa 2, para que los casos de uso puedan aceptarlo sin
    depender de la capa de presentación que lo construye.
    """

    checksum: str
    text: str
    name: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class StoredText:
    """Un texto tal y como vive en la capa de persistencia."""

    checksum: str
    text: str
    created_at: datetime
    updated_at: datetime
    name: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class TextChanges:
    """Cambios que aplicar durante una actualización.

    ``None`` significa *no enviado, déjalo como está*, y por eso las
    comprobaciones de más abajo comparan contra ``None`` y nunca contra la
    veracidad del valor: ``""`` y ``{}`` son valores reales que el cliente
    tiene permiso para escribir.
    """

    name: str | None = None
    metadata: dict[str, Any] | None = None


@runtime_checkable
class TextRepository(Protocol):
    """Abstracción para almacenar y recuperar textos."""

    async def checksum_exists(self, checksum: str) -> bool: ...

    async def insert(self, item: StoredText) -> None: ...

    async def get_by_checksum(self, checksum: str) -> StoredText | None: ...

    async def update(
        self, checksum: str, changes: TextChanges
    ) -> StoredText | None: ...

    async def delete(self, checksum: str) -> bool: ...

    async def count(self) -> int: ...
