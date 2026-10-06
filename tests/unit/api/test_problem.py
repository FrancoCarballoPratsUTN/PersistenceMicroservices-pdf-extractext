"""Tests del documento problem de RFC 9457 y de los handlers que lo emiten."""

import logging

import httpx
import pytest
from fastapi import FastAPI
from starlette.exceptions import HTTPException

from app.api.exception_handlers import register_exception_handlers
from app.api.problem import PROBLEM_MEDIA_TYPE
from app.errors import (
    ChecksumAlreadyExistsError,
    InternalError,
    ResourceNotFoundError,
    ServiceError,
    TextNotFoundError,
)
from tests.unit.fixtures.error_cases import ALL_ERROR_CLASSES

SIX_MEMBERS = {"type", "title", "status", "detail", "instance", "code"}


def make_app_with_route(path: str = "/texts", on_call=None) -> FastAPI:
    """Crea una app mínima con los handlers de problem details instalados."""
    app = FastAPI()
    register_exception_handlers(app)
    if on_call:
        app.add_api_route(path, on_call, methods=["GET"])
    return app


async def send_request(
    app: FastAPI, method: str, url: str, raise_app: bool = True
) -> httpx.Response:
    """Envía una petición in-process mediante httpx ASGI transport."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.request(method, url)


@pytest.mark.parametrize("error_cls", ALL_ERROR_CLASSES, ids=lambda cls: cls.__name__)
async def test_every_error_class_answers_with_its_status_and_the_six_members(error_cls):
    async def fail():
        raise error_cls()

    app = make_app_with_route(on_call=fail)
    response = await send_request(app, "GET", "/texts")

    assert response.status_code == error_cls.status
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": error_cls.type_uri,
        "title": error_cls.title,
        "status": error_cls.status,
        "detail": error_cls().default_detail,
        "instance": "/texts",
        "code": error_cls.code,
    }


async def test_the_detail_of_this_occurrence_reaches_the_client():
    async def fail():
        raise ChecksumAlreadyExistsError(
            "A document with checksum 'abc' already exists."
        )

    response = await send_request(make_app_with_route(on_call=fail), "GET", "/texts")
    assert response.json()["detail"] == "A document with checksum 'abc' already exists."


async def test_two_occurrences_of_one_class_share_the_title_and_differ_in_detail():
    async def fail(checksum: str = ""):
        raise TextNotFoundError(f"No document exists for checksum {checksum!r}.")

    app = make_app_with_route(on_call=fail)
    first = (await send_request(app, "GET", "/texts?checksum=aaa")).json()
    second = (await send_request(app, "GET", "/texts?checksum=bbb")).json()

    assert first["title"] == second["title"] == TextNotFoundError.title
    assert first["detail"] != second["detail"]


async def test_instance_redacts_query_params_completely():
    checksum = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"

    async def fail():
        raise TextNotFoundError()

    app = make_app_with_route(on_call=fail)
    response = await send_request(
        app, "GET", f"/texts?checksum={checksum}&reason=missing"
    )

    assert response.json()["instance"] == "/texts?checksum=<redacted>&reason=<redacted>"
    assert checksum not in response.text
    assert "missing" not in response.text
    assert "testserver" not in response.text


async def test_instance_is_the_bare_path_when_the_request_carries_no_query():
    async def fail():
        raise TextNotFoundError()

    response = await send_request(make_app_with_route(on_call=fail), "GET", "/texts")
    assert response.json()["instance"] == "/texts"


async def test_an_unknown_route_answers_a_404_problem_about_the_route():
    response = await send_request(make_app_with_route(), "GET", "/no-such-route")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "/problems/not_found",
        "title": "Resource not found",
        "status": 404,
        "detail": ResourceNotFoundError.default_detail,
        "instance": "/no-such-route",
        "code": "NOT_FOUND",
    }


async def test_a_verb_the_route_does_not_accept_answers_a_405_problem():
    response = await send_request(
        make_app_with_route(on_call=lambda: None), "POST", "/texts"
    )

    assert response.status_code == 405
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"


async def test_a_status_without_an_error_class_still_answers_a_six_member_problem():
    async def fail():
        raise HTTPException(status_code=418)

    response = await send_request(make_app_with_route(on_call=fail), "GET", "/texts")
    assert response.status_code == 418
    assert set(response.json()) == SIX_MEMBERS


async def test_an_unexpected_exception_answers_a_500_that_leaks_nothing():
    internal = "mongodb://admin:hunter2@db:27017 timed out"

    async def fail():
        raise RuntimeError(internal)

    response = await send_request(
        make_app_with_route(on_call=fail), "GET", "/texts", raise_app=False
    )

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert response.json()["detail"] == InternalError.default_detail
    assert internal not in response.text
    assert "RuntimeError" not in response.text


async def test_an_unexpected_exception_is_logged_with_its_traceback(caplog):
    async def fail():
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="app.api.exception_handlers"):
        await send_request(
            make_app_with_route(on_call=fail), "GET", "/texts", raise_app=False
        )

    record = caplog.records[-1]
    assert "/texts" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


async def test_a_service_error_is_answered_by_its_own_class_not_by_the_catch_all():
    async def fail():
        raise ChecksumAlreadyExistsError()

    response = await send_request(
        make_app_with_route(on_call=fail), "GET", "/texts", raise_app=False
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CHECKSUM_ALREADY_EXISTS"
    assert issubclass(ChecksumAlreadyExistsError, ServiceError)
