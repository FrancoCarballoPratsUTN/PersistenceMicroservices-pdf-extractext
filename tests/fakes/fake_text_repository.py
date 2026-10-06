"""Implementación fake en memoria de TextRepository (test double)."""

from __future__ import annotations

from typing import Any

from app.errors import DocumentTooLargeError, DuplicateKeyError
from app.use_cases.ports import StoredText, TextChanges, TextRepository


class FakeTextRepository:
    """Implementación simple en memoria de TextRepository.

    No hereda del Protocol (tipado estructural). Registra el número de llamadas
    y tiene barreras sencillas para simular errores.
    """

    def __init__(self, *, insert_error: Exception | None = None) -> None:
        self._store: dict[str, StoredText] = {}
        self.calls: dict[str, int] = {
            "checksum_exists": 0,
            "insert": 0,
            "get_by_checksum": 0,
            "update": 0,
            "delete": 0,
            "count": 0,
        }
        self.should_fail_duplicate: bool = False
        self.should_fail_too_large: bool = False
        self.last_inserted: StoredText | None = None
        self.should_exist_checksums: set[str] = set()
        self._insert_error = insert_error

    async def checksum_exists(self, checksum: str) -> bool:
        self.calls["checksum_exists"] += 1
        if checksum in self.should_exist_checksums:
            return True
        return checksum in self._store

    async def insert(self, item: StoredText) -> None:
        self.calls["insert"] += 1
        self.last_inserted = item
        if self._insert_error is not None:
            raise self._insert_error
        if self.should_fail_duplicate:
            raise DuplicateKeyError("simulated duplicate")
        if self.should_fail_too_large:
            raise DocumentTooLargeError("simulated too large")
        if item.checksum in self._store:
            raise DuplicateKeyError(f"checksum exists {item.checksum}")
        self._store[item.checksum] = item

    async def get_by_checksum(self, checksum: str) -> StoredText | None:
        self.calls["get_by_checksum"] += 1
        return self._store.get(checksum)

    async def update(self, checksum: str, changes: TextChanges) -> StoredText | None:
        self.calls["update"] += 1
        if checksum not in self._store:
            return None
        old = self._store[checksum]
        meta: dict[str, Any] | None
        if changes.metadata is not None:
            meta = changes.metadata.copy()
        else:
            meta = old.metadata.copy() if old.metadata is not None else None
        new_item = StoredText(
            checksum=old.checksum,
            text=old.text,
            created_at=old.created_at,
            updated_at=old.updated_at,
            name=changes.name if changes.name is not None else old.name,
            metadata=meta,
        )
        self._store[checksum] = new_item
        return new_item

    async def delete(self, checksum: str) -> bool:
        self.calls["delete"] += 1
        if checksum in self._store:
            del self._store[checksum]
            return True
        return False

    async def count(self) -> int:
        self.calls["count"] += 1
        return len(self._store)


def _structural_check() -> None:
    _: TextRepository = FakeTextRepository()  # type: ignore[assignment]


_structural_check()
