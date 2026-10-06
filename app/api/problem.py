"""Documentos problem de RFC 9457, construidos como dicts simples.

La única regla dura que impone el orquestador es que cualquier ``status >= 300``
vuelve con un cuerpo que sabe analizar como problem
(``internal/httpclient/client.go:39``). Este módulo es el dueño de la forma de ese
cuerpo: los cinco miembros canónicos de RFC 9457 3.1 más ``code``, la extensión
legible por máquina de 3.2.

Por qué un dict y no un modelo
------------------------------
Pydantic es el contrato de cable en el resto de ``app/api`` (SPEC 2.3), y un cuerpo
problem es deliberadamente parte de él. Dos razones, y ninguna es que solo tenga
seis miembros planos.

``code`` es una enumeración leída de ``ServiceError.__subclasses__()`` en tiempo de
ejecución, así que ``Problem(BaseModel)`` no podría llevar un ``Literal`` suyo sin
enumerar cada código dos veces -- y enumerarlo dos veces es cómo un vocabulario
empieza a separarse de su propia fuente. ``detail`` también son datos de ejecución,
y un modelo lo validaría al salir, que no es un error que una ruta de fallo pueda
afrontar.

Así que ``Problem`` es el único componente de ``/openapi.json`` escrito a mano, y
``tests/integration/api/test_openapi.py`` compara su ``enum`` contra
``app.errors`` para que los dos no se separen.

De dónde vienen los valores
---------------------------
Cinco de los seis miembros son el contrato a nivel de clase de un
:class:`~app.errors.ServiceError`, definido una sola vez en ``app/errors.py``.
Solo ``detail`` varía en cada caso. Este módulo copia esos valores, nunca los
decide, así que hay exactamente un sitio donde se escribe un status, un ``type``
o un ``title``.

``instance`` conserva la ruta pero no los valores de la consulta
----------------------------------------------------------------
El checksum viaja como parámetro de consulta y las respuestas acaban en los logs
de los clientes que las leen. Nombrar el parámetro mientras se oculta su valor
mantiene un error rastreable (``/texts?checksum=<redacted>``) sin volver a publicar
el identificador, y omitir el host hace lo mismo con el despliegue.
"""

from collections.abc import Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse

from app.errors import ServiceError

PROBLEM_MEDIA_TYPE = "application/problem+json"
REDACTED = "<redacted>"


def instance_of(request: Request) -> str:
    """Devuelve la ruta de la petición junto con los nombres de sus parámetros.

    Args:
        request: La petición a la que se responde.

    Returns:
        La ruta pelada cuando no hay cadena de consulta; en caso contrario, la
        ruta más un par ``name=<redacted>`` por parámetro, en el orden en que
        llegaron.
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
    """Devuelve un documento problem con exactamente los seis miembros del contrato.

    Args:
        status: El código de estado HTTP, repetido en el cuerpo para que sea
            autosuficiente.
        type_uri: URI relativa estable que identifica la clase de problem.
        title: Resumen breve y sin variables de la clase de problem.
        detail: Explicación de este caso concreto.
        instance: La petición que lo disparó, tal como la construye
            :func:`instance_of`.
        code: Nombre estable y legible por máquina del problem.

    Returns:
        Un dict con los seis miembros y nada más.
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
    """Devuelve el documento problem que describe ``error`` en ``instance``.

    Args:
        error: El error de dominio que se reporta.
        instance: La petición a la que se responde.

    Returns:
        Los seis miembros, leídos de la clase de error y de este caso concreto.
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
    """Devuelve la respuesta que informa de ``error`` al cliente.

    Args:
        error: El error de dominio que se reporta.
        instance: La petición a la que se responde.
        headers: Cabeceras extra que exige el estado, como el desafío
            ``WWW-Authenticate`` que un 401 le debe a quien llama
            (RFC 9110 sección 15.5.2, RFC 6750 sección 3).

    Returns:
        Una respuesta JSON con el estado del error y el tipo de medio problem.
    """
    return JSONResponse(
        status_code=error.status,
        content=problem_from_error(error, instance),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )
