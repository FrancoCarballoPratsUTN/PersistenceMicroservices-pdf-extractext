"""Tests del middleware de límite de cuerpo (413 Payload Too Large)."""

from __future__ import annotations

from tests.unit.api.conftest import AUTH, JSON, small_client
from tests.unit.api.helpers import _send_body_through_limit


def test_a_body_over_the_limit_is_refused(small_client) -> None:
    response = small_client.post(
        "/texts",
        content='{"text":"' + "x" * 200 + '"}',
        headers={**AUTH, **JSON},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_a_body_exactly_at_the_limit_is_accepted(small_client) -> None:
    padding = 100 - len('{"text":"","checksum":"abc123"}')
    body = '{"text":"' + "x" * padding + '","checksum":"abc123"}'

    response = small_client.post("/texts", content=body, headers={**AUTH, **JSON})

    assert len(body) == 100
    assert response.status_code == 201


def test_a_body_over_the_ten_mib_default_is_refused(client) -> None:
    response = client.post(
        "/texts",
        content=b"x" * (11 * 1024 * 1024),
        headers={**AUTH, **JSON},
    )

    assert response.status_code == 413


def test_a_get_without_a_body_is_not_refused(small_client) -> None:
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
