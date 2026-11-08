"""Errores de persistencia e infraestructura (5xx)."""

from app.errors.base import ServiceError
from app.errors.http import PayloadTooLargeError


class PersistenceError(ServiceError):
    """MongoDB estaba inalcanzable o devolvió un error del servidor."""

    status = 503
    code = "PERSISTENCE_ERROR"
    type_uri = "/problems/persistence_error"
    title = "Persistence unavailable"
    default_detail = "The persistence layer is unavailable."


class DocumentTooLargeError(PayloadTooLargeError):
    """Error de documento demasiado grande de MongoDB.

    Equivale a ``pymongo.errors.DocumentTooLarge``.
    """


class InternalError(ServiceError):
    """Último recurso para una excepción que ninguna capa anticipó.

    Hereda todo el contrato de :class:`ServiceError` en vez de repetirlo: un
    error sin clasificar es exactamente un error interno, y restatear los valores
    daría a las dos definiciones la oportunidad de discrepar.
    """
