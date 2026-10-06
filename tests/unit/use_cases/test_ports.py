"""Tests de los puertos y del test double (T7)."""

from datetime import UTC, datetime

from app.use_cases.ports import StoredText, TextChanges, TextRepository
from tests.fakes.fake_text_repository import FakeTextRepository


async def test_fake_is_structural_subtype_of_protocol() -> None:
    """El fake satisface TextRepository por tipado estructural."""
    repo = FakeTextRepository()
    assert isinstance(repo, TextRepository)


async def test_fake_starts_empty() -> None:
    """Empieza sin documentos."""
    repo = FakeTextRepository()
    repo.calls["count"] = 0
    assert await repo.count() == 0
    assert await repo.checksum_exists("abc") is False
    assert await repo.get_by_checksum("abc") is None


async def test_insert_and_get() -> None:
    """Insert almacena y get recupera."""
    repo = FakeTextRepository()
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    item = StoredText(
        checksum="abc123",
        text="hello",
        created_at=now,
        updated_at=now,
        metadata={"name": "test"},
    )
    await repo.insert(item)
    assert await repo.count() == 1
    assert await repo.checksum_exists("abc123") is True
    got = await repo.get_by_checksum("abc123")
    assert got is not None
    assert got.checksum == "abc123"
    assert got.text == "hello"
    assert got.metadata == {"name": "test"}


async def test_update_changes_metadata_only() -> None:
    """Update devuelve el elemento actualizado, o None si no existe."""
    repo = FakeTextRepository()
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    item = StoredText(
        checksum="abc123",
        text="hello",
        created_at=now,
        updated_at=now,
        metadata=None,
    )
    await repo.insert(item)
    updated = await repo.update("abc123", TextChanges(metadata={"x": 1}))
    assert updated is not None
    assert updated.metadata == {"x": 1}
    missing = await repo.update("nope", TextChanges(metadata={"x": 1}))
    assert missing is None


async def test_delete_returns_true_only_when_existed() -> None:
    """Delete devuelve un booleano."""
    repo = FakeTextRepository()
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    await repo.insert(
        StoredText(
            checksum="abc123",
            text="hello",
            created_at=now,
            updated_at=now,
        )
    )
    assert await repo.delete("abc123") is True
    assert await repo.delete("abc123") is False


async def test_calls_counters_track_invocations() -> None:
    """Los contadores de llamadas funcionan."""
    repo = FakeTextRepository()
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    await repo.insert(
        StoredText(
            checksum="abc123",
            text="t",
            created_at=now,
            updated_at=now,
        )
    )
    await repo.checksum_exists("abc123")
    await repo.get_by_checksum("abc123")
    await repo.update("abc123", TextChanges(metadata=None))
    await repo.delete("abc123")
    await repo.count()
    assert repo.calls["insert"] >= 1
    assert repo.calls["checksum_exists"] >= 1
    assert repo.calls["get_by_checksum"] >= 1
    assert repo.calls["update"] >= 1
    assert repo.calls["delete"] >= 1
    assert repo.calls["count"] >= 1


async def test_duplicate_barrier_raises() -> None:
    """La barrera simula un duplicado."""
    repo = FakeTextRepository()
    repo.should_fail_duplicate = True
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    from app.errors import DuplicateKeyError

    try:
        await repo.insert(
            StoredText(
                checksum="abc123",
                text="t",
                created_at=now,
                updated_at=now,
            )
        )
        raise AssertionError()
    except DuplicateKeyError:
        pass


async def test_too_large_barrier_raises() -> None:
    """La barrera simula un documento demasiado grande."""
    repo = FakeTextRepository()
    repo.should_fail_too_large = True
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    from app.errors import DocumentTooLargeError

    try:
        await repo.insert(
            StoredText(
                checksum="abc123",
                text="t",
                created_at=now,
                updated_at=now,
            )
        )
        raise AssertionError()
    except DocumentTooLargeError:
        pass
