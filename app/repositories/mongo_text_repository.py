"""Implementación en MongoDB del puerto TextRepository (T8).

El repositorio traduce los fallos de MongoDB al vocabulario del dominio, así que
nada por encima de esta capa tiene que saber que pymongo existe (SPEC 2.1).

Recibe la colección en vez de construir un cliente: :mod:`app.repositories.mongodb`
ya es dueño de la conexión y de su ciclo de vida, y un segundo cliente aquí sería
un segundo pool de conexiones para la misma base de datos.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DocumentTooLarge as PymongoDocumentTooLarge
from pymongo.errors import DuplicateKeyError as PymongoDuplicateKeyError
from pymongo.errors import PyMongoError

from app.errors import (
    ChecksumAlreadyExistsError,
    DocumentTooLargeError,
    PersistenceError,
)
from app.request_context import request_id_context
from app.use_cases.ports import StoredText, TextChanges

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_stored(document: dict[str, Any]) -> StoredText:
    """Reconstruye un texto almacenado a partir del documento que devolvió MongoDB."""
    return StoredText(
        checksum=document.get("checksum") or document["_id"],
        text=document.get("text", ""),
        created_at=document.get("created_at") or _utcnow(),
        updated_at=document.get("updated_at") or _utcnow(),
        name=document.get("name"),
        metadata=document.get("metadata"),
    )


def persistence_error(error: PyMongoError, operation: str) -> PersistenceError:
    logger.error(
        "MongoDB operation failed operation=%s request_id=%s error_type=%s error=%s",
        operation,
        request_id_context.get() or "-",
        type(error).__name__,
        error,
    )
    return PersistenceError()


class MongoTextRepository:
    """Almacena los textos en la colección de MongoDB que se le entrega.

    Args:
        collection: La colección asíncrona que contiene los documentos de texto.
    """

    def __init__(self, collection: Any) -> None:
        self._collection = collection

    async def checksum_exists(self, checksum: str) -> bool:
        """Informa si un checksum ya está almacenado."""
        document = await self._find_one({"_id": checksum}, {"_id": 1})
        return document is not None

    async def insert(self, item: StoredText) -> None:
        """Almacena un texto, rechazando un checksum que ya esté ocupado."""
        document = {
            "_id": item.checksum,
            "checksum": item.checksum,
            "text": item.text,
            "name": item.name,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "metadata": item.metadata,
        }
        try:
            await self._collection.insert_one(document)
        except PymongoDuplicateKeyError as error:
            raise ChecksumAlreadyExistsError() from error
        except PymongoDocumentTooLarge as error:
            raise DocumentTooLargeError() from error
        except PyMongoError as error:
            raise persistence_error(error, "insert") from error

    async def get_by_checksum(self, checksum: str) -> StoredText | None:
        """Devuelve el texto almacenado, o None cuando el checksum es desconocido."""
        document = await self._find_one({"_id": checksum})
        return _to_stored(document) if document is not None else None

    async def update(self, checksum: str, changes: TextChanges) -> StoredText | None:
        """Aplica los cambios y devuelve el resultado, o None si no existe.

        Sólo se escriben los campos que el cliente envió de verdad: un cambio
        que se deja como ``None`` no aparece en el ``$set`` y conserva su valor
        almacenado. Las comparaciones son contra ``None`` para que una cadena
        vacía o un objeto vacío siga sobrescribiendo, y ``created_at`` nunca
        entra en el ``$set``.
        """
        update: dict[str, Any] = {"updated_at": _utcnow()}
        if changes.name is not None:
            update["name"] = changes.name
        if changes.metadata is not None:
            update["metadata"] = changes.metadata
        try:
            document = await self._collection.find_one_and_update(
                {"_id": checksum},
                {"$set": update},
                return_document=ReturnDocument.AFTER,
            )
        except PymongoDocumentTooLarge as error:
            raise DocumentTooLargeError() from error
        except PyMongoError as error:
            raise persistence_error(error, "update") from error
        return _to_stored(document) if document is not None else None

    async def delete(self, checksum: str) -> bool:
        """Elimina un texto, informando de si había alguno que eliminar."""
        try:
            result = await self._collection.delete_one({"_id": checksum})
        except PyMongoError as error:
            raise persistence_error(error, "delete") from error
        return result.deleted_count == 1

    async def _find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Ejecuta una consulta, traduciendo cualquier fallo de MongoDB."""
        try:
            return await self._collection.find_one(query, projection=projection)
        except PyMongoError as error:
            raise persistence_error(error, "find_one") from error
