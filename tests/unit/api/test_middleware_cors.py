"""Tests de CORS."""

from __future__ import annotations

from tests.unit.api.conftest import AUTH, BODY, client, cors_client

CORS_ORIGIN = "https://app.example"


def test_cors_is_closed_by_default(client) -> None:
    response = client.options(
        "/texts",
        headers={
            "Origin": CORS_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_a_configured_origin_is_answered_in_a_preflight(
    cors_client,
) -> None:
    """Un preflight no lleva credenciales, así que CORS lo responde fuera del token.

    Starlette responde un preflight con ``200``; SPEC pedía ``204``. Ambos dicen
    lo mismo a un navegador -- el preflight nunca llega al recurso -- y forzar el
    otro código significaría envolver la biblioteca para cambiar un dígito.
    """
    response = cors_client.options(
        "/texts",
        headers={
            "Origin": CORS_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == CORS_ORIGIN


def test_an_unconfigured_origin_does_not_receive_cors_headers(
    cors_client,
) -> None:
    response = cors_client.options(
        "/texts",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_the_allowed_methods_are_the_four_verbs_and_options(
    cors_client,
) -> None:
    response = cors_client.options(
        "/texts",
        headers={
            "Origin": CORS_ORIGIN,
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


def test_the_preflight_allows_the_request_id_header(
    cors_client,
) -> None:
    response = cors_client.options(
        "/texts",
        headers={
            "Origin": CORS_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Request-ID",
        },
    )

    assert "x-request-id" in response.headers["access-control-allow-headers"].lower()
