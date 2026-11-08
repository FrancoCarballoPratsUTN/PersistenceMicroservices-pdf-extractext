"""Errores HTTP de solicitud del cliente (4xx)."""

from app.errors.base import ServiceError


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


class PayloadTooLargeError(ServiceError):
    """El body de la petición, o el documento resultante, excede el tamaño permitido."""

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
