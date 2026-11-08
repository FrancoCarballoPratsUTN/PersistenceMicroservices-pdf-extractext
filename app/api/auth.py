import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.api.problem import instance_of, problem_response
from app.config import Settings
from app.errors import UnauthorizedError

logger = logging.getLogger(__name__)

BEARER_SCHEME = "Bearer"

# Las sondas de la plataforma no pueden llevar credenciales (SPEC 3.1), así que
# estas dos quedan abiertas. Cualquier otra ruta, presente o futura, está protegida.
PUBLIC_PATHS = frozenset({"/health", "/readyz"})

REJECTION_DETAIL = "Missing or invalid bearer token."


def rejection_reason(header: str | None, expected_token: str) -> str | None:
    """Explica por qué una credencial no es aceptable, en palabras seguras para el log.

    Args:
        header: La cabecera ``Authorization`` tal cual, o ``None`` cuando quien
            llama no envió ninguna.
        expected_token: El token configurado.

    Returns:
        ``None`` cuando la credencial es válida; en caso contrario, una frase
        breve que nombre el paso que falló. El valor presentado nunca aparece en
        ella.
    """
    if header is None:
        return "missing header"
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != BEARER_SCHEME.lower():
        return "unexpected scheme"
    presented = credentials.strip()
    if not presented:
        return "missing credentials"
    if not secrets.compare_digest(
        presented.encode("utf-8"), expected_token.encode("utf-8")
    ):
        return "token mismatch"
    return None


def unauthorized_response(request: Request) -> Response:
    """Devuelve el rechazo con el que responde todo modo de fallo.

    Args:
        request: La petición a la que se responde.

    Returns:
        Un documento problem con el desafío ``WWW-Authenticate`` de RFC 6750,
        para que quien llama sepa con qué esquema debe reintentar.
    """
    return problem_response(
        UnauthorizedError(REJECTION_DETAIL),
        instance_of(request),
        headers={"WWW-Authenticate": BEARER_SCHEME},
    )


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
