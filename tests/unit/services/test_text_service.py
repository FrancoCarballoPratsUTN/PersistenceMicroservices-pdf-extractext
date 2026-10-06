"""Tests de TextService.create, update y delete (T9, T10, T13, T14)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.errors import ChecksumAlreadyExistsError, PersistenceError, TextNotFoundError
from app.services.text_service import TextService
from app.use_cases.ports import CreateTextCommand, TextChanges
from tests.fakes.fake_text_repository import FakeTextRepository

NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)


def _service(repository: FakeTextRepository) -> TextService:
    return TextService(repository, now_factory=lambda: NOW)


def _command(**changes: Any) -> CreateTextCommand:
    fields: dict[str, Any] = {"checksum": "abc123", "text": "hello"}
    fields.update(changes)
    return CreateTextCommand(**fields)


async def test_a_new_text_is_stored_with_both_timestamps() -> None:
    repository = FakeTextRepository()

    await _service(repository).create(_command(name="contrato.pdf"))

    assert repository.last_inserted is not None
    assert repository.last_inserted.checksum == "abc123"
    assert repository.last_inserted.text == "hello"
    assert repository.last_inserted.name == "contrato.pdf"
    assert repository.last_inserted.metadata == {}
    assert repository.last_inserted.created_at == NOW
    assert repository.last_inserted.updated_at == NOW


async def test_the_metadata_of_the_command_is_kept() -> None:
    repository = FakeTextRepository()

    await _service(repository).create(_command(metadata={"pages": 12}))

    assert repository.last_inserted is not None
    assert repository.last_inserted.metadata == {"pages": 12}


async def test_an_existing_checksum_is_refused_before_inserting() -> None:
    repository = FakeTextRepository()
    repository.should_exist_checksums.add("abc123")

    with pytest.raises(ChecksumAlreadyExistsError):
        await _service(repository).create(_command())

    assert repository.last_inserted is None


async def test_a_failing_repository_is_not_swallowed() -> None:
    repository = FakeTextRepository(insert_error=PersistenceError("mongo is down"))

    with pytest.raises(PersistenceError):
        await _service(repository).create(_command())


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
