"""Helpers de auditoría y logging para el servicio de textos."""

from __future__ import annotations

import hashlib
import logging

from app.request_context import request_id_context

logger = logging.getLogger(__name__)


def checksum_hash(checksum: str) -> str:
    """Devuelve los primeros 12 caracteres del hash SHA-256 de un checksum."""
    return hashlib.sha256(checksum.encode("utf-8")).hexdigest()[:12]


def log_resource_change(operation: str, checksum: str) -> None:
    """Emite un log de negocio para un cambio de recurso sin exponer PII.

    Args:
        operation: Nombre de la operación (create, update, delete).
        checksum: Checksum del texto afectado (se hashea antes de loguear).
    """
    logger.info(
        "resource_changed operation=%s result=success "
        "checksum_hash=%s request_id=%s",
        operation,
        checksum_hash(checksum),
        request_id_context.get() or "-",
    )


def require_found(item, checksum: str):
    """Devuelve el ítem o lanza TextNotFoundError si no existe.

    Args:
        item: Resultado del repositorio (puede ser None).
        checksum: Checksum buscado, usado en el mensaje de error.

    Returns:
        El ítem si no es None.

    Raises:
        TextNotFoundError: Si item es None.
    """
    from app.errors import TextNotFoundError

    if item is None:
        raise TextNotFoundError(f"no text with checksum {checksum!r}")
    return item
