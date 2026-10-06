"""Tests del middleware de token bearer en :mod:`app.api.auth`.

Cada petición atraviesa la raíz de composición real (``app.main.create_app``) para
que la suite pruebe el cableado y no solo la función: un middleware que nunca se
registrara pasaría igualmente un test que lo llamara directamente.

El rechazo es deliberadamente uniforme. SPEC 3.2 pide un único ``detail``
idéntico en los cuatro modos de fallo, porque decirle al llamante *por qué* se
rechazó un token es un oráculo para enumerar tokens. El log del servidor conserva
en cambio la razón real, así que se afirman las dos mitades de ese intercambio:
el cuerpo es uniforme, el log es específico, y ninguno jamás lleva el token.
"""

import logging

import httpx
import pytest
from fastapi import FastAPI

from app.config import ConfigurationError, Settings
from app.main import create_app

TOKEN = "s3cr3t-token"
WRONG_TOKEN = "wrong-token"
REJECTION_DETAIL = "Missing or invalid bearer token."
CHECKSUM = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"

# Todas las formas en que un llamante puede equivocarse con la autorización. Todas
# deben responder el mismo estado, el mismo title y el mismo detail.
BAD_CREDENTIALS = [
    pytest.param(None, id="header-ausente"),
    pytest.param("", id="header-vacio"),
    pytest.param(f"Bearer {WRONG_TOKEN}", id="valor-incorrecto"),
    pytest.param(f"Basic {TOKEN}", id="esquema-distinto"),
    pytest.param("Bearer", id="sin-valor"),
    pytest.param(TOKEN, id="sin-esquema"),
]

PROTECTED_VERBS = [
    pytest.param("GET", id="get"),
    pytest.param("POST", id="post"),
    pytest.param("PUT", id="put"),
    pytest.param("DELETE", id="delete"),
]


def build_app(token: str = TOKEN) -> FastAPI:
    """La app real más las rutas sobre las que el middleware tiene opinión.

    El stub protegido vive en ``/private``, no en ``/texts``: el router real ya
    responde ``/texts``, y FastAPI conserva primero la ruta registrada, de modo
    que un stub declarado ahí sería código muerto en cuanto se añadiera un verbo.
    Estos tests tratan del middleware, así que no deben depender de qué rutas
    declare por casualidad el servicio.

    Args:
        token: El token que la app aceptará.

    Returns:
        Una app construida por la raíz de composición, con ``/private`` protegido
        y las dos sondas abiertas, exactamente como declarará el servicio.
    """
    from app.repositories.mongodb import MongoConnection
    from tests.fakes.fake_mongo_client import FakeMongoClientFactory

    settings = Settings(service_api_token=token)
    mongo = MongoConnection(settings, client_factory=FakeMongoClientFactory())
    app = create_app(settings, connection=mongo)

    # Para los tests de auth, la disponibilidad no depende de un ciclo de vida
    # Mongo real: las sondas están abiertas y la disponibilidad debería ser OK al
    # comprobar sin credenciales.
    async def _ready_ok() -> bool:
        return True

    app.state.readiness_check = _ready_ok

    @app.get("/private")
    async def private() -> dict[str, str]:
        return {"message": "OK", "checksum": CHECKSUM}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ok", "mongo": "ok"}

    return app


async def send_request(
    app: FastAPI, method: str, url: str, header: str | None = None
) -> httpx.Response:
    """Envía una petición en proceso a ``app``.

    Args:
        app: La aplicación a llamar.
        method: Verbo HTTP.
        url: Ruta y query, relativas a ``testserver``.
        header: Valor de la cabecera ``Authorization``. ``None`` omite la cabecera
            entera, lo cual es distinto de enviarla vacía.

    Returns:
        La respuesta, una vez ejecutado todo el stack ASGI.
    """
    headers = {"Authorization": header} if header is not None else None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        return await client.request(method, url, headers=headers)


async def test_a_request_without_credentials_is_rejected():
    response = await send_request(build_app(), "GET", "/private")

    assert response.status_code == 401


@pytest.mark.parametrize("header", BAD_CREDENTIALS)
async def test_every_wrong_credential_answers_401_with_the_same_detail(header):
    response = await send_request(build_app(), "GET", "/private", header)

    assert response.status_code == 401
    assert response.json()["detail"] == REJECTION_DETAIL
    assert response.json()["title"] == "Unauthorized"


async def test_the_rejection_is_a_problem_document():
    response = await send_request(build_app(), "GET", "/private")

    assert response.json() == {
        "type": "/problems/unauthorized",
        "title": "Unauthorized",
        "status": 401,
        "detail": REJECTION_DETAIL,
        "instance": "/private",
        "code": "UNAUTHORIZED",
    }


async def test_the_rejection_uses_the_problem_media_type():
    response = await send_request(build_app(), "GET", "/private")

    assert response.headers["content-type"] == "application/problem+json"


async def test_the_rejection_challenges_with_the_bearer_scheme():
    response = await send_request(build_app(), "GET", "/private")

    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("method", PROTECTED_VERBS)
async def test_every_verb_on_a_protected_path_is_rejected(method):
    response = await send_request(build_app(), method, "/private")

    assert response.status_code == 401


async def test_a_valid_token_reaches_the_route():
    response = await send_request(build_app(), "GET", "/private", f"Bearer {TOKEN}")

    assert response.status_code == 200
    assert response.json() == {"message": "OK", "checksum": CHECKSUM}


@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
async def test_the_scheme_is_read_case_insensitively(scheme):
    response = await send_request(build_app(), "GET", "/private", f"{scheme} {TOKEN}")

    assert response.status_code == 200


async def test_the_token_value_is_case_sensitive():
    response = await send_request(build_app(), "GET", "/private", "Bearer S3CR3T-TOKEN")

    assert response.status_code == 401


async def test_the_presented_token_never_reaches_the_response_body():
    header = f"Bearer {WRONG_TOKEN}"

    response = await send_request(build_app(), "GET", "/private", header)

    assert WRONG_TOKEN not in response.text


async def test_neither_token_ever_reaches_the_log(caplog):
    with caplog.at_level(logging.DEBUG, logger="app.api.auth"):
        await send_request(build_app(), "GET", "/private", f"Bearer {WRONG_TOKEN}")
        await send_request(build_app(), "GET", "/private", f"Bearer {TOKEN}")

    messages = [record.getMessage() for record in caplog.records]
    assert messages, "the refusal is expected to leave a trace in the log"
    assert all(TOKEN not in message for message in messages)
    assert all(WRONG_TOKEN not in message for message in messages)


async def test_the_log_records_why_each_credential_was_refused(caplog):
    """Una razón por modo de fallo, para que el log sirva de algo.

    Las cuatro cabeceras son los cuatro casos de SPEC 3.2, y cada uno falla en un
    paso distinto, que es lo que hace que las razones difieran.
    """
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        for header in [None, "Bearer", f"Bearer {WRONG_TOKEN}", f"Basic {TOKEN}"]:
            await send_request(build_app(), "GET", "/private", header)

    reasons = {record.getMessage().rsplit(": ", 1)[-1] for record in caplog.records}

    assert len(reasons) == 4, f"each refusal mode needs its own reason: {reasons}"


async def test_an_unknown_route_is_refused_before_it_is_routed():
    response = await send_request(build_app(), "GET", "/no-such-route")

    assert response.status_code == 401


async def test_the_refusal_log_names_the_route_it_refused(caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        await send_request(build_app(), "GET", "/private")

    assert "/private" in caplog.records[-1].getMessage()


async def test_the_refusal_log_does_not_carry_the_checksum(caplog):
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        await send_request(build_app(), "GET", f"/private?checksum={CHECKSUM}")

    messages = [record.getMessage() for record in caplog.records]
    assert all(CHECKSUM not in message for message in messages)


async def test_health_answers_without_credentials():
    response = await send_request(build_app(), "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_answers_without_credentials():
    response = await send_request(build_app(), "GET", "/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mongo": "ok"}


async def test_an_open_route_stays_open_even_with_a_wrong_token():
    response = await send_request(
        build_app(), "GET", "/health", f"Bearer {WRONG_TOKEN}"
    )

    assert response.status_code == 200


async def test_the_app_refuses_to_build_without_a_token_in_the_environment(monkeypatch):
    monkeypatch.delenv("SERVICE_API_TOKEN", raising=False)

    with pytest.raises(ConfigurationError, match="SERVICE_API_TOKEN"):
        create_app()
