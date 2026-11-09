"""Ciclo de vida del cliente de MongoDB: conexión, disponibilidad y cierre."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.config import Settings
from app.repositories.mongodb.collections import texts as _texts
from app.repositories.mongodb.utils import ClientFactory, redact_uri

logger = logging.getLogger(__name__)


class MongoConnection:
    """Mantiene el cliente de MongoDB y responde si la BD es usable."""

    def __init__(
        self, settings: Settings, client_factory: ClientFactory = AsyncMongoClient
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._client: AsyncMongoClient | None = None
        self._last_readiness_check: float | None = None
        self._last_availability: bool | None = None

    async def start(self) -> bool:
        """Abre la conexión y comprueba que MongoDB responde."""
        timeout = self._settings.mongo_timeout_ms
        uri = self._settings.mongo_uri
        self._last_readiness_check = self._last_availability = None
        self._client = self._client_factory(
            uri,
            timeoutMS=timeout,
            serverSelectionTimeoutMS=timeout,
            connectTimeoutMS=timeout,
            socketTimeoutMS=self._settings.mongo_socket_timeout_ms,
            maxPoolSize=self._settings.mongo_max_pool_size,
            retryWrites=False,
        )
        logger.debug("MongoDB connection prepared with uri=%s", redact_uri(uri))
        if not await self.is_available():
            logger.warning(
                "MongoDB did not answer during start-up; /readyz reports unavailable."
            )
            return False
        return True

    async def close(self) -> None:
        """Libera el cliente. Seguro de llamar más de una vez."""
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
            available = True
        except PyMongoError:
            available = False

        self._last_readiness_check = now
        self._last_availability = available
        return available

    def _database(self) -> Any:
        return self._client[self._settings.mongo_database]

    def texts(self) -> Any:
        """Devuelve la colección que contiene los textos."""
        return _texts(self)
