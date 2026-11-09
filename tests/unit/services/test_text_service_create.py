"""Tests de TextService.create."""

from __future__ import annotations

import hashlib
import logging

import pytest

from app.errors import ChecksumAlreadyExistsError, PersistenceError
from app.request_context import request_id_context
from tests.unit.services.conftest import _command, _service, NOW
from tests.fakes.fake_text_repository import FakeTextRepository


async def test_create_log_has_request_id_and_safe_checksum(caplog) -> None:
    context_token = request_id_context.set("request-123")
    command = _command(text="private body", metadata={"secret": "private data"})

    try:
        with caplog.at_level(logging.INFO, logger="app.services.audit_logger"):
            await _service(FakeTextRepository()).create(command)

        message = caplog.text
        assert "request_id=request-123" in message
        assert "result=success" in message
        assert hashlib.sha256(b"abc123").hexdigest()[:12] in message
        assert "abc123" not in message
        assert "private body" not in message
        assert "private data" not in message
    finally:
        request_id_context.reset(context_token)


async def test_a_new_text_is_stored_with_both_timestamps() -> None:
    repository = FakeTextRepository()

    await _service(repository).create(_command(name="contrato.pdf"))

    assert repository.last_inserted is not None
    assert repository.last_inserted.checksum == "abc123"
    assert repository.last_inserted.text == "hello"
    assert repository.last_inserted.name == "contrato.pdf"
    assert repository.last_inserted.metadata == {}
    assert repository.last_inserted.created_at == NOW
    assert repository.last_inserted.updated_at == NOW


async def test_the_metadata_of_the_command_is_kept() -> None:
    repository = FakeTextRepository()

    await _service(repository).create(_command(metadata={"pages": 12}))

    assert repository.last_inserted is not None
    assert repository.last_inserted.metadata == {"pages": 12}


async def test_an_existing_checksum_is_refused_before_inserting() -> None:
    repository = FakeTextRepository()
    repository.should_exist_checksums.add("abc123")

    with pytest.raises(ChecksumAlreadyExistsError):
        await _service(repository).create(_command())

    assert repository.last_inserted is None


async def test_a_failing_repository_is_not_swallowed() -> None:
    repository = FakeTextRepository(insert_error=PersistenceError("mongo is down"))

    with pytest.raises(PersistenceError):
        await _service(repository).create(_command())
