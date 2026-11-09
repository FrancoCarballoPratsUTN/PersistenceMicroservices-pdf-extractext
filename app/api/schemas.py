"""Esquemas OpenAPI de la API: componentes, respuestas y cuerpos de petición.

Genera y publica los esquemas de OpenAPI (Text, CreateText, UpdateText,
Acknowledgement, Probe, Problem) junto con los códigos de error y los cuerpos
de respuesta Problem+JSON.
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
    """Recopila los códigos de error de todas las subclases de ServiceError.

    Returns:
        Lista ordenada de códigos de error únicos.
    """
    codes: set[str] = set()

    def add_subclass_codes(error_type: type[ServiceError]) -> None:
        for subclass in error_type.__subclasses__():
            codes.add(subclass.code)
            add_subclass_codes(subclass)

    add_subclass_codes(ServiceError)
    return sorted(codes)


_TEXT = schema_of(TextOut, "A stored text, as GET and PUT answer it.")

_CREATE_TEXT = schema_of(CreateTextBody, "The text to store.")

_UPDATE_TEXT = schema_of(
    UpdateTextBody,
    "What to change. A field left out does not change (SPEC 4.3), and a body "
    "asking for no change at all is refused.",
)

_ACKNOWLEDGEMENT = schema_of(AcknowledgementOut, "What POST and DELETE answer with.")

_PROBE = schema_of(ProbeOut, "What the probes answer with.")

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

_PYDANTIC_VALIDATION_SCHEMAS = ("HTTPValidationError", "ValidationError")


def _ref(name: str) -> dict[str, str]:
    """Construye una referencia OpenAPI a un esquema por nombre.

    Args:
        name: Nombre del esquema en ``components/schemas``.

    Returns:
        Diccionario de referencia ``$ref``.
    """
    return {"$ref": f"#/components/schemas/{name}"}


def accepts(name: str) -> dict[str, Any]:
    """Construye el cuerpo de petición requerido para un esquema dado.

    Args:
        name: Nombre del esquema del cuerpo de petición.

    Returns:
        Esquema de cuerpo de petición con el contenido JSON.
    """
    return {"required": True, "content": {JSON: {"schema": _ref(name)}}}


def answered_with(name: str, description: str) -> dict[str, Any]:
    """Construye la descripción de una respuesta exitosa para un esquema.

    Args:
        name: Nombre del esquema de respuesta.
        description: Descripción de la respuesta.

    Returns:
        Esquema de respuesta con el contenido JSON.
    """
    return {"description": description, "content": {JSON: {"schema": _ref(name)}}}


def failing_with(*statuses: str) -> dict[str, Any]:
    """Construye las descripciones de respuestas de error para varios estados.

    Args:
        *statuses: Códigos de estado HTTP de las respuestas de error.

    Returns:
        Diccionario con las respuestas de error claveadas por código de estado.
    """
    return {
        status: {
            "description": _FAILURES[status],
            "content": {PROBLEM_MEDIA_TYPE: {"schema": _ref("Problem")}},
        }
        for status in statuses
    }


def _drop_pydantic_validation(document: dict[str, Any]) -> None:
    """Elimina los esquemas de validación de Pydantic del documento OpenAPI.

    Args:
        document: Documento OpenAPI generado por FastAPI.

    Returns:
        Ninguno.
    """
    for path in document.get("paths", {}).values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)
    schemas = document.get("components", {}).get("schemas", {})
    for name in _PYDANTIC_VALIDATION_SCHEMAS:
        schemas.pop(name, None)


def _require_the_checksum(document: dict[str, Any]) -> None:
    """Marca como obligatorio el parámetro ``checksum`` en todas las operaciones.

    Args:
        document: Documento OpenAPI generado por FastAPI.

    Returns:
        Ninguno.
    """
    for path in document.get("paths", {}).values():
        for operation in path.values():
            for parameter in operation.get("parameters", []):
                if parameter["name"] == "checksum":
                    parameter["required"] = True
                    parameter["schema"] = {"type": "string", "minLength": 1}


def publish(app: FastAPI) -> None:
    """Publica los esquemas personalizados en el OpenAPI de la aplicación.

    Args:
        app: Instancia de la aplicación FastAPI.

    Returns:
        Ninguno.
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
