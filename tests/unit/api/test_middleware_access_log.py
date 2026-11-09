"""Tests del log de acceso."""

from __future__ import annotations

import logging

from tests.unit.api.conftest import client


def test_a_request_is_logged_with_its_status_and_duration(
    client, caplog
) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health")

    line = caplog.text
    assert "GET" in line
    assert "/health" in line
    assert "200" in line
    assert "ms" in line


def test_the_access_log_includes_the_request_id_once(
    client, caplog
) -> None:
    request_id = "access-123"
    with caplog.at_level(logging.INFO, logger="app.api.middleware"):
        client.get("/health", headers={"X-Request-ID": request_id})

    records = [
        record for record in caplog.records if record.name == "app.api.middleware"
    ]
    assert len(records) == 1
    assert records[0].request_id == request_id
