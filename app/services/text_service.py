from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.errors import ChecksumAlreadyExistsError, TextNotFoundError
from app.request_context import request_id_context
from app.use_cases.ports import (
    CreateTextCommand,
    StoredText,
    TextChanges,
    TextRepository,
)

logger = logging.getLogger(__name__)


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
        """
        Args:
            command: El texto ya validado que se debe almacenar.

        Raises:
            ChecksumAlreadyExistsError: Si el checksum ya está almacenado.
        """
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
        logger.info(
            "resource_changed operation=create result=success "
            "checksum_hash=%s request_id=%s",
            hashlib.sha256(command.checksum.encode("utf-8")).hexdigest()[:12],
            request_id_context.get() or "-",
        )

    async def find_by_checksum(self, checksum: str) -> StoredText:
        """Devuelve el texto almacenado.

        Args:
            checksum: El checksum que se busca, tratado como una cadena opaca.

        Returns:
            El texto que está almacenado.

        Raises:
            TextNotFoundError: Si ningún texto lleva ese checksum. El ``404`` se
                decide aquí, en la Capa 2, y no en el router.
        """
        item = await self._repository.get_by_checksum(checksum)
        if item is None:
            raise TextNotFoundError(f"no text with checksum {checksum!r}")
        return item

    async def update(self, checksum: str, changes: TextChanges) -> StoredText:
        """Aplica los cambios pedidos a un texto almacenado.
        Args:
            checksum: El checksum del texto que hay que cambiar, tomado de la
                cadena de consulta.
            changes: Qué cambiar. Un campo que se deje como ``None`` no se
                escribe.

        Returns:
            El texto tal y como queda tras la actualización.

        Raises:
            TextNotFoundError: Si ningún texto lleva ese checksum.
        """
        item = await self._repository.update(checksum, changes)
        if item is None:
            raise TextNotFoundError(f"no text with checksum {checksum!r}")
        logger.info(
            "resource_changed operation=update result=success "
            "checksum_hash=%s request_id=%s",
            hashlib.sha256(checksum.encode("utf-8")).hexdigest()[:12],
            request_id_context.get() or "-",
        )
        return item

    async def delete(self, checksum: str) -> None:
        """Elimina un texto almacenado.
        Args:
            checksum: El checksum del texto que hay que eliminar.

        Raises:
            TextNotFoundError: Si no había ningún texto que eliminar.
        """
        if not await self._repository.delete(checksum):
            raise TextNotFoundError(f"no text with checksum {checksum!r}")
        logger.info(
            "resource_changed operation=delete result=success "
            "checksum_hash=%s request_id=%s",
            hashlib.sha256(checksum.encode("utf-8")).hexdigest()[:12],
            request_id_context.get() or "-",
        )
