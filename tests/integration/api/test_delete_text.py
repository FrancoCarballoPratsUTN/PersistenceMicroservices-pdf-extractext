"""Tests de integración de DELETE /texts?checksum= (T14).

El documento se crea mediante POST y luego se borra mediante DELETE; lo que el
cliente puede observar después es un GET que ya no lo encuentra.
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
CHECKSUM = "9f86d081"
BODY = {"text": "contenido extraido...", "checksum": CHECKSUM, "name": "contrato.pdf"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(service_api_token=TOKEN, mongo_uri="mongodb://test:27017")
    connection = MongoConnection(settings, client_factory=FakeMongoClientFactory())
    with TestClient(create_app(settings=settings, connection=connection)) as running:
        yield running


def test_a_deleted_text_is_answered_with_ok_and_its_checksum(
    client: TestClient,
) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    response = client.delete("/texts", params={"checksum": CHECKSUM}, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"message": "OK", "checksum": CHECKSUM}


def test_the_document_is_gone_afterwards(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    client.delete("/texts", params={"checksum": CHECKSUM}, headers=AUTH)

    assert (
        client.get("/texts", params={"checksum": CHECKSUM}, headers=AUTH).status_code
        == 404
    )


def test_only_the_asked_checksum_is_deleted(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)
    client.post("/texts", json={"text": "otro", "checksum": "otro1"}, headers=AUTH)

    client.delete("/texts", params={"checksum": CHECKSUM}, headers=AUTH)

    gone = client.get("/texts", params={"checksum": CHECKSUM}, headers=AUTH)
    kept = client.get("/texts", params={"checksum": "otro1"}, headers=AUTH)
    assert gone.status_code == 404
    assert kept.status_code == 200


def test_deleting_twice_answers_not_found_the_second_time(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)
    client.delete("/texts", params={"checksum": CHECKSUM}, headers=AUTH)

    response = client.delete("/texts", params={"checksum": CHECKSUM}, headers=AUTH)

    assert response.status_code == 404


def test_an_unknown_checksum_is_reported_as_not_found(client: TestClient) -> None:
    response = client.delete("/texts", params={"checksum": "missing"}, headers=AUTH)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "TEXT_NOT_FOUND"


def test_a_missing_query_parameter_is_refused(client: TestClient) -> None:
    response = client.delete("/texts", headers=AUTH)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_empty_query_parameter_is_refused(client: TestClient) -> None:
    response = client.delete("/texts", params={"checksum": ""}, headers=AUTH)

    assert response.status_code == 400


def test_deleting_a_text_needs_credentials(client: TestClient) -> None:
    client.post("/texts", json=BODY, headers=AUTH)

    response = client.delete("/texts", params={"checksum": CHECKSUM})

    assert response.status_code == 401


def test_a_checksum_with_url_characters_is_deleted(client: TestClient) -> None:
    client.post("/texts", json={"text": "hello", "checksum": "a/b c"}, headers=AUTH)

    response = client.delete("/texts", params={"checksum": "a/b c"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["checksum"] == "a/b c"
    assert (
        client.get("/texts", params={"checksum": "a/b c"}, headers=AUTH).status_code
        == 404
    )
