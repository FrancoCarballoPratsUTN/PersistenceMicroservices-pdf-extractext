"""Helpers compartidos para tests de TextService."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.text_service import TextService
from app.use_cases.ports import CreateTextCommand
from tests.fakes.fake_text_repository import FakeTextRepository

NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)


def _service(repository: FakeTextRepository) -> TextService:
    return TextService(repository, now_factory=lambda: NOW)


def _command(**changes: Any) -> CreateTextCommand:
    fields: dict[str, Any] = {"checksum": "abc123", "text": "hello"}
    fields.update(changes)
    return CreateTextCommand(**fields)
