from typing import ClassVar


class ServiceError(Exception):
    """Clase base de todo fallo que este servicio reporta a un cliente."""

    status: ClassVar[int] = 500
    code: ClassVar[str] = "INTERNAL_ERROR"
    type_uri: ClassVar[str] = "/problems/internal_error"
    title: ClassVar[str] = "Internal server error"
    default_detail: ClassVar[str] = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class ChecksumAlreadyExistsError(ServiceError):
    """Ya hay un documento guardado con este checksum. """

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


class UnauthorizedError(ServiceError):
    """El token bearer faltaba, venía mal formado o no era el configurado."""

    status = 401
    code = "UNAUTHORIZED"
    type_uri = "/problems/unauthorized"
    title = "Unauthorized"
    default_detail = "A valid bearer token is required."


class ValidationError(ServiceError):
    """El body o el query string de la petición son inválidos estructuralmente."""

    status = 400
    code = "VALIDATION_ERROR"
    type_uri = "/problems/validation_error"
    title = "Request validation error"
    default_detail = "The request body or query parameters are invalid."


class ImmutableFieldError(ServiceError):
    """Un ``PUT`` intentó llevar ``text`` o ``checksum`` en el body."""

    status = 400
    code = "IMMUTABLE_FIELD"
    type_uri = "/problems/immutable_field"
    title = "Immutable field"
    default_detail = "The request tried to modify an immutable field."


class PayloadTooLargeError(ServiceError):
    """El body de la petición, o el documento resultante, excede el tamaño permitido. """

    status = 413
    code = "PAYLOAD_TOO_LARGE"
    type_uri = "/problems/payload_too_large"
    title = "Payload too large"
    default_detail = "The document exceeds the maximum allowed size."


class UnsupportedMediaTypeError(ServiceError):
    """El ``Content-Type`` de la petición no fue ``application/json``."""

    status = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    type_uri = "/problems/unsupported_media_type"
    title = "Unsupported media type"
    default_detail = "The request Content-Type must be application/json."


class MethodNotAllowedError(ServiceError):
    """La ruta que coincidió no admite el verbo HTTP."""

    status = 405
    code = "METHOD_NOT_ALLOWED"
    type_uri = "/problems/method_not_allowed"
    title = "Method not allowed"
    default_detail = "The HTTP method is not supported by this resource."


class ResourceNotFoundError(ServiceError):
    """La ruta solicitada no existe."""

    status = 404
    code = "NOT_FOUND"
    type_uri = "/problems/not_found"
    title = "Resource not found"
    default_detail = "The requested resource does not exist."


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
