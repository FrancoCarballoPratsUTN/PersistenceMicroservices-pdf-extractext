"""Tests de sondas (health y readyz)."""

from __future__ import annotations

from app.main import create_app
from app.repositories.mongodb import MongoConnection

from tests.unit.conftest import (
    build_running_app,
    build_settings,
    running_app,
    FakeMongoClientFactory,
)


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


async def test_readyz_reuses_ping_until_cache_expires(monkeypatch) -> None:
    """El caché de readiness evita golpear Mongo en cada sonda."""
    import app.repositories.mongodb as mongodb

    current_time = 10.0
    monkeypatch.setattr(mongodb.client, "monotonic", lambda: current_time)
    factory = FakeMongoClientFactory()
    settings = build_settings(mongo_readiness_cache_ttl_seconds=1)
    connection = MongoConnection(settings, client_factory=factory)
    app = create_app(settings, connection=connection)

    async with running_app(app) as client:
        assert factory.client.pings == 1  # ping de inicio
        assert (await client.get("/readyz")).status_code == 200
        assert (await client.get("/readyz")).status_code == 200
        assert factory.client.pings == 1

        current_time += 1.1
        assert (await client.get("/readyz")).status_code == 200

    assert factory.client.pings == 2


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
