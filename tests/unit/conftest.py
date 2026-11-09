"""Helpers compartidos para tests del ciclo de vida de MongoDB."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.config import Settings
from app.repositories.mongodb import MongoConnection
from tests.fakes.fake_mongo_client import FakeMongoClientFactory

TOKEN = "token-for-tests-0123456789"


def build_settings(**overrides: Any) -> Settings:
    """Devuelve unos ajustes con timeout corto y sin esperas de red."""
    values = {
        "mongo_uri": "mongodb://mongo.invalid:27017",
        "mongo_database": "texts",
        "mongo_texts_collection": "texts",
        "mongo_timeout_ms": 5000,
        "service_api_token": TOKEN,
    }
    values.update(overrides)
    return Settings(**values)


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
