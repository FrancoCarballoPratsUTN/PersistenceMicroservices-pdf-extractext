"""Repositorio de textos sobre MongoDB: acceso a datos y traducción de errores.

Traduce las excepciones del driver de MongoDB a los errores de dominio del
servicio y reconstruye textos almacenados a partir de los documentos devueltos.
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
    """Devuelve la fecha y hora actuales en UTC."""
    return datetime.now(UTC)


def _invalid_stored_fields(document: dict[str, Any]) -> list[str]:
    """Identifica los campos inválidos de un documento de texto almacenado.

    Args:
        document: Documento de MongoDB a validar.

    Returns:
        Lista con los nombres de los campos que no cumplen el tipo esperado.
    """
    fields = {
        "checksum": (document.get("checksum") or document.get("_id"), str),
        "text": (document.get("text"), str),
        "created_at": (document.get("created_at"), datetime),
        "updated_at": (document.get("updated_at"), datetime),
    }
    invalid = [
        name
        for name, (value, expected_type) in fields.items()
        if not isinstance(value, expected_type)
    ]
    name = document.get("name")
    metadata = document.get("metadata")
    if name is not None and not isinstance(name, str):
        invalid.append("name")
    if metadata is not None and not isinstance(metadata, dict):
        invalid.append("metadata")
    return invalid


def _to_stored(document: dict[str, Any]) -> StoredText:
    """Reconstruye un texto y falla si MongoDB devolvió datos incompletos.

    Args:
        document: Documento de MongoDB que representa un texto almacenado.

    Returns:
        Instancia de :class:`StoredText` reconstruida a partir del documento.

    Raises:
        PersistenceError: Si el documento tiene campos faltantes o inválidos.
    """
    invalid_fields = _invalid_stored_fields(document)
    if invalid_fields:
        fields = ",".join(invalid_fields)
        logger.error(
            "MongoDB returned an invalid text document fields=%s request_id=%s",
            fields,
            request_id_context.get() or "-",
        )
        raise PersistenceError() from ValueError(
            f"Missing or invalid document fields: {fields}"
        )

    return StoredText(
        checksum=document.get("checksum") or document.get("_id"),
        text=document["text"],
        created_at=document["created_at"],
        updated_at=document["updated_at"],
        name=document.get("name"),
        metadata=document.get("metadata"),
    )


def persistence_error(error: PyMongoError, operation: str) -> PersistenceError:
    """Registra el error de MongoDB y construye un PersistenceError.

    Args:
        error: Excepción original de pymongo.
        operation: Nombre de la operación que falló.

    Returns:
        Instancia de :class:`PersistenceError` lista para lanzarse.
    """
    logger.error(
        "MongoDB operation failed operation=%s request_id=%s error_type=%s",
        operation,
        request_id_context.get() or "-",
        type(error).__name__,
    )
    return PersistenceError()


class MongoTextRepository:
    """Almacena los textos en la colección de MongoDB que se le entrega.

    Args:
        collection: La colección asíncrona que contiene los documentos de texto.
    """

    def __init__(self, collection: Any) -> None:
        """Guarda la colección sobre la que operará el repositorio.

        Args:
            collection: La colección asíncrona que contiene los documentos de
                texto.

        Returns:
            Ninguno.
        """
        self._collection = collection

    async def checksum_exists(self, checksum: str) -> bool:
        """Informa si un checksum ya está almacenado.

        Args:
            checksum: Checksum del texto a buscar.

        Returns:
            ``True`` si el checksum ya existe, ``False`` en caso contrario.
        """
        document = await self._find_one({"_id": checksum}, {"_id": 1})
        return document is not None

    async def insert(self, item: StoredText) -> None:
        """Almacena un texto, rechazando un checksum que ya esté ocupado.

        Args:
            item: Texto a almacenar.

        Returns:
            Ninguno.
        """
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
        """Devuelve el texto almacenado, o None cuando el checksum es desconocido.

        Args:
            checksum: Checksum del texto a buscar.

        Returns:
            El texto almacenado, o ``None`` si el checksum es desconocido.
        """
        document = await self._find_one({"_id": checksum})
        return _to_stored(document) if document is not None else None

    async def update(self, checksum: str, changes: TextChanges) -> StoredText | None:
        """Aplica los cambios y devuelve el resultado, o None si no existe.

        Args:
            checksum: Checksum del texto a actualizar.
            changes: Cambios a aplicar (nombre y metadatos).

        Returns:
            El texto actualizado, o ``None`` si el checksum no existe.
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
        """Elimina un texto, informando de si había alguno que eliminar.

        Args:
            checksum: Checksum del texto a eliminar.

        Returns:
            ``True`` si se eliminó un documento, ``False`` si no existía.
        """
        try:
            result = await self._collection.delete_one({"_id": checksum})
        except PyMongoError as error:
            raise persistence_error(error, "delete") from error
        return result.deleted_count == 1

    async def _find_one(
        self, query: dict[str, Any], projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Ejecuta una consulta, traduciendo cualquier fallo de MongoDB.

        Args:
            query: Consulta de filtrado para localizar el documento.
            projection: Proyección opcional de campos a devolver.

        Returns:
            El documento encontrado, o ``None`` si no hay coincidencia.
        """
        try:
            return await self._collection.find_one(query, projection=projection)
        except PyMongoError as error:
            raise persistence_error(error, "find_one") from error
