"""Tests unitarios del ciclo de vida de MongoDB (tarea T6).

Nada de lo que hay aquí toca la red: el cliente es un fake que responde o rechaza
un ping en memoria, así que ningún test abre un socket ni espera un timeout.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from pymongo.errors import OperationFailure

from app.config import Settings
from app.repositories.mongodb import MongoConnection
from tests.fakes.fake_mongo_client import FakeMongoClientFactory

TOKEN = "token-for-tests-0123456789"


def build_settings(**overrides: Any) -> Settings:
    """Devuelve unos ajustes con timeout corto y sin esperas de red."""
    return Settings(
        mongo_uri="mongodb://mongo.invalid:27017",
        mongo_database="texts",
        mongo_texts_collection="texts",
        mongo_timeout_ms=5000,
        service_api_token=TOKEN,
        **overrides,
    )


@asynccontextmanager
async def running_app(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    """Arranca la app como lo haría un servidor y luego responde peticiones con ella."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client


@asynccontextmanager
async def build_running_app(
    factory: FakeMongoClientFactory,
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeMongoClientFactory]]:
    """Una app cuyo MongoDB responde exactamente como se le indicó a ``factory``."""
    from app.main import create_app

    settings = build_settings()
    connection = MongoConnection(settings, client_factory=factory)
    app = create_app(settings, connection=connection)
    async with running_app(app) as client:
        yield client, factory


async def test_the_client_is_built_with_the_configured_timeout() -> None:
    """La fábrica recibe la URI y el timeout que piden los ajustes."""
    factory = FakeMongoClientFactory()
    connection = MongoConnection(build_settings(), client_factory=factory)

    await connection.start()

    client = factory.client
    assert client.uri == "mongodb://mongo.invalid:27017"
    assert client.options["serverSelectionTimeoutMS"] == 5000
    assert client.options["connectTimeoutMS"] == 5000


async def test_a_successful_start_reports_mongo_as_available() -> None:
    """Arrancar contra un MongoDB que responde deja la conexión utilizable."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory()
    )

    assert await connection.start() is True
    assert await connection.is_available() is True


async def test_the_start_ensures_the_index_on_updated_at() -> None:
    """El bootstrap crea el índice que pide SPEC 5.5, sobre la colección de
    textos."""
    factory = FakeMongoClientFactory()
    connection = MongoConnection(build_settings(), client_factory=factory)

    await connection.start()

    assert factory.client.indexes == [("texts.texts", "updated_at")]


async def test_a_mongo_that_does_not_answer_lets_the_start_finish() -> None:
    """Un MongoDB muerto se informa, no se propaga: la app debe sobrevivirlo."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory(ping_fails=True)
    )

    assert await connection.start() is False
    assert await connection.is_available() is False


async def test_a_failed_index_lets_the_start_finish() -> None:
    """Un bootstrap que no puede terminar también se informa, en vez de matar la
    app."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory(index_fails=True)
    )

    assert await connection.start() is False


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
    settings = Settings(
        mongo_uri="mongodb://user:super-secret@mongo.invalid:27017",
        mongo_database="texts",
        mongo_texts_collection="texts",
        mongo_timeout_ms=5000,
        service_api_token=TOKEN,
    )
    connection = MongoConnection(
        settings, client_factory=FakeMongoClientFactory(ping_fails=True)
    )

    with caplog.at_level(logging.DEBUG, logger="app.repositories.mongodb"):
        await connection.start()

    assert "super-secret" not in caplog.text


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
    factory = FakeMongoClientFactory(close_error=RuntimeError("boom"))

    with caplog.at_level(logging.ERROR, logger="app.main"):
        async with build_running_app(factory) as (_, _):
            pass

    assert any(record.levelno >= logging.ERROR for record in caplog.records)


async def test_the_shutdown_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Quien opera tiene que poder ver en el log que el servicio cerró y cuánto
    tardó, no sólo que dejó de responder (SPEC 5.5)."""
    with caplog.at_level(logging.INFO, logger="app.main"):
        async with build_running_app(FakeMongoClientFactory()) as (_, _):
            pass

    messages = [record.getMessage().lower() for record in caplog.records]
    assert any("shutting down" in message for message in messages)
    assert any("shutdown finished" in message for message in messages)


async def test_a_connection_that_never_started_is_not_available() -> None:
    """Sin cliente no hay nada que responda a un ping."""
    connection = MongoConnection(
        build_settings(), client_factory=FakeMongoClientFactory()
    )

    assert await connection.is_available() is False


async def test_the_app_starts_and_reports_itself_when_mongo_is_down() -> None:
    """AC: con MongoDB inalcanzable la app arranca igualmente y /readyz responde
    503."""
    async with build_running_app(FakeMongoClientFactory(ping_fails=True)) as (
        client,
        _,
    ):
        health = await client.get("/health")
        ready = await client.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503


async def test_readyz_explains_the_database_is_not_available() -> None:
    """Un 503 es un documento problem+json, como cualquier otro error de la API."""
    async with build_running_app(FakeMongoClientFactory(ping_fails=True)) as (
        client,
        _,
    ):
        ready = await client.get("/readyz")

    body = ready.json()
    assert ready.headers["content-type"].startswith("application/problem+json")
    assert body["status"] == 503
    assert body["title"] == "Persistence unavailable"
    assert body["code"] == "PERSISTENCE_ERROR"
    assert "mongo" in body["detail"].lower()


async def test_readyz_reports_ok_when_mongo_answers() -> None:
    """La forma sana de /readyz es la que documenta SPEC 3.1."""
    async with build_running_app(FakeMongoClientFactory()) as (client, _):
        ready = await client.get("/readyz")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "mongo": "ok"}


async def test_health_answers_even_when_mongo_is_down() -> None:
    """La vivacidad trata del proceso, no de la base de datos que hay detrás."""
    async with build_running_app(FakeMongoClientFactory(ping_fails=True)) as (
        client,
        _,
    ):
        health = await client.get("/health")

    assert health.status_code == 200


async def test_the_probes_stay_open_without_credentials() -> None:
    """El orquestador sondea sin token, así que ambas rutas siguen públicas."""
    async with build_running_app(FakeMongoClientFactory()) as (client, _):
        health = await client.get("/health")
        ready = await client.get("/readyz")

    assert health.status_code == 200
    assert ready.status_code == 200


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
