"""Fixtures compartidas para tests de middleware HTTP (T15)."""

from __future__ import annotations

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
CORS_ORIGIN = "https://app.example"


def build_client(
    *,
    max_body_bytes: int = 10485760,
    cors_allow_origins: tuple[str, ...] = (),
) -> Iterator[TestClient]:
    settings = Settings(
        service_api_token=TOKEN,
        mongo_uri="mongodb://test:27017",
        max_text_body_bytes=max_body_bytes,
        cors_allow_origins=cors_allow_origins,
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


@pytest.fixture
def cors_client() -> Iterator[TestClient]:
    """Un cliente que sólo permite el origen usado por los tests de CORS."""
    yield from build_client(cors_allow_origins=(CORS_ORIGIN,))

