"""Tests de integración de POST /texts (T10).

La aplicación se construye con una conexión sobre el cliente Mongo fake, de modo
que todo el stack se ejecuta en memoria: ni socket, ni timeout. Entrar en el
contexto del cliente ejecuta el lifespan, que es donde se construyen la conexión
y el servicio.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repositories.mongodb import MongoConnection
from tests.fakes.fake_mongo_client import FakeMongoClientFactory

TOKEN = "token-for-tests-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(service_api_token=TOKEN, mongo_uri="mongodb://test:27017")
    connection = MongoConnection(settings, client_factory=FakeMongoClientFactory())
    with TestClient(create_app(settings=settings, connection=connection)) as running:
        yield running


def test_a_new_text_is_created_and_pointed_at(client: TestClient) -> None:
    response = client.post(
        "/texts", json={"checksum": "abc123", "text": "hello"}, headers=AUTH
    )

    assert response.status_code == 201
    assert response.headers["Location"] == "/texts?checksum=abc123"
    assert response.json() == {"message": "OK", "checksum": "abc123"}


def test_the_same_checksum_twice_is_refused(client: TestClient) -> None:
    client.post("/texts", json={"checksum": "abc123", "text": "hello"}, headers=AUTH)

    response = client.post(
        "/texts", json={"checksum": "abc123", "text": "other"}, headers=AUTH
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "CHECKSUM_ALREADY_EXISTS"


def test_all_four_fields_are_accepted(client: TestClient) -> None:
    response = client.post(
        "/texts",
        json={
            "text": "contenido extraido del PDF...",
            "checksum": "9f86d081",
            "name": "contrato.pdf",
            "metadata": {"pages": 12, "duration_ms": 431, "producer": "pypdf"},
        },
        headers=AUTH,
    )

    assert response.status_code == 201


def test_a_name_that_is_not_a_string_is_refused(client: TestClient) -> None:
    response = client.post(
        "/texts", json={"checksum": "abc123", "text": "hello", "name": 7}, headers=AUTH
    )

    assert response.status_code == 400


def test_a_body_without_text_is_refused(client: TestClient) -> None:
    response = client.post("/texts", json={"checksum": "abc123"}, headers=AUTH)

    assert response.status_code == 400


def test_a_body_that_is_not_an_object_is_refused(client: TestClient) -> None:
    response = client.post("/texts", json=["not", "an", "object"], headers=AUTH)

    assert response.status_code == 400


def test_creating_a_text_needs_credentials(client: TestClient) -> None:
    response = client.post("/texts", json={"checksum": "abc123", "text": "hello"})

    assert response.status_code == 401


def test_a_checksum_is_escaped_in_the_location(client: TestClient) -> None:
    response = client.post(
        "/texts", json={"checksum": 'a/b"c', "text": "hello"}, headers=AUTH
    )

    assert response.status_code == 201
    assert response.headers["Location"] == "/texts?checksum=a%2Fb%22c"


def test_a_checksum_is_returned_as_json_verbatim(client: TestClient) -> None:
    response = client.post(
        "/texts", json={"checksum": 'a/b"c', "text": "hello"}, headers=AUTH
    )

    assert response.json() == {"message": "OK", "checksum": 'a/b"c'}


def test_a_body_that_is_not_json_is_refused(client: TestClient) -> None:
    response = client.post(
        "/texts",
        content=b"{not json",
        headers={**AUTH, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
