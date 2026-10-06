"""El guardia entre Pydantic y el vocabulario de errores de este servicio (T18).

``checked`` es el unico sitio donde un ``pydantic.ValidationError`` se convierte
en un ``app.errors.ValidationError``. Lo que importa ahi es el ``detail`` que lee
el cliente: se construye con los nombres de campo *nuestros*, nunca con la prosa
en ingles de Pydantic, porque el ``detail`` de RFC 9457 forma parte del contrato
de cable y no debe moverse al actualizar la biblioteca.
"""

from __future__ import annotations

import pytest

from app.api.models import CreateTextBody
from app.api.validators.common import checked, require_str
from app.errors import ValidationError


def test_require_str_ok() -> None:
    assert require_str("hello") == "hello"


def test_require_str_empty_raises() -> None:
    with pytest.raises(ValidationError):
        require_str("")


def test_a_body_that_is_not_an_object_says_the_body_is_invalid() -> None:
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, [1, 2])

    assert caught.value.detail == "invalid body"


def test_a_missing_checksum_names_the_checksum() -> None:
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, {"text": "t"})

    assert caught.value.detail == "invalid checksum"


def test_an_empty_text_names_the_text() -> None:
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, {"text": "", "checksum": "c"})

    assert caught.value.detail == "invalid text"


def test_metadata_that_is_not_an_object_names_the_metadata() -> None:
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, {"text": "t", "checksum": "c", "metadata": []})

    assert caught.value.detail == "invalid metadata"


def test_a_name_of_the_wrong_type_names_the_name() -> None:
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, {"text": "t", "checksum": "c", "name": 5})

    assert caught.value.detail == "invalid name"


def test_the_first_offending_field_is_the_one_reported() -> None:
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, {"text": 12, "checksum": "c"})

    assert caught.value.detail == "invalid text"


def test_the_detail_never_carries_pydantics_own_wording() -> None:
    """Una actualizacion de la biblioteca no debe poder reescribir el contrato."""
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, {"text": "", "checksum": "c"})

    assert "at least" not in str(caught.value)


def test_a_key_pydantic_cannot_name_still_names_the_field_it_belongs_to() -> None:
    """Un rechazo a varios niveles informa de nuestro campo, no del camino de
    Pydantic.

    Una clave int dentro de ``metadata`` se rechaza en ``('metadata', 1, '[key]')``.
    El detail debe nombrar ``metadata`` -- el miembro que escribio el cliente --
    en vez de representar un camino para el que no tenemos vocabulario.
    """
    with pytest.raises(ValidationError) as caught:
        checked(CreateTextBody, {"text": "t", "checksum": "c", "metadata": {1: "x"}})

    assert caught.value.detail == "invalid metadata"


def test_a_body_of_the_wrong_json_type_still_says_the_body_is_invalid() -> None:
    """Un escalar o ``null`` no es un mapeo, asi que se lee como cualquier otro
    no-objeto."""
    for raw in ("hola", 7, None):
        with pytest.raises(ValidationError) as caught:
            checked(CreateTextBody, raw)

        assert caught.value.detail == "invalid body"


def test_a_field_the_model_does_not_declare_is_ignored_rather_than_refused() -> None:
    """Anadir un miembro al DTO del orquestador no debe empezar a fallar con 400.

    SPEC 2.3 lee ``name`` y ``metadata`` como siempre presentes, con ``null`` cuando
    faltan. Un cliente que empiece a enviar mas que eso debe seguir funcionando,
    y por eso ``extra`` se queda en el ``ignore`` por defecto de Pydantic
    (D-T18.4).
    """
    body = checked(
        CreateTextBody,
        {"text": "t", "checksum": "c", "page_count": 12},
    )

    assert body.checksum == "c"
    assert not hasattr(body, "page_count")


def test_a_valid_body_comes_back_as_the_model() -> None:
    body = checked(CreateTextBody, {"text": "t", "checksum": "c", "name": "n.pdf"})

    assert body.name == "n.pdf"
    assert body.metadata is None
