"""Tests de integración de GET /texts?checksum= (T12).

La app se ejecuta sobre el cliente Mongo fake, de modo que un documento se
almacena mediante POST y se vuelve a leer mediante GET sin base de datos.
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
BODY = {
    "text": "contenido extraido del PDF...",
    "checksum": "9f86d081",
    "name": "contrato.pdf",
    "metadata": {"pages": 12, "producer": "pypdf"},
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(service_api_token=TOKEN, mongo_uri="mongodb://test:27017")
    connection = MongoConnection(settings, client_factory=FakeMongoClientFactory())
    with TestClient(create_app(settings=settings, connection=connection)) as running:
        yield running


def test_a_stored_text_is_returned_with_the_six_members(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    response = client.get("/texts?checksum=9f86d081", headers=AUTH)

    assert response.status_code == 200
    assert set(response.json()) == {
        "checksum",
        "text",
        "name",
        "metadata",
        "created_at",
        "updated_at",
    }


def test_the_members_carry_what_was_stored(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    response = client.get("/texts?checksum=9f86d081", headers=AUTH)

    assert response.json()["checksum"] == "9f86d081"
    assert response.json()["text"] == BODY["text"]
    assert response.json()["name"] == "contrato.pdf"
    assert response.json()["metadata"] == {"pages": 12, "producer": "pypdf"}


def test_the_timestamps_are_rfc3339_in_utc(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    body = client.get("/texts?checksum=9f86d081", headers=AUTH).json()

    assert body["created_at"].endswith("Z")
    assert len(body["created_at"]) == len("2026-10-01T12:34:56.789Z")


def test_both_timestamps_are_the_same_on_a_fresh_document(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    body = client.get("/texts?checksum=9f86d081", headers=AUTH).json()

    assert body["created_at"] == body["updated_at"]


def test_a_missing_query_parameter_is_refused(client: TestClient) -> None:
    response = client.get("/texts", headers=AUTH)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_empty_query_parameter_is_refused(client: TestClient) -> None:
    response = client.get("/texts?checksum=", headers=AUTH)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_unknown_checksum_is_reported_as_not_found(client: TestClient) -> None:
    response = client.get("/texts?checksum=missing", headers=AUTH)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "TEXT_NOT_FOUND"


def test_reading_a_text_needs_credentials(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    response = client.get("/texts?checksum=9f86d081")

    assert response.status_code == 401


def test_a_checksum_with_url_characters_is_found(client: TestClient) -> None:
    client.post("/texts", json={"checksum": "a/b c", "text": "hello"}, headers=AUTH)

    response = client.get("/texts", params={"checksum": "a/b c"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["checksum"] == "a/b c"


def test_a_text_without_a_name_comes_back_with_an_empty_one(
    client: TestClient,
) -> None:
    client.post("/texts", json={"checksum": "abc", "text": "hello"}, headers=AUTH)

    response = client.get("/texts?checksum=abc", headers=AUTH)

    assert response.json()["name"] == ""
    assert response.json()["metadata"] == {}
