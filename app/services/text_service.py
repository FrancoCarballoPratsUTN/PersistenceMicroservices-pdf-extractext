"""Lógica de negocio del recurso de textos (Capa 2).

El servicio es dueño de las reglas que los endpoints deben respetar y de las
marcas de tiempo que las acompañan; la persistencia se queda detrás del puerto
(SPEC 4).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.errors import ChecksumAlreadyExistsError, TextNotFoundError
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
        """Almacena un texto, rechazando un checksum que ya esté ocupado.

        La primera barrera es la búsqueda, que responde sin tocar MongoDB. La
        segunda es el ``_id`` único, que es lo que de verdad cierra la carrera
        bajo concurrencia (SPEC 5.3): el repositorio lanza
        ``ChecksumAlreadyExistsError`` ante el duplicado y aquí no se captura.

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

        El servicio sólo decide qué significa no encontrarlo: el repositorio
        informa de que no se actualizó nada y el ``404`` se lanza aquí, en la
        Capa 2, en vez de en el router.

        La marca ``updated_at`` es del repositorio y deliberadamente no se
        asigna aquí, así que el servicio nunca es dueño de un reloj en este
        camino.

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
        return item

    async def delete(self, checksum: str) -> None:
        """Elimina un texto almacenado.

        No hay ninguna búsqueda antes del borrado: el repositorio ya informa de
        si quitó algo, y preguntar dos veces sólo añadiría un viaje de ida y
        vuelta y una segunda respuesta que mantener sincronizada.

        Args:
            checksum: El checksum del texto que hay que eliminar.

        Raises:
            TextNotFoundError: Si no había ningún texto que eliminar.
        """
        if not await self._repository.delete(checksum):
            raise TextNotFoundError(f"no text with checksum {checksum!r}")
