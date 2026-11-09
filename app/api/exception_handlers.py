"""Manejadores de excepción: convierte errores de servicio en respuestas Problem+JSON.

Registra los manejadores para :class:`ServiceError`, excepciones HTTP de Starlette
y excepciones no controladas, emitiendo siempre respuestas RFC 9457.
"""

import logging

from starlette.applications import Starlette
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.problem import (
    PROBLEM_MEDIA_TYPE,
    build_problem,
    instance_of,
    problem_response,
)
from app.errors import (
    InternalError,
    MethodNotAllowedError,
    ResourceNotFoundError,
    ServiceError,
)
from app.request_context import request_id_context

logger = logging.getLogger(__name__)

_ROUTING_ERRORS: dict[int, type[ServiceError]] = {
    404: ResourceNotFoundError,
    405: MethodNotAllowedError,
}


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """Convierte un :class:`ServiceError` en una respuesta Problem+JSON.

    Args:
        request: Petición que originó el error.
        exc: Error de servicio lanzado.

    Returns:
        Respuesta JSON con el detalle del problema.
    """
    return problem_response(exc, instance_of(request))


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Convierte una excepción HTTP de Starlette en una respuesta Problem+JSON.

    Args:
        request: Petición que originó el error.
        exc: Excepción HTTP de Starlette.

    Returns:
        Respuesta JSON con el detalle del problema.
    """
    error_cls = _ROUTING_ERRORS.get(exc.status_code)
    if error_cls is not None:
        return problem_response(error_cls(), instance_of(request))
    return JSONResponse(
        status_code=exc.status_code,
        media_type=PROBLEM_MEDIA_TYPE,
        content=build_problem(
            status=exc.status_code,
            type_uri="/problems/http_error",
            title="HTTP error",
            detail="The request could not be completed.",
            instance=instance_of(request),
            code="HTTP_ERROR",
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Maneja una excepción no controlada y devuelve un error 500.

    Args:
        request: Petición que originó el error.
        exc: Excepción no controlada.

    Returns:
        Respuesta JSON con el detalle del error interno.
    """
    request_id = getattr(request.state, "request_id", "-")
    token = request_id_context.set(request_id)
    try:
        logger.error(
            "Unhandled error while handling %s error_type=%s",
            request.url.path,
            type(exc).__name__,
        )
        response = problem_response(InternalError(), instance_of(request))
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_context.reset(token)


def register_exception_handlers(app: Starlette) -> None:
    """Registra los manejadores de excepción de la aplicación.

    Args:
        app: Instancia de la aplicación Starlette/FastAPI.

    Returns:
        Ninguno.
    """
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
