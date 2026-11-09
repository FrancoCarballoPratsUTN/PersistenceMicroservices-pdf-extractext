"""Tests del orden que fija la SPEC (401 → 415 → 413 → 400)."""

from __future__ import annotations

from tests.unit.api.conftest import AUTH, JSON, small_client


def test_the_token_is_checked_before_the_body_size(
    small_client,
) -> None:
    response = small_client.post("/texts", content=b"x" * 500, headers={**JSON})

    assert response.status_code == 401


def test_the_content_type_is_checked_before_the_body_size(
    small_client,
) -> None:
    response = small_client.post(
        "/texts", content=b"x" * 500, headers={**AUTH, "Content-Type": "text/plain"}
    )

    assert response.status_code == 415


def test_the_content_type_is_checked_before_the_body_is_parsed(
    client,
) -> None:
    """Un cuerpo que ni siquiera es JSON se rechaza primero como tipo de medio
    incorrecto."""
    response = client.post(
        "/texts", content="{not json", headers={**AUTH, "Content-Type": "text/plain"}
    )

    assert response.status_code == 415
