"""Tests de TextService.update y delete."""

from __future__ import annotations

import pytest

from app.errors import TextNotFoundError
from app.use_cases.ports import TextChanges
from tests.unit.services.conftest import _command, _service, NOW
from tests.fakes.fake_text_repository import FakeTextRepository


async def test_the_updated_text_is_returned() -> None:
    repository = FakeTextRepository()
    await _service(repository).create(_command(name="contrato.pdf"))

    updated = await _service(repository).update("abc123", TextChanges(name="otro.pdf"))

    assert updated.name == "otro.pdf"
    assert updated.checksum == "abc123"
    assert updated.text == "hello"
    assert updated.created_at == NOW


async def test_an_update_of_metadata_leaves_the_name_alone() -> None:
    repository = FakeTextRepository()
    await _service(repository).create(_command(name="contrato.pdf"))

    updated = await _service(repository).update(
        "abc123", TextChanges(metadata={"pages": 12})
    )

    assert updated.metadata == {"pages": 12}
    assert updated.name == "contrato.pdf"


async def test_an_update_of_an_unknown_checksum_is_reported_as_not_found() -> None:
    with pytest.raises(TextNotFoundError):
        await _service(FakeTextRepository()).update(
            "missing", TextChanges(name="n.pdf")
        )


async def test_a_deleted_text_is_no_longer_readable() -> None:
    repository = FakeTextRepository()
    await _service(repository).create(_command())

    await _service(repository).delete("abc123")

    with pytest.raises(TextNotFoundError):
        await _service(repository).find_by_checksum("abc123")


async def test_deleting_an_unknown_checksum_is_reported_as_not_found() -> None:
    with pytest.raises(TextNotFoundError):
        await _service(FakeTextRepository()).delete("missing")


async def test_deleting_does_not_look_the_checksum_up_first() -> None:
    """La propia respuesta del repositorio es el veredicto: sin viaje extra antes."""
    repository = FakeTextRepository()
    await _service(repository).create(_command())
    lookups_before = repository.calls["checksum_exists"]

    await _service(repository).delete("abc123")

    assert repository.calls["checksum_exists"] == lookups_before
