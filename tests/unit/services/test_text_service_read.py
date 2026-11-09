"""Tests de TextService.find_by_checksum."""

from __future__ import annotations

import pytest

from app.errors import TextNotFoundError
from tests.unit.services.conftest import _command, _service, NOW
from tests.fakes.fake_text_repository import FakeTextRepository


async def test_the_stored_text_is_returned_when_the_checksum_exists() -> None:
    repository = FakeTextRepository()
    await _service(repository).create(_command(name="contrato.pdf"))

    found = await _service(repository).find_by_checksum("abc123")

    assert found.checksum == "abc123"
    assert found.text == "hello"
    assert found.name == "contrato.pdf"
    assert found.created_at == NOW


async def test_an_unknown_checksum_is_reported_as_not_found() -> None:
    with pytest.raises(TextNotFoundError):
        await _service(FakeTextRepository()).find_by_checksum("missing")
