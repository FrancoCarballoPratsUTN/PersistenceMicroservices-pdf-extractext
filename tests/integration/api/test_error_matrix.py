"""Las once filas de la matriz de SPEC 6.2, pedidas por HTTP real (T16).

T2 demostró las filas como atributos de clase y T3 demostró la forma del
documento. Ninguno demostró la parte de la que depende el orquestador: que una
*petición real* provoque la fila que dice. Este módulo cierra ese hueco. Cada
fila se provoca como lo provocaría un cliente y la respuesta se lee del cable,
de modo que una fila inalcanzable fallaría aquí en lugar de pasar en silencio.

Las filas son datos, no código
------------------------------
Una fila es una promesa ``(status, code)`` más la petición que la dispara, de
modo que la matriz es una sola tabla y cada test puede recorrerla comprobando
además algo propio: el estado y el código, luego la posibilidad de analizar el
cuerpo.

Los fallos se inyectan en la *base de datos*, no en la app
---------------------------------------------------------
Una fila que necesita que MongoDB se comporte mal recibe un cliente fake que
lanza excepción en una lectura. No se parchea nada dentro de ``app/``, así que
el mapeo de un fallo del driver a un estado es el de producción: ``503`` demuestra
que el repositorio traduce un ``PyMongoError``, y ``500`` que la red de seguridad
responde a una excepción que nadie clasificó.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pymongo.errors import ServerSelectionTimeoutError

from app.api.problem import PROBLEM_MEDIA_TYPE
from app.config import Settings
from app.main import create_app
from app.repositories.mongodb import MongoConnection
from tests.fakes.fake_mongo_client import FakeMongoClientFactory

TOKEN = "token-for-tests-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NEW_TEXT = {"checksum": "abc", "text": "hello"}
NEW_NAME = {"name": "otro.pdf"}

# Lo bastante pequeña para que enviar un cuerpo sobredimensionado sea barato, y lo
# bastante grande para que todos los demás cuerpos de este módulo queden por debajo.
BODY_LIMIT = 512

# Los miembros que se le deben a un cliente ante un fallo: los cinco de RFC 9457 3.1
# más la extensión ``code`` de 3.2. Nada más, así que una clave de más es un cambio
# de contrato.
CONTRACT_MEMBERS = {"type", "title", "status", "detail", "instance", "code"}


@dataclass(frozen=True, slots=True)
class Row:
    """Una fila de la matriz de SPEC 6.2, y la petición que la provoca.

    Args:
        status: El estado HTTP que la fila le debe al cliente.
        code: El nombre legible por máquina que el cuerpo debe llevar.
        provoke: Envía la petición que dispara la fila y devuelve la respuesta.
        find_error: Lo que la base de datos fake lanza en una lectura, para las dos
            filas que necesitan una base de datos rota para ser alcanzables.
        rethrow: Si el cliente de test vuelve a lanzar una excepción no controlada.
            Solo la fila ``500`` lo desactiva, porque ahí la excepción no
            controlada es justamente el comportamiento bajo prueba: Starlette envía
            su respuesta y luego la vuelve a lanzar, lo cual es correcto para un
            servidor e ilegible para un test.
    """

    status: int
    code: str
    provoke: Callable[[TestClient], Response]
    find_error: Exception | None = None
    rethrow: bool = True


def _post_without_credentials(client: TestClient) -> Response:
    return client.post("/texts", json=NEW_TEXT)


def _get_without_credentials(client: TestClient) -> Response:
    return client.get("/texts?checksum=abc")


def _put_without_credentials(client: TestClient) -> Response:
    return client.put("/texts?checksum=abc", json=NEW_NAME)


def _delete_without_credentials(client: TestClient) -> Response:
    return client.delete("/texts?checksum=abc")


def _post_a_body_that_is_not_json(client: TestClient) -> Response:
    headers = {**AUTH, "Content-Type": "text/plain"}
    return client.post("/texts", content=b"hello", headers=headers)


def _post_a_body_over_the_limit(client: TestClient) -> Response:
    body = {"checksum": "big", "text": "x" * BODY_LIMIT}
    return client.post("/texts", json=body, headers=AUTH)


def _post_the_same_checksum_twice(client: TestClient) -> Response:
    client.post("/texts", json=NEW_TEXT, headers=AUTH)
    return client.post("/texts", json=NEW_TEXT, headers=AUTH)


def _put_an_immutable_field(client: TestClient) -> Response:
    return client.put("/texts?checksum=abc", json={"text": "otro"}, headers=AUTH)


def _get_without_a_checksum(client: TestClient) -> Response:
    return client.get("/texts", headers=AUTH)


def _read_missing_text(client: TestClient) -> Response:
    return client.get("/texts?checksum=ghost", headers=AUTH)


def _read_an_unknown_route(client: TestClient) -> Response:
    return client.get("/nowhere", headers=AUTH)


def _write_with_a_verb_the_route_refuses(client: TestClient) -> Response:
    return client.patch("/texts", headers=AUTH)


def _read_over_a_broken_database(client: TestClient) -> Response:
    return client.get("/texts?checksum=abc", headers=AUTH)


ROWS = [
    Row(409, "CHECKSUM_ALREADY_EXISTS", _post_the_same_checksum_twice),
    Row(404, "TEXT_NOT_FOUND", _read_missing_text),
    Row(401, "UNAUTHORIZED", _post_without_credentials),
    Row(400, "VALIDATION_ERROR", _get_without_a_checksum),
    Row(400, "IMMUTABLE_FIELD", _put_an_immutable_field),
    Row(413, "PAYLOAD_TOO_LARGE", _post_a_body_over_the_limit),
    Row(415, "UNSUPPORTED_MEDIA_TYPE", _post_a_body_that_is_not_json),
    Row(405, "METHOD_NOT_ALLOWED", _write_with_a_verb_the_route_refuses),
    Row(404, "NOT_FOUND", _read_an_unknown_route),
    Row(
        503,
        "PERSISTENCE_ERROR",
        _read_over_a_broken_database,
        find_error=ServerSelectionTimeoutError("no MongoDB host answered"),
    ),
    Row(
        500,
        "INTERNAL_ERROR",
        _read_over_a_broken_database,
        find_error=RuntimeError("something no layer classified"),
        rethrow=False,
    ),
]

PROTECTED_CALLS = [
    pytest.param(_post_without_credentials, id="POST /texts"),
    pytest.param(_get_without_credentials, id="GET /texts"),
    pytest.param(_put_without_credentials, id="PUT /texts"),
    pytest.param(_delete_without_credentials, id="DELETE /texts"),
]


def _running(
    *, find_error: Exception | None = None, rethrow: bool = True
) -> TestClient:
    """Devuelve toda la app sirviendo en memoria, sobre una base de datos que puede
    estar rota.

    Args:
        find_error: Lo que la base de datos fake lanza en una lectura.
        rethrow: Si el cliente de test vuelve a lanzar una excepción no controlada.

    Returns:
        Un cliente cuyo gestor de contexto ejecuta el lifespan, que es donde se
        conectan el repositorio y el servicio.
    """
    settings = Settings(
        service_api_token=TOKEN,
        mongo_uri="mongodb://test:27017",
        max_text_body_bytes=BODY_LIMIT,
    )
    connection = MongoConnection(
        settings, client_factory=FakeMongoClientFactory(find_error=find_error)
    )
    app = create_app(settings=settings, connection=connection)
    return TestClient(app, raise_server_exceptions=rethrow)


@pytest.fixture(params=ROWS, ids=lambda row: row.code)
def row(request: pytest.FixtureRequest) -> Row:
    """Cada fila de la matriz, con una ejecucion de test por fila."""
    return request.param


@pytest.fixture
def client(row: Row) -> Iterator[TestClient]:
    """Una app en marcha que lleva exactamente los fallos que su fila necesita."""
    with _running(find_error=row.find_error, rethrow=row.rethrow) as running:
        yield running


def test_each_row_answers_with_the_status_and_code_it_promises(
    row: Row, client: TestClient
) -> None:
    response = row.provoke(client)

    assert response.status_code == row.status
    assert response.json()["code"] == row.code


def test_every_failure_is_a_problem_the_orchestrator_can_parse(
    row: Row, client: TestClient
) -> None:
    """La regla de ``internal/httpclient/client.go:39``, fila a fila.

    Un fallo que el cliente de Go no sabe analizar degrada a un simple error de
    transporte, perdiendo el estado y el mensaje, así que el cuerpo tiene que
    llegar como problem.
    """
    response = row.provoke(client)

    assert response.status_code >= 300
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert set(body) == CONTRACT_MEMBERS
    assert body["status"] == response.status_code


@pytest.mark.parametrize("call", PROTECTED_CALLS)
def test_every_protected_endpoint_refuses_an_anonymous_caller(
    call: Callable[[TestClient], Response],
) -> None:
    with _running() as client:
        response = call(client)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
