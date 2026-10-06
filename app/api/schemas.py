"""El documento OpenAPI: mitad derivado, mitad escrito a mano (T17, T18).

FastAPI publica un ``{}`` vacío para cada body, porque ninguna ruta declara un
modelo en su firma del que leer un esquema. Este módulo aporta la mitad que
falta, y lo hace de dos maneras distintas a propósito.

Derivado, no transcrito
-----------------------
Cinco de los seis componentes salen de :func:`app.api.models.schema_of`, aplicada
a los modelos de :mod:`app.api.models`. Eso es justo lo que busca T18: las reglas
que aplica el servicio y la descripción de esas reglas son la misma declaración,
así que el documento no puede alejarse del comportamiento que documenta.

``Problem`` es la excepción, y tiene que serlo. Su enumeración de ``code`` se lee
de :mod:`app.errors` en tiempo de ejecución, y ningún tipo estático puede
derivarse de una introspección en runtime. Sigue escrito a mano, y
``tests/integration/api/test_openapi.py`` compara su ``enum`` con el vocabulario
de errores, así que tampoco puede separarse de :mod:`app.errors`.

Las tres cosas que FastAPI hace mal
-----------------------------------
No publica componentes, porque no tiene un modelo del que leerlos y el
``openapi_extra`` que acepta su constructor nunca se mezcla. Inventa un ``422``
para el query param ``checksum``, al que este servicio responde con
``400 VALIDATION_ERROR`` en su lugar (SPEC 2.3). Y llama opcional a ese
parámetro, porque la ruta lo declara opcional para poder leerlo y rechazarlo a
mano.

Ninguna de las tres se puede arreglar desde el ``openapi_extra`` de una ruta: la
fusión añade claves, no puede quitar una, y concatena listas en vez de
reemplazarlas. Así que se corrigen sobre el documento ya terminado, en
:func:`publish`. También sobreviven a T18: los bodies de la petición los validan
las rutas y no FastAPI, precisamente para que nunca se produzca un ``422``.
"""

from typing import Any

from fastapi import FastAPI

from app.api.models import (
    AcknowledgementOut,
    CreateTextBody,
    ProbeOut,
    TextOut,
    UpdateTextBody,
    schema_of,
)
from app.api.problem import PROBLEM_MEDIA_TYPE
from app.errors import ServiceError

BEARER = "bearerAuth"
JSON = "application/json"

SECURITY: list[dict[str, list[str]]] = [{BEARER: []}]


def _codes() -> list[str]:
    """Devuelve todos los codes que define el vocabulario de errores.

    Todas las clases de :mod:`app.errors` derivan directamente de
    ``ServiceError``, así que sus subclases son todo el vocabulario. Una subclase
    anidada tendría que añadirse a la matriz de SPEC 6.2, y la guarda de
    ``tests/integration/api/test_openapi.py`` compara las dos listas.

    Returns:
        Los codes, ordenados para que el documento publicado sea estable.
    """
    return sorted(error.code for error in ServiceError.__subclasses__())


_TEXT = schema_of(TextOut, "A stored text, as GET and PUT answer it.")

_CREATE_TEXT = schema_of(CreateTextBody, "The text to store.")

_UPDATE_TEXT = schema_of(
    UpdateTextBody,
    "What to change. A field left out does not change (SPEC 4.3), and a body "
    "asking for no change at all is refused.",
)

_ACKNOWLEDGEMENT = schema_of(AcknowledgementOut, "What POST and DELETE answer with.")

_PROBE = schema_of(ProbeOut, "What the probes answer with.")

# The one component written by hand: its `code` enumeration is read off
# app.errors at runtime, which no static model could carry (see the module
# docstring).
_PROBLEM = {
    "type": "object",
    "description": "Every failure, as RFC 9457 defines it plus a `code`.",
    "required": ["type", "title", "status", "detail", "instance", "code"],
    "properties": {
        "type": {"type": "string", "format": "uri-reference"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string"},
        "code": {"type": "string", "enum": _codes()},
    },
}

COMPONENTS = {
    "securitySchemes": {
        BEARER: {
            "type": "http",
            "scheme": "bearer",
            "description": "Shared secret sent on every request but the probes.",
        }
    },
    "schemas": {
        "Text": _TEXT,
        "CreateText": _CREATE_TEXT,
        "UpdateText": _UPDATE_TEXT,
        "Acknowledgement": _ACKNOWLEDGEMENT,
        "Probe": _PROBE,
        "Problem": _PROBLEM,
    },
}

_FAILURES = {
    "400": (
        "Malformed body, a wrong field type, a missing required field, a missing "
        "checksum, or a field that cannot be changed."
    ),
    "401": "The bearer token is absent, malformed, or not the configured one.",
    "404": "No document holds that checksum, or the route does not exist.",
    "405": "The route does not accept this verb.",
    "409": "A document with that checksum is already stored.",
    "413": "The body is larger than MAX_TEXT_BODY_BYTES.",
    "415": "The Content-Type is not application/json.",
    "500": "An exception no layer anticipated.",
    "503": "MongoDB is unreachable, or answered with an error.",
}

# The schemas FastAPI builds to describe a 422, which this service never sends.
_PYDANTIC_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def accepts(name: str) -> dict[str, Any]:
    """Devuelve el body de petición de un verbo, usando el componente indicado.

    Args:
        name: El esquema de componente que describe el body aceptado.

    Returns:
        Un body de petición obligatorio, como lo son los dos verbos que lo
        llevan.
    """
    return {"required": True, "content": {JSON: {"schema": _ref(name)}}}


def answered_with(name: str, description: str) -> dict[str, Any]:
    """Devuelve una respuesta de éxito usando el componente indicado.

    Args:
        name: El esquema de componente que describe el body de la respuesta.
        description: Qué significa la respuesta, para quien lea ``/docs``.

    Returns:
        Un objeto de respuesta para colgarlo del status al que pertenece.
    """
    return {"description": description, "content": {JSON: {"schema": _ref(name)}}}


def failing_with(*statuses: str) -> dict[str, Any]:
    """Devuelve las respuestas de documento problem para los status dados.

    Args:
        statuses: Los statuses con los que puede fallar este verbo, como cadenas.

    Returns:
        Un objeto de respuesta por status, cada uno un ``Problem`` bajo el tipo de
        medio problem.
    """
    return {
        status: {
            "description": _FAILURES[status],
            "content": {PROBLEM_MEDIA_TYPE: {"schema": _ref("Problem")}},
        }
        for status in statuses
    }


def _drop_pydantic_validation(document: dict[str, Any]) -> None:
    """Quita en el sitio lo que FastAPI inventó para describir un 422.

    ``HTTPValidationError`` y ``ValidationError`` son la forma que FastAPI da a un
    422. Una vez desaparecido el 422 inventado nada apunta a ellos, y el nombre
    ``ValidationError`` se lee como nuestro propio ``VALIDATION_ERROR``, cuyo
    documento es un problema y no una lista de errores de campo.

    Args:
        document: El documento que se está corrigiendo.
    """
    for path in document.get("paths", {}).values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)
    schemas = document.get("components", {}).get("schemas", {})
    for name in _PYDANTIC_VALIDATION_SCHEMAS:
        schemas.pop(name, None)


def _require_the_checksum(document: dict[str, Any]) -> None:
    """Dice que el checksum es obligatorio, cosa que la firma no puede expresar.

    La ruta declara ``checksum: str | None = None`` precisamente para poder
    rechazar un checksum ausente con ``400 VALIDATION_ERROR`` (SPEC 3.3). Leída
    como firma, eso también vuelve opcional el parámetro en el documento, justo
    al lado de un 400 que el servicio sí manda.

    Args:
        document: El documento que se está corrigiendo.
    """
    for path in document.get("paths", {}).values():
        for operation in path.values():
            for parameter in operation.get("parameters", []):
                if parameter["name"] == "checksum":
                    parameter["required"] = True
                    parameter["schema"] = {"type": "string", "minLength": 1}


def publish(app: FastAPI) -> None:
    """Hace que ``app`` sirva un documento que describa este servicio.

    Args:
        app: La aplicación a corregir. FastAPI cachea el documento que construye,
            así que esto va en la fábrica, antes de la primera petición.
    """
    generated = app.openapi

    def openapi() -> dict[str, Any]:
        document = generated()
        components = document.setdefault("components", {})
        components.setdefault("schemas", {}).update(COMPONENTS["schemas"])
        components["securitySchemes"] = COMPONENTS["securitySchemes"]
        _require_the_checksum(document)
        _drop_pydantic_validation(document)
        return document

    app.openapi = openapi
