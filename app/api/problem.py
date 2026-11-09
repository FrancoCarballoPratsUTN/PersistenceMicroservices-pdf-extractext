"""Construcción de respuestas Problem+JSON (RFC 9457) para errores de la API."""

from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.errors import ServiceError

PROBLEM_MEDIA_TYPE = "application/problem+json"
REDACTED = "<redacted>"


def instance_of(request: Request) -> str:
    """Construye el campo ``instance`` a partir de la petición.

    Args:
        request: Petición entrante.

    Returns:
        Ruta de la petición con los valores de consulta enmascarados.
    """
    parameters = "&".join(f"{name}={REDACTED}" for name in request.query_params)
    return f"{request.url.path}?{parameters}" if parameters else request.url.path


def build_problem(
    *,
    status: int,
    type_uri: str,
    title: str,
    detail: str,
    instance: str,
    code: str,
) -> dict[str, str | int]:
    """Construye un diccionario Problem+JSON a partir de sus campos.

    Args:
        status: Código de estado HTTP.
        type_uri: URI de referencia del tipo de problema.
        title: Título breve del problema.
        detail: Detalle explicativo del problema.
        instance: Identificador de la ocurrencia concreta.
        code: Código de error interno del servicio.

    Returns:
        Diccionario con los campos del problema RFC 9457.
    """
    return {
        "type": type_uri,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
        "code": code,
    }


def problem_from_error(error: ServiceError, instance: str) -> dict[str, str | int]:
    """Construye un diccionario Problem+JSON a partir de un :class:`ServiceError`.

    Args:
        error: Error de servicio a convertir.
        instance: Identificador de la ocurrencia concreta.

    Returns:
        Diccionario con los campos del problema RFC 9457.
    """
    return build_problem(
        status=error.status,
        type_uri=error.type_uri,
        title=error.title,
        detail=error.detail,
        instance=instance,
        code=error.code,
    )


def problem_response(
    error: ServiceError, instance: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    """Construye una respuesta JSON Problem+JSON a partir de un error.

    Args:
        error: Error de servicio a convertir en respuesta.
        instance: Identificador de la ocurrencia concreta.
        headers: Cabeceras HTTP adicionales opcionales.

    Returns:
        Respuesta JSON con código de estado y media type Problem+JSON.
    """
    return JSONResponse(
        status_code=error.status,
        content=problem_from_error(error, instance),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )
