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
    return {"$ref": f"#/components/schemas/{name}"}


def accepts(name: str) -> dict[str, Any]:
    return {"required": True, "content": {JSON: {"schema": _ref(name)}}}


def answered_with(name: str, description: str) -> dict[str, Any]:
    return {"description": description, "content": {JSON: {"schema": _ref(name)}}}


def failing_with(*statuses: str) -> dict[str, Any]:
    return {
        status: {
            "description": _FAILURES[status],
            "content": {PROBLEM_MEDIA_TYPE: {"schema": _ref("Problem")}},
        }
        for status in statuses
    }


def _drop_pydantic_validation(document: dict[str, Any]) -> None:
    for path in document.get("paths", {}).values():
        for operation in path.values():
            operation.get("responses", {}).pop("422", None)
    schemas = document.get("components", {}).get("schemas", {})
    for name in _PYDANTIC_VALIDATION_SCHEMAS:
        schemas.pop(name, None)


def _require_the_checksum(document: dict[str, Any]) -> None:
    for path in document.get("paths", {}).values():
        for operation in path.values():
            for parameter in operation.get("parameters", []):
                if parameter["name"] == "checksum":
                    parameter["required"] = True
                    parameter["schema"] = {"type": "string", "minLength": 1}


def publish(app: FastAPI) -> None:
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
