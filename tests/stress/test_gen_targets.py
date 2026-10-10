"""Tests de :mod:`tests.stress.scripts.gen_targets`.

Cubre la lógica pura (unicidad, serialización de targets, escritura de
ficheros) y los dos efectos HTTP (purga y siembra) con un cliente mock. El
stress real lo hacen k6 y vegeta, no pytest: aquí sólo se garantiza que los
targets que Vegeta atacará tienen la forma correcta.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import Mock

import httpx
import pytest

from tests.stress.scripts.gen_targets import (
    build_targets,
    generate_checksums,
    load_documents,
    main,
    pre_clean,
    write_targets,
)

BASE_URL = "http://stress.test:8082"
TOKEN = "tok-abc123"


def targets_of(targets: str) -> list[dict]:
    """Decodifica el fichero de targets: una línea es una petición."""
    return [json.loads(line) for line in targets.splitlines()]


def fake_client(*statuses: int) -> Mock:
    """Cliente httpx falso: responde un estado por llamada, en orden."""

    def responses() -> list[Mock]:
        return [Mock(status_code=status) for status in statuses]

    client = Mock()
    client.post.side_effect = responses()
    client.delete.side_effect = responses()
    return client


def test_checksums_are_unique_and_reproducible():
    first = generate_checksums(1000, seed=42)

    assert first == generate_checksums(1000, seed=42)
    assert first != generate_checksums(1000, seed=43)
    assert len(set(first)) == 1000
    assert all(len(checksum) == 64 for checksum in first)


def test_checksums_reject_a_non_positive_count():
    with pytest.raises(ValueError, match="count"):
        generate_checksums(0)


def test_post_target_is_a_base64_json_line():
    (target,) = targets_of(build_targets("POST", BASE_URL, TOKEN, ["abc123"]))

    assert target["method"] == "POST"
    assert target["url"] == f"{BASE_URL}/texts"
    assert target["header"]["Authorization"] == [f"Bearer {TOKEN}"]
    assert target["header"]["Content-Type"] == ["application/json"]
    assert json.loads(base64.b64decode(target["body"])) == {
        "checksum": "abc123",
        "text": "stress payload 0",
    }


def test_get_and_delete_targets_use_the_query_param():
    for method in ("GET", "DELETE"):
        (target,) = targets_of(build_targets(method, BASE_URL, TOKEN, ["abc123"]))
        assert target["method"] == method
        assert target["url"] == f"{BASE_URL}/texts?checksum=abc123"
        assert target["header"] == {"Authorization": [f"Bearer {TOKEN}"]}


def test_put_target_sends_a_non_empty_name():
    """``PUT {}`` es ``400`` por contrato; enviarlo sería un falso negativo."""
    (target,) = targets_of(build_targets("PUT", BASE_URL, TOKEN, ["abc123"]))

    assert json.loads(base64.b64decode(target["body"]))["name"] == "stress-0"


def test_an_unknown_verb_is_rejected():
    with pytest.raises(ValueError, match="PATCH"):
        build_targets("PATCH", BASE_URL, TOKEN, ["abc123"])


def test_write_targets_writes_one_file_per_verb(tmp_path):
    written = write_targets(tmp_path, BASE_URL, TOKEN, generate_checksums(3, seed=7))

    assert set(written) == {"post", "get", "put", "delete"}
    for verb, path in written.items():
        parsed = targets_of(path.read_text(encoding="utf-8"))
        assert len(parsed) == 3
        assert all(target["method"] == verb.upper() for target in parsed)


def test_pre_clean_counts_deleted_and_missing():
    client = fake_client(200, 404)

    report = pre_clean(BASE_URL, TOKEN, ["abc123", "def456"], client=client)

    assert (report.deleted, report.missing) == (1, 1)


def test_pre_clean_propagates_an_unexpected_status():
    client = Mock()
    client.delete.return_value = Mock(
        status_code=401,
        raise_for_status=Mock(
            side_effect=httpx.HTTPStatusError("401", request=Mock(), response=Mock())
        ),
    )

    with pytest.raises(httpx.HTTPStatusError):
        pre_clean(BASE_URL, TOKEN, ["abc123"], client=client)


def test_load_documents_counts_created_and_existing():
    client = fake_client(201, 409)

    report = load_documents(BASE_URL, TOKEN, ["abc123", "def456"], client=client)

    assert (report.created, report.existing) == (1, 1)


def test_cli_needs_the_token_and_writes_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("SERVICE_API_TOKEN", raising=False)

    exit_code = main(["--count", "2", "--out-dir", str(tmp_path)])

    assert exit_code == 2
    assert "SERVICE_API_TOKEN" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_cli_writes_the_four_files_with_a_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)

    exit_code = main(["--count", "5", "--seed", "42", "--out-dir", str(tmp_path)])

    assert exit_code == 0
    assert {path.name for path in tmp_path.iterdir()} == {
        "post.txt",
        "get.txt",
        "put.txt",
        "delete.txt",
    }
