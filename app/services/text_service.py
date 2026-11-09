from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.errors import ChecksumAlreadyExistsError, TextNotFoundError
from app.services.audit_logger import log_resource_change, require_found
from app.use_cases.ports import (
    CreateTextCommand,
    StoredText,
    TextChanges,
    TextRepository,
)


class TextService:
    """Casos de uso sobre los textos almacenados.

    Args:
        repository: Dónde viven los textos.
        now_factory: Reloj, sustituible en los tests. Por defecto, el ahora en
            UTC.
    """

    def __init__(
        self,
        repository: TextRepository,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._now_factory = now_factory or (lambda: datetime.now(UTC))

    async def create(self, command: CreateTextCommand) -> None:
        """Almacena un texto, rechazando un checksum duplicado."""
        if await self._repository.checksum_exists(command.checksum):
            raise ChecksumAlreadyExistsError("checksum already exists")

        now = self._now_factory()
        await self._repository.insert(
            StoredText(
                checksum=command.checksum,
                text=command.text,
                name=command.name,
                metadata=command.metadata or {},
                created_at=now,
                updated_at=now,
            )
        )
        log_resource_change("create", command.checksum)

    async def find_by_checksum(self, checksum: str) -> StoredText:
        """Devuelve el texto almacenado, o lanza TextNotFoundError."""
        return require_found(await self._repository.get_by_checksum(checksum), checksum)

    async def update(self, checksum: str, changes: TextChanges) -> StoredText:
        """Aplica los cambios y devuelve el texto actualizado."""
        item = require_found(await self._repository.update(checksum, changes), checksum)
        log_resource_change("update", checksum)
        return item

    async def delete(self, checksum: str) -> None:
        """Elimina un texto, lanzando TextNotFoundError si no existía."""
        if not await self._repository.delete(checksum):
            raise TextNotFoundError(f"no text with checksum {checksum!r}")
        log_resource_change("delete", checksum)
