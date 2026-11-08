"""Errores de dominio de negocio (4xx de reglas del servicio)."""

from app.errors.base import ServiceError


class ChecksumAlreadyExistsError(ServiceError):
    """Ya hay un documento guardado con este checksum."""

    status = 409
    code = "CHECKSUM_ALREADY_EXISTS"
    type_uri = "/problems/checksum_already_exists"
    title = "Checksum already exists"
    default_detail = "A document with this checksum already exists."


class TextNotFoundError(ServiceError):
    """La ruta coincidió, pero ningún documento tiene ese checksum."""

    status = 404
    code = "TEXT_NOT_FOUND"
    type_uri = "/problems/text_not_found"
    title = "Text not found"
    default_detail = "No document exists for the requested checksum."


class ImmutableFieldError(ServiceError):
    """Un ``PUT`` intentó llevar ``text`` o ``checksum`` en el body."""

    status = 400
    code = "IMMUTABLE_FIELD"
    type_uri = "/problems/immutable_field"
    title = "Immutable field"
    default_detail = "The request tried to modify an immutable field."
