"""Tests del mapeo documento -> dict de API (T12).

El cliente de Go decodifica estos seis miembros por nombre, asi que el test
enuncia todo el contrato: las seis claves, sin nulos, y marcas de tiempo RFC 3339
en UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.repositories.serialization import to_api_dict
from app.use_cases.ports import StoredText

MOMENT = datetime(2026, 10, 1, 12, 34, 56, 789_000, tzinfo=UTC)


def _stored(**changes: object) -> StoredText:
    fields: dict[str, object] = {
        "checksum": "9f86d081",
        "text": "contenido extraido del PDF...",
        "name": "contrato.pdf",
        "created_at": MOMENT,
        "updated_at": MOMENT,
        "metadata": {"pages": 12},
    }
    fields.update(changes)
    return StoredText(**fields)  # type: ignore[arg-type]


def test_the_six_members_of_the_contract_are_present() -> None:
    assert set(to_api_dict(_stored())) == {
        "checksum",
        "text",
        "name",
        "metadata",
        "created_at",
        "updated_at",
    }


def test_every_member_carries_the_stored_value() -> None:
    assert to_api_dict(_stored()) == {
        "checksum": "9f86d081",
        "text": "contenido extraido del PDF...",
        "name": "contrato.pdf",
        "metadata": {"pages": 12},
        "created_at": "2026-10-01T12:34:56.789Z",
        "updated_at": "2026-10-01T12:34:56.789Z",
    }


def test_the_timestamps_end_with_z() -> None:
    document = to_api_dict(_stored())

    assert document["created_at"].endswith("Z")
    assert document["updated_at"].endswith("Z")


def test_sub_millisecond_precision_is_truncated() -> None:
    """Siete microsegundos estan por debajo de la precision que promete el
    contrato."""
    document = to_api_dict(_stored(created_at=datetime(2026, 1, 2, 3, 4, 5, 7, UTC)))

    assert document["created_at"] == "2026-01-02T03:04:05.000Z"


def test_a_timestamp_without_a_zone_is_read_as_utc() -> None:
    """MongoDB devuelve datetimes sin zona; por contrato son UTC."""
    document = to_api_dict(_stored(created_at=datetime(2026, 1, 2, 3, 4, 5, 70000)))

    assert document["created_at"] == "2026-01-02T03:04:05.070Z"


def test_a_timestamp_in_another_zone_is_converted_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))

    document = to_api_dict(
        _stored(created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=plus_two))
    )

    assert document["created_at"] == "2026-01-02T01:04:05.000Z"


def test_an_absent_name_is_sent_as_an_empty_string() -> None:
    """El cliente de Go decodifica una cadena ausente como su valor cero; nosotros
    la enviamos."""
    document = to_api_dict(_stored(name=None))

    assert document["name"] == ""


def test_absent_metadata_is_sent_as_an_empty_object() -> None:
    document = to_api_dict(_stored(metadata=None))

    assert document["metadata"] == {}
