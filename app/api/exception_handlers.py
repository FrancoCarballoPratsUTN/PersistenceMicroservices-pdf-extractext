"""Manejadores de excepciones: el único sitio donde una excepción se vuelve HTTP.

La Capa 1 es la dueña de esa traducción (SPEC 2.2), así que todo fallo que este
servicio puede producir sale del proceso como ``application/problem+json``. Tres
manejadores lo hacen exhaustivo: nuestros propios errores, los errores de
enrutamiento que Starlette lanza por su cuenta, y cualquier cosa imprevista.

El texto del framework nunca se repite
--------------------------------------
Una ``StarletteHTTPException`` lleva un mensaje humano elegido por el framework, o
por quien la lanzó. Nada de ese texto es nuestro para repetirlo, así que las
clases mapeadas aportan su propio ``default_detail`` y el que lo atrapa todo
aporta una fija. La excepción real llega al log del servidor, que el cliente no
puede leer.
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

logger = logging.getLogger(__name__)

# Los únicos dos estados que Starlette lanza por su cuenta: ninguna ruta coincidió
# con la URL (404), o la ruta no acepta el verbo (405). Cualquier otro fallo lo
# lanza como ServiceError la capa que lo detectó.
_ROUTING_ERRORS: dict[int, type[ServiceError]] = {
    404: ResourceNotFoundError,
    405: MethodNotAllowedError,
}


async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    """Responde a un error de dominio con el estado y el documento que define su clase.

    Args:
        request: La petición a la que se responde.
        exc: El error lanzado por la capa que detectó el fallo.

    Returns:
        La respuesta problem para ``exc``.
    """
    return problem_response(exc, instance_of(request))


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Responde a un error HTTP del framework como detalles de problema.

    Un estado que ninguna clase de error modela se reporta con fidelidad, con un
    título genérico en lugar de obligarlo a meterse en una clase vecina: responder
    418 como si fuera un 404 sería una mentira peor que un documento inespecífico.

    Args:
        request: La petición a la que se responde.
        exc: El error lanzado por el framework.

    Returns:
        Una respuesta problem, tenga o no el estado su propia clase.
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
    """Responde a una excepción imprevista con un 500 y conserva la causa real.

    Args:
        request: La petición a la que se responde.
        exc: La excepción que ninguna capa anticipó.

    Returns:
        Un problem 500 genérico; el texto de la excepción va al log, no al cliente.
    """
    logger.error("Unhandled error while handling %s", request.url.path, exc_info=exc)
    return problem_response(InternalError(), instance_of(request))


def register_exception_handlers(app: Starlette) -> None:
    """Instala los tres manejadores en ``app``.

    Args:
        app: La aplicación que proteger. La raíz de composición de ``app/main.py``
            llama a esto antes de que la aplicación empiece a atender peticiones.
    """
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
