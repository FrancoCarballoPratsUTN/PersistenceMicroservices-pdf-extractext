"""Tests del cabecera X-Request-ID."""

from __future__ import annotations

from tests.unit.api.conftest import AUTH, BODY, client


def test_a_request_id_is_generated_when_the_caller_sends_none(client) -> None:
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_the_request_id_of_the_caller_is_echoed(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_an_invalid_request_id_is_replaced(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id"})

    assert response.headers["X-Request-ID"] != "bad id"


def test_a_long_request_id_is_replaced(client) -> None:
    request_id = "x" * 129
    response = client.get("/health", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] != request_id


def test_a_refusal_also_carries_a_request_id(client) -> None:
    response = client.post("/texts", content=BODY, headers=AUTH)

    assert response.status_code == 415
    assert response.headers["X-Request-ID"]


def test_a_401_echoes_the_request_id(client) -> None:
    response = client.get("/texts?checksum=x", headers={"X-Request-ID": "auth-123"})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "auth-123"
