"""El contrato de cable, escrito una vez (T18).

SPEC 2.3 mantuvo Pydantic fuera del contrato, y el precio fueron ~55 lineas de
schemas escritos a mano en ``app/api/schemas.py`` -- dicts que nadie derivaba de
las reglas que el servicio aplica de verdad. Estos tests sostienen los modelos que
los sustituyeron.

Que se afirma aqui
------------------
* cada modelo publica exactamente los miembros obligatorios que promete, y en
  orden,
* las reglas que aplica el servicio estan *publicadas*: un ``text`` y un
  ``checksum`` no vacios, ``metadata`` de forma libre, marcas de tiempo RFC 3339,
* ningun schema lleva el ``title`` que Pydantic inventa por propiedad. El
  componente ya tiene nombre; repetirlo es ruido en ``/docs``,
* la descripcion publicada es la que pasa el llamante, nunca el docstring. Estos
  docstrings son de estilo Google con bloques ``Args:``, y en ``/docs`` eso se lee
  como ruido,
* ``min_length=1`` es una regla, y un checksum sigue siendo una cadena opaca: SPEC
  Q1 nunca pidio validacion de formato, y Pydantic no debe empezar a inventarla.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.api.models import (
    AcknowledgementOut,
    CreateTextBody,
    ProbeOut,
    TextOut,
    UpdateTextBody,
    schema_of,
)

MODELS = [
    (CreateTextBody, "The text to store."),
    (UpdateTextBody, "What to change."),
    (TextOut, "A stored text, as GET and PUT answer it."),
    (AcknowledgementOut, "What POST and DELETE answer with."),
    (ProbeOut, "What the probes answer with."),
]


def _keys(node: Any) -> set[str]:
    """Devuelve cada clave de objeto que aparece en algun punto de un schema.

    Recorre dicts y listas, de modo que tambien encuentra un ``title`` escondido
    dentro de una rama de ``anyOf``, no solo el que esta en la cima de una
    propiedad.
    """
    if isinstance(node, dict):
        return set(node) | {key for value in node.values() for key in _keys(value)}
    if isinstance(node, list):
        return {key for value in node for key in _keys(value)}
    return set()


def test_the_create_body_requires_exactly_the_text_and_the_checksum() -> None:
    schema = schema_of(CreateTextBody, "The text to store.")

    assert schema["required"] == ["text", "checksum"]


def test_neither_required_string_may_be_empty() -> None:
    """Un ``_id`` vacio seria un documento al que ninguna peticion podria volver
    a llegar."""
    properties = schema_of(CreateTextBody, "The text to store.")["properties"]

    assert properties["text"]["minLength"] == 1
    assert properties["checksum"]["minLength"] == 1


def test_the_checksum_is_published_as_never_format_validated() -> None:
    """SPEC Q1 y la tabla de riesgos de la seccion 10 prometen ambos esto."""
    properties = schema_of(CreateTextBody, "The text to store.")["properties"]

    assert properties["checksum"]["description"] == "Never format-validated."


def test_metadata_is_published_as_a_free_object() -> None:
    """Un campo opcional se publica como ``anyOf: [object, null]``.

    Este es el unico cambio de forma que la tarea declara en sus diffs de cable: un
    ``metadata`` con ``null`` es legal, asi que el documento lo dice en vez de
    afirmar que es un objeto simple.
    """
    metadata = schema_of(CreateTextBody, "The text to store.")["properties"]["metadata"]

    assert metadata["anyOf"][0] == {"type": "object", "additionalProperties": True}
    assert metadata["anyOf"][1] == {"type": "null"}


def test_the_update_body_requires_nothing() -> None:
    """Ausente significa *no enviado* (SPEC 4.3), asi que ningun miembro es
    obligatorio."""
    assert "required" not in schema_of(UpdateTextBody, "What to change.")


def test_a_stored_text_publishes_all_six_members_it_promises() -> None:
    """El cliente de Go decodifica seis por nombre y lee como vacio al que falte."""
    schema = schema_of(TextOut, "A stored text, as GET and PUT answer it.")

    assert schema["required"] == [
        "checksum",
        "text",
        "name",
        "metadata",
        "created_at",
        "updated_at",
    ]


def test_the_stored_text_publishes_its_timestamps_as_rfc_3339() -> None:
    properties = schema_of(TextOut, "A stored text.")["properties"]

    assert properties["created_at"]["type"] == "string"
    assert properties["created_at"]["format"] == "date-time"


def test_the_acknowledgement_names_what_happened_and_to_what() -> None:
    schema = schema_of(AcknowledgementOut, "What POST and DELETE answer with.")

    assert schema["required"] == ["message", "checksum"]


def test_the_probe_requires_only_its_status() -> None:
    """``mongo`` es el miembro extra de la segunda sonda, asi que no puede ser
    obligatorio."""
    schema = schema_of(ProbeOut, "What the probes answer with.")

    assert schema["required"] == ["status"]


def test_a_stored_text_repeats_that_its_checksum_is_never_format_validated() -> None:
    """La regla va sobre el checksum, asi que se publica donde aparezca.

    Antes se publicaba tanto en ``CreateText`` como en ``Text``; declararla solo en
    un modelo la eliminaria en silencio del otro.
    """
    properties = schema_of(TextOut, "A stored text.")["properties"]

    assert properties["checksum"]["description"] == "Never format-validated."


def test_the_acknowledgement_publishes_the_message_it_always_sends() -> None:
    """Un ejemplo es lo que le dice a un cliente que lee ``/docs`` que esperar."""
    properties = schema_of(AcknowledgementOut, "What POST and DELETE answer with.")[
        "properties"
    ]

    assert properties["message"]["examples"] == ["OK"]


def test_the_probe_publishes_the_statuses_it_uses() -> None:
    properties = schema_of(ProbeOut, "What the probes answer with.")["properties"]

    assert properties["status"]["examples"] == ["ok"]
    assert properties["mongo"]["examples"] == ["ok"]


@pytest.mark.parametrize(("model", "description"), MODELS)
def test_no_published_schema_carries_a_title(
    model: type[BaseModel], description: str
) -> None:
    assert "title" not in _keys(schema_of(model, description))


def test_the_description_is_the_one_the_caller_passes_not_the_docstring() -> None:
    schema = schema_of(ProbeOut, "What the probes answer with.")

    assert schema["description"] == "What the probes answer with."
    assert "Args:" not in json.dumps(schema)


@pytest.mark.parametrize("field", ["text", "checksum"])
def test_a_number_is_not_accepted_where_a_string_is_required(field: str) -> None:
    """Pydantic en modo laxo convierte muchas cosas; esta no debe convertirla.

    Si una version futura o un cambio en ``model_config`` empieza a aceptar ``12``
    como checksum, el ``_id`` de MongoDB deja de ser la cadena que envio el
    llamante.
    """
    body = {"text": "t", "checksum": "c", field: 12}

    with pytest.raises(PydanticValidationError):
        CreateTextBody.model_validate(body)


def test_a_checksum_of_any_shape_is_accepted() -> None:
    """SPEC Q1: el checksum es una cadena opaca, nunca validada por formato."""
    body = CreateTextBody.model_validate({"text": "t", "checksum": "not-a-digest!"})

    assert body.checksum == "not-a-digest!"
