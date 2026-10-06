"""Carrera sobre el mismo checksum (T11).

Llegan a la vez diez peticiones para el mismo checksum. Solo una puede
almacenarse, así que las otras nueve deben ser rechazadas, y solo el ``_id``
único puede garantizarlo, porque la comprobación de existencia no es atómica con
la inserción (SPEC 5.3).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.errors import ChecksumAlreadyExistsError
from app.main import create_app
from app.repositories.mongodb import MongoConnection
from app.repositories.mongodb_text_repository import MongoTextRepository
from app.services.text_service import TextService
from app.use_cases.ports import CreateTextCommand
from tests.fakes.fake_mongo_client import FakeMongoClient, FakeMongoClientFactory

TOKEN = "token-for-tests-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CONCURRENCY = 10
REPETITIONS = 20


@asynccontextmanager
async def _client() -> AsyncIterator[tuple[httpx.AsyncClient, FakeMongoClientFactory]]:
    """Ejecuta la app sobre el cliente fake y entrega tanto el cliente como el fake."""
    factory = FakeMongoClientFactory()
    settings = Settings(service_api_token=TOKEN, mongo_uri="mongodb://test:27017")
    connection = MongoConnection(settings, client_factory=factory)
    app = create_app(settings=settings, connection=connection)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client, factory


async def _post_same_checksum(
    client: httpx.AsyncClient, count: int, checksum: str = "abc123"
) -> list[int]:
    """Lanza ``count`` POST concurrentes para un checksum y devuelve sus estados."""
    responses = await asyncio.gather(
        *[
            client.post(
                "/texts",
                json={"checksum": checksum, "text": "hello"},
                headers=AUTH,
            )
            for _ in range(count)
        ]
    )
    return [response.status_code for response in responses]


async def test_only_one_of_ten_concurrent_posts_is_created() -> None:
    async with _client() as (client, factory):
        statuses = await _post_same_checksum(client, CONCURRENCY)

    assert statuses.count(201) == 1
    assert statuses.count(409) == CONCURRENCY - 1
    assert len(factory.client.documents) == 1


async def test_the_stored_document_is_the_only_one() -> None:
    async with _client() as (client, factory):
        await _post_same_checksum(client, CONCURRENCY)

        stored = factory.client.documents["abc123"]

    assert stored["text"] == "hello"


async def test_twenty_rounds_never_store_twice() -> None:
    async with _client() as (client, factory):
        for round_number in range(REPETITIONS):
            statuses = await _post_same_checksum(
                client, CONCURRENCY, checksum=f"round{round_number}"
            )

            assert statuses.count(201) == 1, statuses
            assert statuses.count(409) == CONCURRENCY - 1, statuses

        assert len(factory.client.documents) == REPETITIONS


async def test_a_checksum_that_was_never_stored_is_still_created() -> None:
    """La carrera no debe romper el camino feliz para un checksum nuevo."""
    async with _client() as (client, factory):
        statuses = await asyncio.gather(
            *[
                client.post(
                    "/texts",
                    json={"checksum": f"sum{i}", "text": "hello"},
                    headers=AUTH,
                )
                for i in range(CONCURRENCY)
            ]
        )

    assert [response.status_code for response in statuses] == [201] * CONCURRENCY
    assert len(factory.client.documents) == CONCURRENCY


@pytest.mark.parametrize("attempts", [2, 3, 10])
async def test_the_number_of_refusals_follows_the_number_of_requests(
    attempts: int,
) -> None:
    async with _client() as (client, factory):
        statuses = await _post_same_checksum(client, attempts)

    assert statuses.count(201) == 1
    assert statuses.count(409) == attempts - 1
    assert len(factory.client.documents) == 1


class GatedCollection:
    """La colección fake, pero toda lectura se completa antes de liberar a nadie.

    Este es el peor caso de SPEC 5.3: cada petición lee la colección antes de que
    ninguna inserte, de modo que la comprobación de existencia ve una colección
    vacía y no puede rechazar a nadie. Solo el ``_id`` único queda para atrapar
    los duplicados, y eso es precisamente lo que esta clase existe para
    demostrar.
    """

    def __init__(self, inner: Any, parties: int) -> None:
        self._inner = inner
        self._barrier = asyncio.Barrier(parties)

    async def find_one(
        self,
        query: dict[str, Any],
        projection: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        document = await self._inner.find_one(query, projection=projection, **kwargs)
        await self._barrier.wait()
        return document

    async def insert_one(self, document: dict[str, Any]) -> Any:
        return await self._inner.insert_one(document)


async def test_only_the_unique_id_refuses_when_everyone_checks_first() -> None:
    client = FakeMongoClient(
        "mongodb://test:27017", {}, ping_fails=False, index_fails=False
    )
    collection = GatedCollection(client["db"]["texts"], CONCURRENCY)
    service = TextService(MongoTextRepository(collection))
    command = CreateTextCommand(checksum="abc123", text="hello")

    results = await asyncio.gather(
        *[service.create(command) for _ in range(CONCURRENCY)], return_exceptions=True
    )

    refused = [r for r in results if isinstance(r, ChecksumAlreadyExistsError)]
    assert len(refused) == CONCURRENCY - 1
    assert len(client.documents) == 1
