"""Tests de integración de PUT /texts?checksum= (T13).

Todo el stack se ejecuta en memoria sobre el cliente Mongo fake: un documento se
crea mediante POST, se modifica mediante PUT y se vuelve a leer para ver qué
quedó realmente.
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
BODY = {
    "text": "contenido extraido del PDF...",
    "checksum": CHECKSUM,
    "name": "contrato.pdf",
    "metadata": {"pages": 12, "producer": "pypdf"},
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(service_api_token=TOKEN, mongo_uri="mongodb://test:27017")
    connection = MongoConnection(settings, client_factory=FakeMongoClientFactory())
    with TestClient(create_app(settings=settings, connection=connection)) as running:
        yield running


def _stored(client: TestClient) -> None:
    """Coloca un documento en el almacen antes de modificarlo."""
    created = client.post("/texts", json=BODY, headers=AUTH)
    assert created.status_code == 201


def test_updating_the_name_answers_with_the_stored_text(client: TestClient) -> None:
    _stored(client)

    response = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"name": "otro.pdf"}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["name"] == "otro.pdf"


def test_the_update_is_kept_and_can_be_read_back(client: TestClient) -> None:
    _stored(client)

    client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"name": "otro.pdf"}, headers=AUTH
    )

    assert (
        client.get("/texts", params={"checksum": CHECKSUM}, headers=AUTH).json()["name"]
        == "otro.pdf"
    )


def test_the_text_and_the_checksum_are_never_touched(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"name": "otro.pdf"}, headers=AUTH
    ).json()

    assert body["checksum"] == CHECKSUM
    assert body["text"] == BODY["text"]


def test_an_absent_name_leaves_the_stored_one_alone(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={"metadata": {"pages": 2}},
        headers=AUTH,
    ).json()

    assert body["name"] == "contrato.pdf"
    assert body["metadata"] == {"pages": 2}


def test_a_null_name_leaves_the_stored_one_alone(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={"name": None, "metadata": {"pages": 2}},
        headers=AUTH,
    ).json()

    assert body["name"] == "contrato.pdf"


def test_a_null_metadata_leaves_the_stored_one_alone(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={"name": "otro.pdf", "metadata": None},
        headers=AUTH,
    ).json()

    assert body["metadata"] == {"pages": 12, "producer": "pypdf"}


def test_the_metadata_is_replaced_and_not_merged(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={"metadata": {"pages": 2}},
        headers=AUTH,
    ).json()

    assert body["metadata"] == {"pages": 2}


def test_an_empty_metadata_object_clears_it(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"metadata": {}}, headers=AUTH
    ).json()

    assert body["metadata"] == {}


def test_an_empty_name_overwrites_the_stored_one(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"name": ""}, headers=AUTH
    ).json()

    assert body["name"] == ""


def test_both_fields_can_change_in_one_call(client: TestClient) -> None:
    _stored(client)

    body = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={"name": "otro.pdf", "metadata": {"pages": 2}},
        headers=AUTH,
    ).json()

    assert body["name"] == "otro.pdf"
    assert body["metadata"] == {"pages": 2}


def test_the_creation_timestamp_survives_the_update(client: TestClient) -> None:
    _stored(client)
    before = client.get("/texts", params={"checksum": CHECKSUM}, headers=AUTH).json()

    after = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"name": "otro.pdf"}, headers=AUTH
    ).json()

    assert after["created_at"] == before["created_at"]


def test_the_answer_carries_the_six_members(client: TestClient) -> None:
    _stored(client)

    response = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"name": "otro.pdf"}, headers=AUTH
    )

    assert set(response.json()) == {
        "checksum",
        "text",
        "name",
        "metadata",
        "created_at",
        "updated_at",
    }


@pytest.mark.parametrize("field", ["text", "checksum"])
def test_a_body_carrying_an_immutable_field_is_refused(
    client: TestClient, field: str
) -> None:
    _stored(client)

    response = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={field: "otro valor"},
        headers=AUTH,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "IMMUTABLE_FIELD"


def test_an_immutable_field_does_not_change_the_stored_text(
    client: TestClient,
) -> None:
    _stored(client)

    client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={"checksum": "otro", "name": "otro.pdf"},
        headers=AUTH,
    )

    stored = client.get("/texts", params={"checksum": CHECKSUM}, headers=AUTH)
    assert stored.json()["name"] == "contrato.pdf"


def test_an_empty_body_is_refused(client: TestClient) -> None:
    _stored(client)

    response = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={}, headers=AUTH
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("metadata", ["pages", 12])
def test_metadata_that_is_not_an_object_is_refused(
    client: TestClient, metadata: object
) -> None:
    _stored(client)

    response = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        json={"metadata": metadata},
        headers=AUTH,
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_a_name_that_is_not_a_string_is_refused(client: TestClient) -> None:
    _stored(client)

    response = client.put(
        "/texts", params={"checksum": CHECKSUM}, json={"name": 7}, headers=AUTH
    )

    assert response.status_code == 400


def test_a_body_that_is_not_an_object_is_refused(client: TestClient) -> None:
    _stored(client)

    response = client.put(
        "/texts", params={"checksum": CHECKSUM}, json=["name"], headers=AUTH
    )

    assert response.status_code == 400


def test_a_body_that_is_not_json_is_refused(client: TestClient) -> None:
    _stored(client)

    response = client.put(
        "/texts",
        params={"checksum": CHECKSUM},
        content=b"{not json",
        headers={**AUTH, "Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_a_missing_query_parameter_is_refused(client: TestClient) -> None:
    _stored(client)

    response = client.put("/texts", json={"name": "otro.pdf"}, headers=AUTH)

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_an_empty_query_parameter_is_refused(client: TestClient) -> None:
    _stored(client)

    response = client.put(
        "/texts", params={"checksum": ""}, json={"name": "x"}, headers=AUTH
    )

    assert response.status_code == 400


def test_an_unknown_checksum_is_reported_as_not_found(client: TestClient) -> None:
    response = client.put(
        "/texts",
        params={"checksum": "missing"},
        json={"name": "otro.pdf"},
        headers=AUTH,
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "TEXT_NOT_FOUND"


def test_updating_a_text_needs_credentials(client: TestClient) -> None:
    _stored(client)

    response = client.put("/texts", params={"checksum": CHECKSUM}, json={"name": "x"})

    assert response.status_code == 401
