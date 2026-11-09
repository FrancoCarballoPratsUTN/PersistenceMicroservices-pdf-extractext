"""Fábrica que construye instancias de FakeMongoClient y las guarda."""

from __future__ import annotations

from typing import Any

from tests.fakes.fake_mongo_client import FakeMongoClient


class FakeMongoClientFactory:
    """Construye instancias de :class:`FakeMongoClient` y las guarda para las
    aserciones.

    Args:
        ping_fails: Si es verdadero, todo ping lanza excepción, como ocurriría
            contra un servidor que no está ahí.
        index_fails: Si es verdadero, la creación del índice lanza excepción.
    """

    def __init__(
        self,
        *,
        ping_fails: bool = False,
        index_fails: bool = False,
        insert_error: Exception | None = None,
        find_error: Exception | None = None,
        update_error: Exception | None = None,
        delete_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.ping_fails = ping_fails
        self.index_fails = index_fails
        self.insert_error = insert_error
        self.find_error = find_error
        self.update_error = update_error
        self.delete_error = delete_error
        self.close_error = close_error
        self.clients: list[FakeMongoClient] = []

    def __call__(self, uri: str, **options: Any) -> FakeMongoClient:
        client = FakeMongoClient(
            uri,
            options,
            ping_fails=self.ping_fails,
            index_fails=self.index_fails,
            insert_error=self.insert_error,
            find_error=self.find_error,
            update_error=self.update_error,
            delete_error=self.delete_error,
            close_error=self.close_error,
        )
        self.clients.append(client)
        return client

    @property
    def client(self) -> FakeMongoClient:
        """El cliente construido hasta ahora. Cada test construye exactamente uno."""
        return self.clients[-1]
