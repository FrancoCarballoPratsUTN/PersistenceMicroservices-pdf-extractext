"""Tests de logging de arranque y apagado."""

from __future__ import annotations

import logging

from tests.unit.conftest import build_running_app, FakeMongoClientFactory


async def test_the_start_is_logged(caplog) -> None:
    """El arranque enmarca el ciclo de vida en el log, con su duración, para poder
    leer el timeline de una instancia junto a la línea de apagado."""
    with caplog.at_level(logging.INFO, logger="app.lifespan"):
        async with build_running_app(FakeMongoClientFactory()) as (_, _):
            pass

    messages = [record.getMessage().lower() for record in caplog.records]
    assert any("starting the service" in message for message in messages)
    assert any("service started in" in message for message in messages)


async def test_the_shutdown_is_logged(caplog) -> None:
    """Quien opera tiene que poder ver en el log que el servicio cerró y cuánto
    tardó, no sólo que dejó de responder (SPEC 5.5)."""
    with caplog.at_level(logging.INFO, logger="app.lifespan"):
        async with build_running_app(FakeMongoClientFactory()) as (_, _):
            pass

    messages = [record.getMessage().lower() for record in caplog.records]
    assert any("shutting down" in message for message in messages)
    assert any("shutdown finished" in message for message in messages)
