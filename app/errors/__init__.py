"""Jerarquía de errores del servicio: re-exporta los submódulos del paquete."""

from app.errors.base import ServiceError
from app.errors.domain import (
    ChecksumAlreadyExistsError,
    ImmutableFieldError,
    TextNotFoundError,
)
from app.errors.http import (
    MethodNotAllowedError,
    PayloadTooLargeError,
    ResourceNotFoundError,
    UnauthorizedError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from app.errors.persistence import (
    DocumentTooLargeError,
    InternalError,
    PersistenceError,
)

__all__ = [
    "ServiceError",
    "ChecksumAlreadyExistsError",
    "ImmutableFieldError",
    "TextNotFoundError",
    "UnauthorizedError",
    "ValidationError",
    "PayloadTooLargeError",
    "UnsupportedMediaTypeError",
    "MethodNotAllowedError",
    "ResourceNotFoundError",
    "PersistenceError",
    "DocumentTooLargeError",
    "InternalError",
]
