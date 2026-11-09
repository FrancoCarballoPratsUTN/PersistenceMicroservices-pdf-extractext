"""Tests de disponibilidad (is_available) de MongoConnection."""

from __future__ import annotations

from app.repositories.mongodb import MongoConnection
from tests.unit.conftest import build_settings, FakeMongoClientFactory


async def test_a_connection_that_never_started_is_not_available() -> None:
    """Sin cliente no hay nada que responda a un ping."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory()
    )

    assert await connection.is_available() is False
