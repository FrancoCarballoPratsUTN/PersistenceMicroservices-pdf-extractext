"""La pila de middleware HTTP (T15).

Dónde se coloca cada pieza se decide una sola vez, en :func:`app.main.create_app`, y
sigue el orden de SPEC 3.3: el rechazo más barato ocurre primero, así que un
llamador no autenticado nunca tiene un cuerpo analizado ni medido en su nombre.

Dos reglas merecen enunciarse aquí porque parecen excepciones:

CORS es el más externo
    Un preflight del navegador no lleva credenciales por diseño, así que
    responderlo fuera de la comprobación del token es lo que lo hace funcionar
    siquiera. No cuesta nada en seguridad: una petición real sigue cruzando la
    comprobación del token, y ``CORSMiddleware`` solo añade cabeceras a las
    respuestas que deja pasar.

El límite del cuerpo lee ``Content-Length``, nunca el cuerpo
    La cabecera es lo que el llamador ya declaró, así que el rechazo no cuesta
    nada y una subida enorme nunca se lee en memoria. Un valor ausente o mal
    formado cuenta como cero en lugar de lanzar: una cabecera no vale un ``500``.
"""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.problem import instance_of, problem_response
from app.config import Settings
from app.errors import PayloadTooLargeError, UnsupportedMediaTypeError

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
JSON_MEDIA_TYPE = "application/json"
BODY_METHODS = frozenset({"POST", "PUT"})
CORS_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]


def _is_json(header: str | None) -> bool:
    """Dice si una cabecera Content-Type declara JSON, parámetros incluidos."""
    if header is None:
        return False
    return header.split(";")[0].strip().lower() == JSON_MEDIA_TYPE


def _declared_length(request: Request) -> int:
    """Devuelve el Content-Length que declaró el llamador, o 0 si no es usable."""
    raw = request.headers.get("content-length", "")
    return int(raw) if raw.isdigit() else 0


class ContentTypeMiddleware(BaseHTTPMiddleware):
    """Exige ``application/json`` en los dos verbos que llevan cuerpo.

    Args:
        app: El siguiente manejador de la cadena.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Rechaza la petición, o la pasa.

        Args:
            request: La petición entrante.
            call_next: El resto de la cadena.

        Returns:
            Un ``415`` cuando el verbo lleva un cuerpo que no es JSON; en caso
            contrario, lo que responda el resto de la cadena.
        """
        if request.method in BODY_METHODS and not _is_json(
            request.headers.get("content-type")
        ):
            return problem_response(UnsupportedMediaTypeError(), instance_of(request))
        return await call_next(request)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rechaza un cuerpo mayor que el límite configurado.

    Args:
        app: El siguiente manejador de la cadena.
        settings: Aporta el límite en bytes.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._limit = settings.max_text_body_bytes

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Rechaza un cuerpo demasiado grande, o pasa la petición.

        Args:
            request: La petición entrante.
            call_next: El resto de la cadena.

        Returns:
            Un ``413`` cuando el cuerpo declarado supera el límite; en caso
            contrario, lo que responda el resto de la cadena.
        """
        if _declared_length(request) > self._limit:
            return problem_response(PayloadTooLargeError(), instance_of(request))
        return await call_next(request)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Devuelve el ``X-Request-ID`` del llamador o inventa uno, y lo registra.

    La cabecera también va en los rechazos: una petición rechazada es exactamente
    la que alguien vendrá a buscar cuando rastree algo.

    Args:
        app: El siguiente manejador de la cadena.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Marca la petición, la responde, y marca la respuesta.

        Args:
            request: La petición entrante.
            call_next: El resto de la cadena.

        Returns:
            La respuesta con una cabecera ``X-Request-ID``.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        logger.info("request_id=%s %s %s", request_id, request.method, request.url.path)

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Registra una línea por petición: método, ruta, estado y duración.

    Args:
        app: El siguiente manejador de la cadena.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Responde a la petición y registra cómo ha ido.

        Args:
            request: La petición entrante.
            call_next: El resto de la cadena.

        Returns:
            Lo que respondió el resto de la cadena.
        """
        started = perf_counter()
        response = await call_next(request)
        elapsed_ms = (perf_counter() - started) * 1000
        logger.info(
            "%s %s %d %.1f ms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
