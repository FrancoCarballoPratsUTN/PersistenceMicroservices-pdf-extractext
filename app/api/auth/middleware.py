"""Middleware de autenticación Bearer."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.auth.tokens import PUBLIC_PATHS, rejection_reason, unauthorized_response
from app.config import Settings

logger = logging.getLogger(__name__)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Exige un token Bearer válido en toda ruta fuera de :data:`PUBLIC_PATHS`.

    Se registra como el middleware más externo para que un cuerpo no autenticado
    nunca sea analizado, medido ni enrutado: rechazar primero es también la forma
    más barata de rechazar, y evita que la respuesta revele qué rutas existen.

    Args:
        app: El siguiente manejador de la cadena.
        settings: Aporta el token con el que comparar.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        """Guarda el siguiente manejador y el token de autenticación.

        Args:
            app: El siguiente manejador de la cadena.
            settings: Aporta el token con el que comparar.

        Returns:
            Ninguno.
        """
        super().__init__(app)
        self._token = settings.service_api_token

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Rechaza la petición, o la pasa al resto de la cadena.

        Args:
            request: La petición entrante.
            call_next: El resto de la cadena.

        Returns:
            Un ``401`` cuando la credencial no es aceptable; en caso contrario,
            lo que responda el resto de la cadena.
        """
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        reason = rejection_reason(request.headers.get("Authorization"), self._token)
        if reason is not None:
            # Solo la ruta, nunca la cadena de consulta: ahí viaja el checksum,
            # y esta línea la lee quien vigila los logs.
            logger.warning(
                "Refused %s %s: %s", request.method, request.url.path, reason
            )
            return unauthorized_response(request)

        return await call_next(request)
