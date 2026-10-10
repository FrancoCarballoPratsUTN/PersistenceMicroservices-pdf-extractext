"""La conexión a MongoDB: cómo se construye, se comprueba, se prepara y se cierra.

Este es el único sitio del servicio que sabe que MongoDB existe (SPEC 2.1).
Todo lo que está por encima pregunta a la conexión si MongoDB responde, y nunca
importa pymongo.
"""

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlsplit

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.config import Settings

logger = logging.getLogger(__name__)

ClientFactory = Callable[..., AsyncMongoClient]


def _redact_uri(uri: str) -> str:
    """Oculta las credenciales de una URI para que las contraseñas no lleguen al log."""
    parsed = urlsplit(uri)
    if parsed.password:
        return uri.replace(f":{unquote(parsed.password)}@", ":****@")
    return uri


class MongoConnection:
    """Mantiene el cliente de MongoDB y responde si la base de datos es usable.

    Args:
        settings: De dónde salen la URI, la base de datos y el tiempo máximo.
        client_factory: Construye el cliente. En producción se usa el
            AsyncMongoClient de pymongo; los tests entregan un doble, así que
            nada tiene que abrir un socket.
    """

    def __init__(
        self, settings: Settings, client_factory: ClientFactory = AsyncMongoClient
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._client: AsyncMongoClient | None = None

    async def start(self) -> bool:
        """Abre la conexión, comprueba MongoDB y prepara el índice de textos.

        Returns:
            True cuando MongoDB ha respondido y el índice está en su sitio.
            False cuando ha fallado cualquiera de los dos pasos: el servicio
            tiene que seguir en pie y dejar que /readyz lo informe, así que no
            se lanza nada.
        """
        timeout = self._settings.mongodb_timeout_ms
        uri = self._settings.mongodb_uri
        self._client = self._client_factory(
            uri,
            serverSelectionTimeoutMS=timeout,
            connectTimeoutMS=timeout,
        )
        logger.debug("MongoDB connection prepared with uri=%s", _redact_uri(uri))
        if not await self.is_available():
            logger.warning(
                "MongoDB did not answer during start-up; /readyz reports unavailable."
            )
            return False
        try:
            await self.texts().create_index("updated_at")
        except PyMongoError as error:
            logger.warning(
                "The updated_at index could not be prepared: %s", type(error).__name__
            )
            return False
        return True

    async def close(self) -> None:
        """Libera el cliente. Seguro de llamar más de una vez."""
        if self._client is None:
            return
        await self._client.close()

    async def is_available(self) -> bool:
        """Pregunta a MongoDB si está. Nunca lanza, nunca se bloquea eternamente."""
        if self._client is None:
            return False
        try:
            await self._database().command("ping")
        except PyMongoError:
            return False
        return True

    def _database(self) -> Any:
        return self._client[self._settings.mongodb_database]

    def texts(self) -> Any:
        """Devuelve la colección que contiene los textos.

        El repositorio se construye sobre ella, así que todo el servicio
        comparte un único cliente y un único pool de conexiones.
        """
        return self._database()[self._settings.mongodb_texts_collection]
