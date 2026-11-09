"""Tests de arranque (start) de MongoConnection."""

from __future__ import annotations

import logging

import pytest

from app.repositories.mongodb import MongoConnection
from tests.unit.conftest import build_settings, FakeMongoClientFactory


async def test_the_client_is_built_with_the_configured_timeout() -> None:
    """La fábrica recibe la URI y el timeout que piden los ajustes."""
    factory = FakeMongoClientFactory()
    connection = MongoConnection(
        build_settings(
            mongo_timeout_ms=4000, mongo_socket_timeout_ms=3000, mongo_max_pool_size=20
        ),
        client_factory=factory,
    )

    await connection.start()

    client = factory.client
    assert client.uri == "mongodb://mongo.invalid:27017"
    assert client.options["serverSelectionTimeoutMS"] == 4000
    assert client.options["connectTimeoutMS"] == 4000
    assert client.options["timeoutMS"] == 4000
    assert client.options["socketTimeoutMS"] == 3000
    assert client.options["maxPoolSize"] == 20
    assert client.options["retryWrites"] is False


async def test_a_successful_start_reports_mongo_as_available() -> None:
    """Arrancar contra un MongoDB que responde deja la conexión utilizable."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory()
    )

    assert await connection.start() is True
    assert await connection.is_available() is True


async def test_start_succeeds_when_index_creation_is_unavailable() -> None:
    """El arranque no depende de un índice secundario."""
    factory = FakeMongoClientFactory(index_fails=True)
    connection = MongoConnection(build_settings(), client_factory=factory)

    assert await connection.start() is True
    assert factory.client.pings == 1


async def test_a_mongo_that_does_not_answer_lets_the_start_finish() -> None:
    """Un MongoDB muerto se informa, no se propaga: la app debe sobrevivirlo."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory(ping_fails=True)
    )

    assert await connection.start() is False
    assert await connection.is_available() is False


async def test_a_dead_mongo_is_reported_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Quien opera tiene que poder leer por qué no está la base de datos."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory(ping_fails=True)
    )

    with caplog.at_level(logging.WARNING, logger="app.repositories.mongodb"):
        await connection.start()

    assert any(record.levelno >= logging.WARNING for record in caplog.records)


async def test_the_credentials_in_the_uri_are_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La URI puede llevar una contraseña, así que nunca llega al log."""
    from app.config import Settings

    settings = Settings(
        mongo_uri="mongodb://user:super-secret@mongo.invalid:27017",
        mongo_database="texts",
        mongo_texts_collection="texts",
        mongo_timeout_ms=5000,
        service_api_token="token-for-tests-0123456789",
    )
    connection = MongoConnection(
        settings, client_factory=FakeMongoClientFactory(ping_fails=True)
    )

    with caplog.at_level(logging.DEBUG, logger="app.repositories.mongodb"):
        await connection.start()

    assert "super-secret" not in caplog.text
