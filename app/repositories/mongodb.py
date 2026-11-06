"""La conexión a MongoDB: cómo se construye, se comprueba, se prepara y se cierra.

Este es el único sitio del servicio que sabe que MongoDB existe (SPEC 2.1).
Todo lo que está por encima pregunta a la conexión si MongoDB responde, y nunca
importa pymongo.
"""

import logging
from collections.abc import Callable
from time import monotonic
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
        self._last_readiness_check: float | None = None
        self._last_availability: bool | None = None

    async def start(self) -> bool:
        """Abre la conexión y comprueba que MongoDB responde.

        Returns:
            True cuando MongoDB ha respondido. False cuando no está disponible;
            el servicio sigue en pie y /readyz informa del fallo.
        """
        timeout = self._settings.mongo_timeout_ms
        uri = self._settings.mongo_uri
        self._last_readiness_check = None
        self._last_availability = None
        self._client = self._client_factory(
            uri,
            timeoutMS=timeout,
            serverSelectionTimeoutMS=timeout,
            connectTimeoutMS=timeout,
            socketTimeoutMS=self._settings.mongo_socket_timeout_ms,
            maxPoolSize=self._settings.mongo_max_pool_size,
            retryWrites=False,
        )
        logger.debug("MongoDB connection prepared with uri=%s", _redact_uri(uri))
        if not await self.is_available():
            logger.warning(
                "MongoDB did not answer during start-up; /readyz reports unavailable."
            )
            return False
        return True

    async def close(self) -> None:
        """Libera el cliente. Seguro de llamar más de una vez.

        Soltar el pool no puede ser la razón de que un apagado limpio salga con
        error, así que un error del driver se registra y se traga, igual que
        ``is_available`` nunca propaga un error de red. La raíz de composición
        conserva un último seguro para lo que este método no anticipa.
        """
        if self._client is None:
            return
        try:
            await self._client.close()
        except PyMongoError as error:
            logger.warning(
                "The MongoDB client could not be closed cleanly: %s",
                type(error).__name__,
            )

    async def is_available(self) -> bool:
        """Pregunta a MongoDB si está. Nunca lanza, nunca se bloquea eternamente."""
        if self._client is None:
            return False
        now = monotonic()
        ttl = self._settings.mongo_readiness_cache_ttl_seconds
        if (
            self._last_readiness_check is not None
            and now - self._last_readiness_check < ttl
        ):
            return bool(self._last_availability)

        try:
            await self._database().command("ping")
        except PyMongoError:
            available = False
        else:
            available = True

        self._last_readiness_check = now
        self._last_availability = available
        return available

    def _database(self) -> Any:
        return self._client[self._settings.mongo_database]

    def texts(self) -> Any:
        """Devuelve la colección que contiene los textos.

        El repositorio se construye sobre ella, así que todo el servicio
        comparte un único cliente y un único pool de conexiones.
        """
        return self._database()[self._settings.mongo_texts_collection]
