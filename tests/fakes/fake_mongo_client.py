"""Sustituto en memoria de pymongo.AsyncMongoClient para tests.

Habla con MongoDB a través de una fábrica, así los tests pueden usar este fake
en lugar del cliente real. No abre sockets ni espera timeouts.
"""

from __future__ import annotations

from typing import Any

from tests.fakes.fake_database import FakeDatabase
from tests.fakes.fake_result import _Result


class FakeMongoClient:
    """Fake de AsyncMongoClient que guarda documentos y opciones en memoria."""

    def __init__(
        self,
        uri: str,
        options: dict[str, Any],
        *,
        ping_fails: bool,
        index_fails: bool,
        insert_error: Exception | None = None,
        find_error: Exception | None = None,
        update_error: Exception | None = None,
        delete_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.uri = uri
        self.options = options
        self.ping_fails = ping_fails
        self.index_fails = index_fails
        self.insert_error = insert_error
        self.find_error = find_error
        self.update_error = update_error
        self.delete_error = delete_error
        self.close_error = close_error
        self.pings = 0
        self.documents: dict[Any, dict[str, Any]] = {}
        self.closed = False

    def __getitem__(self, database: str) -> FakeDatabase:
        return FakeDatabase(self)

    async def close(self) -> None:
        """Cierra el cliente, salvo que el test pida que falle."""
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


from tests.fakes.fake_client_factory import FakeMongoClientFactory  # noqa: E402

__all__ = ["FakeMongoClient", "FakeMongoClientFactory", "_Result"]
