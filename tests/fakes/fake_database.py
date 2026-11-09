"""Handle fake de base de datos que entrega colecciones en memoria."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from pymongo.errors import ServerSelectionTimeoutError

from tests.fakes.fake_collection import FakeCollection

if TYPE_CHECKING:
    from tests.fakes.fake_mongo_client import FakeMongoClient


class FakeDatabase:
    """Handle fake de base de datos que entrega colecciones en memoria."""

    def __init__(self, client: "FakeMongoClient") -> None:
        self._client = client

    async def command(self, name: str) -> dict[str, Any]:
        """Responde a un comando de base de datos como lo haría un servidor
        accesible."""
        if self._client.ping_fails:
            raise ServerSelectionTimeoutError(
                f"no MongoDB host answered '{name}'"
            )
        self._client.pings += 1
        return {"ok": 1}

    def __getitem__(self, _: str) -> FakeCollection:
        return FakeCollection(self._client)
