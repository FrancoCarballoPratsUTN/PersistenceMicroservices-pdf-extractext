"""Tests del validador create_text (T10)."""

from __future__ import annotations

import pytest

from app.api.validators.create_text import validate
from app.errors import ValidationError
from app.use_cases.ports import CreateTextCommand


def test_a_complete_body_becomes_a_command() -> None:
    command = validate(
        {
            "checksum": "abc123",
            "text": "hello",
            "name": "contrato.pdf",
            "metadata": {"pages": 12},
        }
    )

    assert command == CreateTextCommand(
        checksum="abc123",
        text="hello",
        name="contrato.pdf",
        metadata={"pages": 12},
    )


def test_name_and_metadata_may_be_absent() -> None:
    command = validate({"checksum": "abc123", "text": "hello"})

    assert command.name is None
    assert command.metadata is None


@pytest.mark.parametrize("missing", ["checksum", "text"])
def test_a_missing_required_field_is_refused(missing: str) -> None:
    body = {"checksum": "abc123", "text": "hello"}
    del body[missing]

    with pytest.raises(ValidationError):
        validate(body)


def test_an_empty_checksum_is_refused() -> None:
    with pytest.raises(ValidationError):
        validate({"checksum": "", "text": "hello"})


def test_metadata_must_be_an_object() -> None:
    with pytest.raises(ValidationError):
        validate({"checksum": "abc123", "text": "hello", "metadata": "nope"})


def test_a_body_that_is_not_an_object_says_the_body_is_invalid() -> None:
    with pytest.raises(ValidationError) as caught:
        validate(["name"])

    assert caught.value.detail == "invalid body"


def test_a_missing_checksum_names_the_checksum() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({"text": "hello"})

    assert caught.value.detail == "invalid checksum"


def test_an_empty_checksum_names_the_checksum() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({"checksum": "", "text": "hello"})

    assert caught.value.detail == "invalid checksum"


def test_a_missing_text_names_the_text() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({"checksum": "abc123"})

    assert caught.value.detail == "invalid text"


def test_a_name_of_the_wrong_type_names_the_name() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({"checksum": "abc123", "text": "hello", "name": 5})

    assert caught.value.detail == "invalid name"


def test_metadata_that_is_not_an_object_names_the_metadata() -> None:
    with pytest.raises(ValidationError) as caught:
        validate({"checksum": "abc123", "text": "hello", "metadata": "nope"})

    assert caught.value.detail == "invalid metadata"
