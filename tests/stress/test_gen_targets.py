"""Tests de :mod:`tests.stress.scripts.gen_targets`.

Vegeta no puede inventar bodies: lee un fichero de targets y lo repite en bucle.
Como los cuatro verbos de este servicio exigen un checksum unico (un repetido
responde ``409`` y contamina la medicion), el generador es la pieza que hace
que el ataque mida escritura de verdad y no una avalancha de conflictos.

Se prueba aqui lo que es logica pura y no cuesta nada verificar: unicidad y
determinismo de los checksums, la forma exacta de los targets y los guardas
del CLI (token obligatorio).

Por que el formato JSON de Vegeta y no el HTTP legible
------------------------------------------------------
Vegeta acepta dos formatos de targets (``-format http`` y ``-format json``).
El HTTP legible **no admite cuerpos en linea**: la linea en blanco cierra la
peticion despues de las cabeceras, asi que un JSON escrito ahi se come como
cabecera y la siguiente linea de metodo acaba siendo "bad method". El formato
JSON lleva el cuerpo codificado en base64 dentro del propio target, que es lo
que este generador emite: un target por linea, sin ambiguaciones de parsing.

La siembra real contra el servicio vivo es verificacion manual de
``stress-plan.md`` T1, no un test.
"""

import base64
import json

import httpx

from tests.stress.scripts.gen_targets import (
    PreCleanReport,
    build_targets,
    generate_checksums,
    load_documents,
    main,
    pre_clean,
    write_targets,
)

BASE_URL = "http://stress.test:8082"
TOKEN = "tok-abc123"


def parse_targets(targets: str) -> list[dict]:
    """Decodifica el fichero de targets en los objetos que Vegeta vera.

    Cada línea es un target JSON -- el formato ``-format json`` de
    ``vegeta attack`` -- de modo que contar líneas es contar peticiones.
    """
    return [json.loads(line) for line in targets.strip().splitlines()]


def test_checksums_are_unique_and_exactly_the_requested_count():
    checksums = generate_checksums(1000)

    assert len(checksums) == 1000
    assert len(set(checksums)) == 1000
    assert all(len(value) == 64 for value in checksums)


def test_checksums_are_deterministic_for_a_given_seed():
    """Un seed fijo reproduce la misma corrida: los targets se comparan entre runs."""
    first = generate_checksums(50, seed=42)
    second = generate_checksums(50, seed=42)
    other = generate_checksums(50, seed=43)

    assert first == second
    assert first != other


def test_a_non_positive_count_is_rejected_at_the_source():
    try:
        generate_checksums(0)
    except ValueError as error:
        assert "count" in str(error)
    else:
        raise AssertionError("generate_checksums(0) debio lanzar ValueError")


def test_post_targets_are_json_lines_with_the_body_base64_encoded():
    """La forma textual del target es contrato con el parser de Vegeta.

    Se espera la estructura literal, construida a mano: si el test llamara a
    los mismos helpers que el codigo, no comprobaria nada. El body viaja en
    base64 dentro del target porque ``-format json`` lo exige.
    """
    targets = build_targets("POST", BASE_URL, TOKEN, ["abc123"])

    (target,) = parse_targets(targets)
    assert target == {
        "method": "POST",
        "url": f"{BASE_URL}/texts",
        "header": {
            "Content-Type": ["application/json"],
            "Authorization": [f"Bearer {TOKEN}"],
        },
        "body": base64.b64encode(
            b'{"checksum":"abc123","text":"stress payload 0"}'
        ).decode(),
    }


def test_get_targets_carry_the_token_and_the_query_param():
    targets = build_targets("GET", BASE_URL, TOKEN, ["abc123", "def456"])

    parsed = parse_targets(targets)
    assert len(parsed) == 2
    first, second = parsed
    assert first == {
        "method": "GET",
        "url": f"{BASE_URL}/texts?checksum=abc123",
        "header": {"Authorization": [f"Bearer {TOKEN}"]},
    }
    assert second["url"] == f"{BASE_URL}/texts?checksum=def456"


def test_put_targets_send_a_non_empty_name_so_the_service_cannot_answer_400():
    """``PUT {}`` es ``400`` por contrato; enviarlo seria un falso negativo."""
    targets = build_targets("PUT", BASE_URL, TOKEN, ["abc123"])

    (target,) = parse_targets(targets)
    assert target["header"]["Content-Type"] == ["application/json"]
    assert target["header"]["Authorization"] == [f"Bearer {TOKEN}"]
    payload = json.loads(base64.b64decode(target["body"]))
    assert payload["name"] == "stress-0"
    assert payload["name"] != ""


def test_delete_targets_use_the_query_param_and_carry_the_token():
    targets = build_targets("DELETE", BASE_URL, TOKEN, ["abc123"])

    assert parse_targets(targets) == [
        {
            "method": "DELETE",
            "url": f"{BASE_URL}/texts?checksum=abc123",
            "header": {"Authorization": [f"Bearer {TOKEN}"]},
        }
    ]


def test_an_unknown_verb_is_refused_instead_of_writing_a_broken_target():
    try:
        build_targets("PATCH", BASE_URL, TOKEN, ["abc123"])
    except ValueError as error:
        assert "PATCH" in str(error)
    else:
        raise AssertionError("un verbo desconocido debio lanzar ValueError")


def test_write_targets_creates_one_file_per_verb_with_one_line_each(tmp_path):
    checksums = generate_checksums(3, seed=7)

    written = write_targets(tmp_path, BASE_URL, TOKEN, checksums)

    assert set(written) == {"post", "get", "put", "delete"}
    for verb, path in written.items():
        assert path.parent == tmp_path
        parsed = parse_targets(path.read_text(encoding="utf-8"))
        assert len(parsed) == 3
        assert all(target["method"] == verb.upper() for target in parsed)


def test_writing_twice_with_the_same_seed_produces_byte_identical_files(tmp_path):
    first = write_targets(
        tmp_path / "a", BASE_URL, TOKEN, generate_checksums(10, seed=42)
    )
    second = write_targets(
        tmp_path / "b", BASE_URL, TOKEN, generate_checksums(10, seed=42)
    )

    for verb, path in first.items():
        assert path.read_bytes() == second[verb].read_bytes()


def test_load_posts_every_checksum_and_counts_409_as_already_there():
    """La siembra reanudable: un segundo ``--load`` no debe abortar por duplicados."""
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        status = 201 if len(seen) == 1 else 409
        return httpx.Response(status, json={"message": "OK"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    checksums = generate_checksums(4, seed=1)

    report = load_documents(BASE_URL, TOKEN, checksums, client=client)

    assert [item["checksum"] for item in seen] == checksums
    assert report.created == 1
    assert report.existing == 3


def test_load_sends_the_bearer_token_on_every_request():
    headers_seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers_seen.append(request.headers.get("Authorization"))
        return httpx.Response(201, json={"message": "OK"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    load_documents(BASE_URL, TOKEN, ["abc123"], client=client)

    assert headers_seen == [f"Bearer {TOKEN}"]


def test_pre_clean_deletes_every_target_and_counts_404_as_absent():
    """El pre-limpieado parte de base cero: un corrida crasheada deja 409.

    Un DELETE por checksum sirve a la vez de purga y de sondeo: si no existia
    responde ``404`` y no debe abortar; si existia, desaparece y el POST del
    ataque vuelve a medir escritura de verdad.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["checksum"])
        status = 200 if request.url.params["checksum"] == "abc123" else 404
        return httpx.Response(status, json={"message": "OK"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    report = pre_clean(BASE_URL, TOKEN, ["abc123", "def456"], client=client)

    assert seen == ["abc123", "def456"]
    assert report.deleted == 1
    assert report.missing == 1


def test_pre_clean_sends_the_token_and_raises_on_forbidden():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(401, json={"code": "UNAUTHORIZED"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    try:
        pre_clean(BASE_URL, TOKEN, ["abc123"], client=client)
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("un 401 durante la limpieza debio lanzar excepcion")


def test_the_cli_pre_cleans_only_when_the_flag_is_asked(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "tests.stress.scripts.gen_targets.pre_clean",
        lambda base_url, token, checksums: (
            calls.append(list(checksums))
            or PreCleanReport(deleted=0, missing=len(checksums))
        ),
    )

    clean = main(["--count", "3", "--pre-clean", "--out-dir", str(tmp_path / "a")])
    plain = main(["--count", "3", "--out-dir", str(tmp_path / "b")])

    assert clean == 0
    assert plain == 0
    assert [len(checksums) for checksums in calls] == [3]


def test_the_cli_refuses_to_run_without_the_token(capsys, monkeypatch, tmp_path):
    """Sin ``SERVICE_API_TOKEN`` no hay targets usables: fallar antes de escribir."""
    monkeypatch.delenv("SERVICE_API_TOKEN", raising=False)

    exit_code = main(["--count", "2", "--out-dir", str(tmp_path)])

    assert exit_code == 2
    assert "SERVICE_API_TOKEN" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_the_cli_writes_the_four_files_when_the_token_is_present(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVICE_API_TOKEN", TOKEN)

    exit_code = main(["--count", "5", "--seed", "42", "--out-dir", str(tmp_path)])

    assert exit_code == 0
    assert {path.name for path in tmp_path.iterdir()} == {
        "post.txt",
        "get.txt",
        "put.txt",
        "delete.txt",
    }
