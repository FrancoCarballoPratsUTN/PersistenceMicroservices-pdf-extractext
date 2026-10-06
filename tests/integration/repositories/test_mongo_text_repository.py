"""Tests de integración de MongoTextRepository (T8).

El repositorio se ejercita sobre el cliente Mongo fake en memoria, de modo que
nada de lo que hay aquí abre un socket.
"""

from datetime import UTC, datetime

import pytest
from pymongo.errors import (
    DocumentTooLarge,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from app.config import Settings
from app.errors import (
    ChecksumAlreadyExistsError,
    DocumentTooLargeError,
    PersistenceError,
)
from app.repositories.mongodb import MongoConnection
from app.repositories.mongodb_text_repository import MongoTextRepository
from app.use_cases.ports import StoredText, TextChanges, TextRepository
from tests.fakes.fake_mongo_client import FakeMongoClientFactory


async def _make_repo(
    *, insert_error: Exception | None = None, find_error: Exception | None = None
) -> MongoTextRepository:
    """Construye un repositorio sobre una conexión respaldada por el cliente fake."""
    settings = Settings(
        service_api_token="token-for-tests-0123456789",
        mongo_uri="mongodb://test:27017",
    )
    connection = MongoConnection(
        settings,
        client_factory=FakeMongoClientFactory(
            insert_error=insert_error, find_error=find_error
        ),
    )
    await connection.start()
    return MongoTextRepository(connection.texts())


def _stored(checksum: str, text: str = "hello world") -> StoredText:
    moment = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    return StoredText(
        checksum=checksum,
        text=text,
        created_at=moment,
        updated_at=moment,
        name="contrato.pdf",
        metadata={"name": "n1"},
    )


async def test_repository_implements_the_protocol_structurally() -> None:
    repo = await _make_repo()
    assert isinstance(repo, TextRepository)


async def test_insert_then_get_returns_the_stored_text() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    got = await repo.get_by_checksum("abc123")

    assert got is not None
    assert got.checksum == "abc123"
    assert got.text == "hello world"
    assert got.name == "contrato.pdf"
    assert got.metadata == {"name": "n1"}


async def test_checksum_exists_is_false_for_an_unknown_checksum() -> None:
    repo = await _make_repo()
    assert await repo.checksum_exists("missing") is False


async def test_get_by_checksum_returns_none_when_absent() -> None:
    repo = await _make_repo()
    assert await repo.get_by_checksum("nope") is None


async def test_count_counts_every_stored_text() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("a", "t"))
    await repo.insert(_stored("b", "t"))

    assert await repo.count() == 2


async def test_inserting_the_same_checksum_twice_raises() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("dup"))

    with pytest.raises(ChecksumAlreadyExistsError):
        await repo.insert(_stored("dup"))


async def test_update_returns_none_when_the_checksum_is_absent() -> None:
    repo = await _make_repo()

    assert await repo.update("ghost", TextChanges(metadata={"name": "new"})) is None


async def test_update_changes_the_metadata_of_a_stored_text() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    updated = await repo.update("abc123", TextChanges(metadata={"name": "new"}))

    assert updated is not None
    assert updated.metadata == {"name": "new"}


async def test_delete_reports_whether_a_text_was_removed() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    assert await repo.delete("abc123") is True
    assert await repo.delete("abc123") is False


async def test_a_document_too_large_is_reported_as_such() -> None:
    repo = await _make_repo(insert_error=DocumentTooLarge("too large"))

    with pytest.raises(DocumentTooLargeError):
        await repo.insert(_stored("abc123"))


async def test_an_unreachable_server_becomes_a_persistence_error() -> None:
    repo = await _make_repo(insert_error=ServerSelectionTimeoutError("no host"))

    with pytest.raises(PersistenceError):
        await repo.insert(_stored("abc123"))


async def test_a_failing_read_becomes_a_persistence_error() -> None:
    repo = await _make_repo(find_error=OperationFailure("read failed"))

    with pytest.raises(PersistenceError):
        await repo.get_by_checksum("abc123")


async def test_updating_without_metadata_leaves_the_metadata_alone() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    updated = await repo.update("abc123", TextChanges())

    assert updated is not None
    assert updated.metadata == {"name": "n1"}


async def test_update_changes_the_name_and_keeps_it_stored() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    await repo.update("abc123", TextChanges(name="otro.pdf"))

    reread = await repo.get_by_checksum("abc123")
    assert reread is not None
    assert reread.name == "otro.pdf"


async def test_an_empty_name_is_written_over_the_stored_one() -> None:
    """``""`` es un valor que el cliente puede escribir, así que no debe leerse como
    *ausente*."""
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    updated = await repo.update("abc123", TextChanges(name=""))

    assert updated is not None
    assert updated.name == ""


async def test_updating_the_name_alone_leaves_the_metadata_alone() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    updated = await repo.update("abc123", TextChanges(name="otro.pdf"))

    assert updated is not None
    assert updated.metadata == {"name": "n1"}


async def test_update_replaces_the_metadata_instead_of_merging_it() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))

    updated = await repo.update("abc123", TextChanges(metadata={"pages": 2}))

    assert updated is not None
    assert updated.metadata == {"pages": 2}


async def test_update_keeps_created_at_and_moves_updated_at() -> None:
    repo = await _make_repo()
    await repo.insert(_stored("abc123"))
    before = await repo.get_by_checksum("abc123")
    assert before is not None

    updated = await repo.update("abc123", TextChanges(name="otro.pdf"))

    assert updated is not None
    assert updated.created_at == before.created_at
    assert updated.updated_at != before.updated_at
