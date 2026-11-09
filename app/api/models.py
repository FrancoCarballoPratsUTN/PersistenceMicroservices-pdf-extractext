"""Modelos Pydantic de la API: cuerpos de petición y respuestas serializadas.

Define CreateTextBody, UpdateTextBody, TextOut, AcknowledgementOut y ProbeOut,
junto con el helper schema_of para generar esquemas OpenAPI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateTextBody(BaseModel):
    text: str = Field(min_length=1, description="The extracted text.")
    checksum: str = Field(min_length=1, description="Never format-validated.")
    name: str | None = None
    metadata: dict[str, Any] | None = None


class UpdateTextBody(BaseModel):
    name: str | None = None
    metadata: dict[str, Any] | None = None


class TextOut(BaseModel):
    checksum: str = Field(description="Never format-validated.")
    text: str
    name: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AcknowledgementOut(BaseModel):
    message: str = Field(examples=["OK"])
    checksum: str


class ProbeOut(BaseModel):
    status: str = Field(examples=["ok"])
    mongo: str | None = Field(default=None, examples=["ok"])


def schema_of[ModelT: BaseModel](
    model: type[ModelT], description: str
) -> dict[str, Any]:
    """Construye el esquema OpenAPI de un modelo Pydantic sin título.

    Args:
        model: Clase del modelo Pydantic.
        description: Descripción del esquema en la API.

    Returns:
        Diccionario con el esquema OpenAPI y su descripción.
    """
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    return {"description": description, **_untitled(schema)}


def _untitled(node: Any) -> Any:
    """Elimina recursivamente las claves ``title`` de un esquema OpenAPI.

    Args:
        node: Nodo del esquema (diccionario, lista o valor escalar).

    Returns:
        El nodo sin claves ``title``.
    """
    if isinstance(node, dict):
        return {key: _untitled(value) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [_untitled(value) for value in node]
    return node
