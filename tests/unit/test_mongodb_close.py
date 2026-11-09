"""Tests de cierre (close) de MongoConnection."""

from __future__ import annotations

import logging

import pytest
from pymongo.errors import OperationFailure

from app.repositories.mongodb import MongoConnection
from tests.unit.conftest import build_settings, FakeMongoClientFactory


async def test_closing_releases_the_client() -> None:
    """El cliente construido en el arranque se cierra al bajar."""
    factory = FakeMongoClientFactory()
    connection = MongoConnection(build_settings(), client_factory=factory)
    await connection.start()

    await connection.close()

    assert factory.client.closed is True


async def test_closing_before_starting_is_harmless() -> None:
    """Una conexión que nunca llegó a la base de datos se cierra sin quejarse."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory()
    )

    await connection.close()


async def test_closing_twice_is_harmless() -> None:
    """Las rutas de apagado pueden ejecutarse más de una vez; cerrar dos veces no
    debe fallar."""
    factory = FakeMongoClientFactory()
    connection = MongoConnection(build_settings(), client_factory=factory)
    await connection.start()

    await connection.close()
    await connection.close()

    assert factory.client.closed is True


async def test_a_driver_error_while_closing_is_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Soltar el pool no puede tumbar el apagado: un error del driver se registra
    y no se propaga."""
    factory = FakeMongoClientFactory(close_error=OperationFailure("cannot close"))
    connection = MongoConnection(build_settings(), client_factory=factory)
    await connection.start()

    with caplog.at_level(logging.WARNING, logger="app.repositories.mongodb"):
        await connection.close()

    assert any(record.levelno >= logging.WARNING for record in caplog.records)


async def test_an_unexpected_error_while_closing_does_not_break_the_shutdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un error que la conexión no anticipa lo atrapa la raíz de composición: el
    lifespan termina igual en vez de morir durante el apagado."""
    from app.main import create_app

    factory = FakeMongoClientFactory(close_error=RuntimeError("boom"))
    connection = MongoConnection(build_settings(), client_factory=factory)
    app = create_app(build_settings(), connection=connection)

    with caplog.at_level(logging.ERROR, logger="app.main"):
        async with app.router.lifespan_context(app):
            pass

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
