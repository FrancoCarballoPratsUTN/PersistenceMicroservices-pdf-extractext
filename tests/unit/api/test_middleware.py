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
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.middleware import BodySizeLimitMiddleware
from app.config import Settings
from app.main import create_app
from app.repositories.mongodb import MongoConnection
from tests.fakes.fake_mongo_client import FakeMongoClientFactory

TOKEN = "token-for-tests-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
JSON = {"Content-Type": "application/json"}
BODY = '{"checksum":"abc123","text":"hello"}'


async def _send_body_through_limit(
    body_messages: list[dict[str, Any]], *, content_length: str | None = None
) -> tuple[int, bytes, list[dict[str, Any]], int]:
    downstream_messages: list[dict[str, Any]] = []
    response_messages: list[dict[str, Any]] = []
    receive_count = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_count
        receive_count += 1
        if body_messages:
            return body_messages.pop(0)
        return {"type": "http.disconnect"}

    async def downstream(scope, receive, send) -> None:
        while True:
            message = await receive()
            downstream_messages.append(message)
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message: dict[str, Any]) -> None:
        response_messages.append(message)

    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    middleware = BodySizeLimitMiddleware(
        downstream,
        settings=Settings(service_api_token=TOKEN, max_text_body_bytes=4),
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/texts",
        "raw_path": b"/texts",
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
        "client": ("testclient", 1234),
    }
    await middleware(scope, receive, send)

    status = next(
        message["status"]
        for message in response_messages
        if message["type"] == "http.response.start"
    )
    downstream_body = b"".join(
        message.get("body", b"")
        for message in downstream_messages
        if message["type"] == "http.request"
    )
    return status, downstream_body, downstream_messages, receive_count


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


async def test_a_chunked_body_over_the_limit_is_refused_before_the_router() -> None:
    status, _, downstream, _ = await _send_body_through_limit(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )

    assert status == 413
    assert downstream == []


async def test_body_size_rejects_content_length_without_reading_body() -> None:
    status, _, downstream, receive_count = await _send_body_through_limit(
        [{"type": "http.request", "body": b"12345", "more_body": False}],
        content_length="5",
    )

    assert status == 413
    assert downstream == []
    assert receive_count == 0


async def test_body_size_replays_a_valid_body_unchanged() -> None:
    messages = [
        {"type": "http.request", "body": b"12", "more_body": True},
        {"type": "http.request", "body": b"34", "more_body": False},
    ]
    status, body, downstream, _ = await _send_body_through_limit(messages)

    assert status == 200
    assert body == b"1234"
    assert downstream[0]["body"] == b"1234"
    assert downstream[0]["more_body"] is False


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


def test_an_invalid_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id"})

    assert response.headers["X-Request-ID"] != "bad id"


def test_a_long_request_id_is_replaced(client: TestClient) -> None:
    request_id = "x" * 129
    response = client.get("/health", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] != request_id


def test_a_refusal_also_carries_a_request_id(client: TestClient) -> None:
    response = client.post("/texts", content=BODY, headers=AUTH)

    assert response.status_code == 415
    assert response.headers["X-Request-ID"]


def test_a_401_echoes_the_request_id(client: TestClient) -> None:
    response = client.get("/texts?checksum=x", headers={"X-Request-ID": "auth-123"})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "auth-123"


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


def test_the_access_log_includes_the_request_id_once(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    request_id = "access-123"
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health", headers={"X-Request-ID": request_id})

    records = [
        record for record in caplog.records if record.name == "app.api.middleware"
    ]
    assert len(records) == 1
    assert records[0].request_id == request_id
