"""Tests de cierre del cliente al apagar la aplicación."""

from __future__ import annotations

from app.repositories.mongodb import MongoConnection
from tests.unit.conftest import build_running_app, build_settings, FakeMongoClientFactory


async def test_the_client_is_closed_when_the_app_stops() -> None:
    """AC: el cliente se cierra limpiamente cuando la app se apaga."""
    async with build_running_app(FakeMongoClientFactory()) as (_, factory):
        pass

    assert factory.client.closed is True


async def test_the_client_is_closed_even_when_mongo_never_answered() -> None:
    """Una base de datos que nunca levantó no filtra el cliente que lo intentó."""
    async with build_running_app(FakeMongoClientFactory(ping_fails=True)) as (
        _,
        factory,
    ):
        pass

    assert factory.client.closed is True
