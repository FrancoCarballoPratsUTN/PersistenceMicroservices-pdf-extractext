"""Tests del validador update_text (T13).

La tabla de SPEC 4.3 es todo el contrato: *ausente* significa *no enviado*, y un
cuerpo vacio es un no-op que se rechaza en vez de aceptarse en silencio.
"""

from __future__ import annotations

import pytest

from app.api.validators.update_text import validate
from app.errors import ImmutableFieldError, ValidationError
from app.use_cases.ports import TextChanges


def test_a_name_is_overwritten_when_it_is_sent() -> None:
    assert validate({"name": "nuevo.pdf"}) == TextChanges(name="nuevo.pdf")


def test_an_empty_name_is_overwritten_too() -> None:
    assert validate({"name": ""}) == TextChanges(name="")


def test_an_absent_name_leaves_it_unchanged() -> None:
    assert validate({"metadata": {"pages": 1}}) == TextChanges(metadata={"pages": 1})


def test_a_null_name_leaves_it_unchanged() -> None:
    assert validate({"name": None, "metadata": {"pages": 1}}) == TextChanges(
        metadata={"pages": 1}
    )


def test_metadata_present_as_an_object_replaces_it_whole() -> None:
    changes = validate({"metadata": {"pages": 2}})

    assert changes.metadata == {"pages": 2}


def test_an_empty_metadata_object_is_a_real_change() -> None:
    """``{}`` limpia el metadata; no es lo mismo que dejarlo como estaba."""
    assert validate({"metadata": {}}).metadata == {}


def test_a_null_metadata_leaves_it_unchanged() -> None:
    assert validate({"metadata": None, "name": "n.pdf"}) == TextChanges(name="n.pdf")


def test_both_fields_travel_together() -> None:
    assert validate({"name": "n.pdf", "metadata": {"pages": 3}}) == TextChanges(
        name="n.pdf", metadata={"pages": 3}
    )


def test_a_text_in_the_body_is_refused_as_immutable() -> None:
    with pytest.raises(ImmutableFieldError):
        validate({"text": "otro texto"})


def test_a_checksum_in_the_body_is_refused_as_immutable() -> None:
    with pytest.raises(ImmutableFieldError):
        validate({"checksum": "otro", "name": "n.pdf"})


@pytest.mark.parametrize("metadata", ["pages", 12, ["a"]])
def test_metadata_that_is_not_an_object_is_refused(metadata: object) -> None:
    with pytest.raises(ValidationError):
        validate({"metadata": metadata})


def test_a_name_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(ValidationError):
        validate({"name": 7})


def test_an_empty_body_is_refused() -> None:
    with pytest.raises(ValidationError):
        validate({})


def test_a_body_of_only_nulls_is_refused_as_a_no_op() -> None:
    with pytest.raises(ValidationError):
        validate({"name": None, "metadata": None})


def test_a_body_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValidationError):
        validate(["name"])


def test_an_unknown_field_is_ignored() -> None:
    """Solo ``name`` y ``metadata`` son nuestros; el resto no es asunto nuestro."""
    assert validate({"pages": 12, "name": "n.pdf"}) == TextChanges(name="n.pdf")


def test_an_empty_body_is_refused_as_a_no_op() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({})

    assert caught.value.detail == "no changes requested"


def test_a_text_in_the_body_wins_over_a_name_of_the_wrong_type() -> None:
    """La regla estructural se comprueba primero, asi que un ``text`` nunca pasa
    desapercibido."""
    with pytest.raises(ImmutableFieldError):
        validate({"text": "otro", "name": 5})


def test_a_name_of_the_wrong_type_names_the_name() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({"name": 7})

    assert caught.value.detail == "invalid name"


def test_metadata_that_is_not_an_object_names_the_metadata() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({"metadata": "nope"})

    assert caught.value.detail == "invalid metadata"


def test_a_body_that_is_not_an_object_says_the_body_is_invalid() -> None:
    with pytest.raises(ValidationError) as caught:
        validate(["name"])

    assert caught.value.detail == "invalid body"
