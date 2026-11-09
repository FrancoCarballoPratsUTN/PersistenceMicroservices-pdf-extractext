"""Tests del middleware de tipo de contenido (415 Unsupported Media Type)."""

from __future__ import annotations

from tests.unit.api.conftest import AUTH, BODY, JSON, client


def test_a_post_declaring_json_is_accepted(client) -> None:
    response = client.post("/texts", content=BODY, headers={**AUTH, **JSON})

    assert response.status_code == 201


def test_a_post_that_is_not_json_is_refused(client) -> None:
    response = client.post(
        "/texts", content=BODY, headers={**AUTH, "Content-Type": "text/plain"}
    )

    assert response.status_code == 415
    assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_a_put_that_is_not_json_is_refused(client) -> None:
    response = client.put(
        "/texts",
        params={"checksum": "abc123"},
        content=BODY,
        headers={**AUTH, "Content-Type": "text/plain"},
    )

    assert response.status_code == 415


def test_a_post_without_a_content_type_is_refused(client) -> None:
    response = client.post("/texts", content=BODY, headers=AUTH)

    assert response.status_code == 415


def test_json_with_a_charset_is_still_json(client) -> None:
    response = client.post(
        "/texts",
        content=BODY,
        headers={**AUTH, "Content-Type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 201


def test_a_get_without_a_content_type_is_not_refused(client) -> None:
    response = client.get("/texts", params={"checksum": "abc123"}, headers=AUTH)

    assert response.status_code == 404


def test_a_refusal_names_the_content_type_it_wanted(client) -> None:
    response = client.post("/texts", content=BODY, headers=AUTH)

    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 415
