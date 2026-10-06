"""Tests del stack de middleware HTTP de :mod:`app.api.middleware` (T15).

Cada petición atraviesa la raíz de composición real, porque el orden del stack es
parte de lo que se prueba: un middleware que nunca se registra, o que se registra
en el sitio equivocado, pasaría un test que lo llamara directamente.

Las comprobaciones son sobre lo que observa el llamante -- estado, cabeceras,
cuerpo -- y sobre el orden que fija SPEC 3.3: ``401`` antes que ``415``, ``415``
antes que ``413``, y ambos antes que el ``400`` que produciría el análisis del
cuerpo.
"""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.repositories.mongodb import MongoConnection
from tests.fakes.fake_mongo_client import FakeMongoClientFactory

TOKEN = "token-for-tests-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
JSON = {"Content-Type": "application/json"}
BODY = '{"checksum":"abc123","text":"hello"}'


def build_client(*, max_body_bytes: int = 10485760) -> Iterator[TestClient]:
    settings = Settings(
        service_api_token=TOKEN,
        mongo_uri="mongodb://test:27017",
        max_text_body_bytes=max_body_bytes,
    )
    connection = MongoConnection(settings, client_factory=FakeMongoClientFactory())
    with TestClient(create_app(settings=settings, connection=connection)) as client:
        yield client


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from build_client()


@pytest.fixture
def small_client() -> Iterator[TestClient]:
    """Un cliente cuyo límite de cuerpo son 100 bytes, para mantener los tests
    pequeños."""
    yield from build_client(max_body_bytes=100)


# --- 415: el tipo de contenido ---------------------------------------------


def test_a_post_declaring_json_is_accepted(client: TestClient) -> None:
    response = client.post("/texts", content=BODY, headers={**AUTH, **JSON})

    assert response.status_code == 201


def test_a_post_that_is_not_json_is_refused(client: TestClient) -> None:
    response = client.post(
        "/texts", content=BODY, headers={**AUTH, "Content-Type": "text/plain"}
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_a_put_that_is_not_json_is_refused(client: TestClient) -> None:
    response = client.put(
        "/texts",
        params={"checksum": "abc123"},
        content=BODY,
        headers={**AUTH, "Content-Type": "text/plain"},
    )

    assert response.status_code == 415


def test_a_post_without_a_content_type_is_refused(client: TestClient) -> None:
    response = client.post("/texts", content=BODY, headers=AUTH)

    assert response.status_code == 415


def test_json_with_a_charset_is_still_json(client: TestClient) -> None:
    response = client.post(
        "/texts",
        content=BODY,
        headers={**AUTH, "Content-Type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 201


def test_a_get_without_a_content_type_is_not_refused(client: TestClient) -> None:
    response = client.get("/texts", params={"checksum": "abc123"}, headers=AUTH)

    assert response.status_code == 404


def test_a_refusal_names_the_content_type_it_wanted(client: TestClient) -> None:
    response = client.post("/texts", content=BODY, headers=AUTH)

    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 415


# --- 413: el tamaño del cuerpo ---------------------------------------------


def test_a_body_over_the_limit_is_refused(small_client: TestClient) -> None:
    response = small_client.post(
        "/texts",
        content='{"text":"' + "x" * 200 + '"}',
        headers={**AUTH, **JSON},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_a_body_exactly_at_the_limit_is_accepted(small_client: TestClient) -> None:
    padding = 100 - len('{"text":"","checksum":"abc123"}')
    body = '{"text":"' + "x" * padding + '","checksum":"abc123"}'

    response = small_client.post("/texts", content=body, headers={**AUTH, **JSON})

    assert len(body) == 100
    assert response.status_code == 201


def test_a_body_over_the_ten_mib_default_is_refused(client: TestClient) -> None:
    response = client.post(
        "/texts",
        content=b"x" * (11 * 1024 * 1024),
        headers={**AUTH, **JSON},
    )

    assert response.status_code == 413


def test_a_get_without_a_body_is_not_refused(small_client: TestClient) -> None:
    response = small_client.get("/health")

    assert response.status_code == 200


# --- el orden que fija la SPEC ---------------------------------------------


def test_the_token_is_checked_before_the_body_size(
    small_client: TestClient,
) -> None:
    response = small_client.post("/texts", content=b"x" * 500, headers={**JSON})

    assert response.status_code == 401


def test_the_content_type_is_checked_before_the_body_size(
    small_client: TestClient,
) -> None:
    response = small_client.post(
        "/texts", content=b"x" * 500, headers={**AUTH, "Content-Type": "text/plain"}
    )

    assert response.status_code == 415


def test_the_content_type_is_checked_before_the_body_is_parsed(
    client: TestClient,
) -> None:
    """Un cuerpo que ni siquiera es JSON se rechaza primero como tipo de medio
    incorrecto."""
    response = client.post(
        "/texts", content="{not json", headers={**AUTH, "Content-Type": "text/plain"}
    )

    assert response.status_code == 415


# --- X-Request-ID ----------------------------------------------------------


def test_a_request_id_is_generated_when_the_caller_sends_none(
    client: TestClient,
) -> None:
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_the_request_id_of_the_caller_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_a_refusal_also_carries_a_request_id(client: TestClient) -> None:
    response = client.post("/texts", content=BODY, headers=AUTH)

    assert response.status_code == 415
    assert response.headers["X-Request-ID"]


# --- CORS ------------------------------------------------------------------


def test_a_preflight_request_is_answered(client: TestClient) -> None:
    """Un preflight no lleva credenciales, asi que CORS lo responde fuera del token.

    Starlette responde un preflight con ``200``; SPEC pedia ``204``. Ambos dicen
    lo mismo a un navegador -- el preflight nunca llega al recurso -- y forzar el
    otro codigo significaria envolver la biblioteca para cambiar un digito.
    """
    response = client.options(
        "/texts",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200


def test_the_allowed_methods_are_the_four_verbs_and_options(
    client: TestClient,
) -> None:
    response = client.options(
        "/texts",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    allowed = response.headers["access-control-allow-methods"]
    assert set(allowed.replace(" ", "").split(",")) == {
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",
    }


# --- el log de acceso ------------------------------------------------------


def test_a_request_is_logged_with_its_status_and_duration(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health")

    line = caplog.text
    assert "GET" in line
    assert "/health" in line
    assert "200" in line
    assert "ms" in line
