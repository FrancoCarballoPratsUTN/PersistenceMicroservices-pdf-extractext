"""El documento OpenAPI publicado (T17, T18).

SPEC 2.3 mantuvo Pydantic fuera del contrato, y el precio fue un documento que
FastAPI ya no puede escribir por sí solo: cada respuesta salía con un schema
vacío. T18 cambió esa premisa -- los schemas ahora se derivan de los modelos de
``app/api/models.py`` -- así que la afirmación interesante aquí ya no es *qué*
dice el documento, que los tests unitarios ya fijan, sino *que se deriva*: cambia
un modelo y este documento tiene que seguirlo, porque un schema del que nadie
deriva desde el código es un schema que se desvía.

Qué se afirma aquí
------------------
* los cinco schemas de cuerpo equivalen a lo que publica su modelo,
* los cuatro verbos de ``/texts`` declaran el esquema bearer, y los probes no,
* cada operación documenta el cuerpo con el que responde en caso de éxito,
* cada operación documenta exactamente los estados con los que puede responder,
  de modo que un fallo que falta es tanto un defecto como uno inventado,
* todo fallo documentado es un documento problem,
* los valores enumerados de ``code`` coinciden con el vocabulario de errores, de
  modo que el documento no puede alejarse en silencio de ``app/errors.py``.

``/openapi.json`` está detrás del token como cualquier ruta salvo los dos probes
(SPEC 3.1), así que se lee con credenciales.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.models import (
    AcknowledgementOut,
    CreateTextBody,
    ProbeOut,
    TextOut,
    UpdateTextBody,
    schema_of,
)
from app.config import Settings
from app.main import create_app
from app.repositories.mongodb import MongoConnection
from tests.fakes.fake_mongo_client import FakeMongoClientFactory
from tests.unit.fixtures.error_cases import ALL_ERROR_CLASSES

TOKEN = "token-for-tests-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

PROBLEM_REF = {"$ref": "#/components/schemas/Problem"}

# ruta, verbo, el estado con el que responde, el schema de ese cuerpo, y todos
# los estados con los que puede fallar (SPEC 6.2). Una sola tabla, porque un
# estado que falta aquí es un estado del que no se le dirá a ningún cliente que
# debe gestionarlo.
OPERATIONS = [
    pytest.param(
        "/texts", "get", "200", "Text", ("400", "401", "404"), id="GET /texts"
    ),
    pytest.param(
        "/texts",
        "post",
        "201",
        "Acknowledgement",
        ("400", "401", "409", "413", "415"),
        id="POST /texts",
    ),
    pytest.param(
        "/texts",
        "put",
        "200",
        "Text",
        ("400", "401", "404", "413", "415"),
        id="PUT /texts",
    ),
    pytest.param(
        "/texts",
        "delete",
        "200",
        "Acknowledgement",
        ("400", "401", "404"),
        id="DELETE /texts",
    ),
    pytest.param("/health", "get", "200", "Probe", (), id="GET /health"),
    pytest.param("/readyz", "get", "200", "Probe", ("503",), id="GET /readyz"),
]

# verbo -> el schema del cuerpo que acepta.
BODY_VERBS = [
    pytest.param("post", "CreateText", id="POST"),
    pytest.param("put", "UpdateText", id="PUT"),
]

# nombre del componente -> el modelo que debe producirlo, y la descripción que el
# documento lleva para él. T18 sustituyó los schemas escritos a mano por los
# generados, y esta tabla es donde queda escrita esa promesa: un componente cuyo
# schema se transcribió en lugar de derivarse pasaría todos los demás tests de
# este fichero.
DERIVED = [
    pytest.param(
        "CreateText",
        CreateTextBody,
        "The text to store.",
        id="CreateText",
    ),
    pytest.param(
        "UpdateText",
        UpdateTextBody,
        "What to change. A field left out does not change (SPEC 4.3), and a body "
        "asking for no change at all is refused.",
        id="UpdateText",
    ),
    pytest.param(
        "Text",
        TextOut,
        "A stored text, as GET and PUT answer it.",
        id="Text",
    ),
    pytest.param(
        "Acknowledgement",
        AcknowledgementOut,
        "What POST and DELETE answer with.",
        id="Acknowledgement",
    ),
    pytest.param(
        "Probe",
        ProbeOut,
        "What the probes answer with.",
        id="Probe",
    ),
]


@pytest.fixture
def document() -> dict[str, Any]:
    """El documento que publica realmente el servicio."""
    settings = Settings(service_api_token=TOKEN, mongo_uri="mongodb://test:27017")
    connection = MongoConnection(settings, client_factory=FakeMongoClientFactory())
    with TestClient(create_app(settings=settings, connection=connection)) as client:
        response = client.get("/openapi.json", headers=AUTH)
    assert response.status_code == 200
    return response.json()


def _operation(document: dict[str, Any], path: str, verb: str) -> dict[str, Any]:
    return document["paths"][path][verb]


@pytest.mark.parametrize("verb", ["get", "post", "put", "delete"])
def test_every_texts_verb_is_documented_as_protected(
    document: dict[str, Any], verb: str
) -> None:
    assert _operation(document, "/texts", verb)["security"] == [{"bearerAuth": []}]


@pytest.mark.parametrize(("name", "model", "description"), DERIVED)
def test_each_schema_is_derived_from_the_model_that_describes_it(
    document: dict[str, Any], name: str, model: type[BaseModel], description: str
) -> None:
    """El punto entero de T18: el documento sigue al código en vez de copiarlo."""
    published = document["components"]["schemas"][name]

    assert published == schema_of(model, description)


def test_the_published_create_body_states_the_non_empty_rule(
    document: dict[str, Any],
) -> None:
    """Un checksum que el cliente podría enviar como ``""`` almacenaría un ``_id``
    inalcanzable."""
    properties = document["components"]["schemas"]["CreateText"]["properties"]

    assert properties["text"]["minLength"] == 1
    assert properties["checksum"]["minLength"] == 1


def test_the_published_text_states_that_its_timestamps_are_dates(
    document: dict[str, Any],
) -> None:
    properties = document["components"]["schemas"]["Text"]["properties"]

    assert properties["created_at"]["format"] == "date-time"
    assert properties["updated_at"]["format"] == "date-time"


def test_the_bearer_scheme_is_defined(document: dict[str, Any]) -> None:
    """El esquema que un cliente necesita para poder enviar un token."""
    scheme = document["components"]["securitySchemes"]["bearerAuth"]

    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"


@pytest.mark.parametrize("path", ["/health", "/readyz"])
def test_the_probes_are_documented_as_open(document: dict[str, Any], path: str) -> None:
    assert "security" not in document["paths"][path]["get"]


@pytest.mark.parametrize(
    ("path", "verb", "success", "schema_name", "failures"), OPERATIONS
)
def test_each_operation_documents_the_body_it_answers_with(
    document: dict[str, Any],
    path: str,
    verb: str,
    success: str,
    schema_name: str,
    failures: tuple[str, ...],
) -> None:
    responses = _operation(document, path, verb)["responses"]

    content = responses[success]["content"]["application/json"]

    assert content["schema"] == {"$ref": f"#/components/schemas/{schema_name}"}


@pytest.mark.parametrize(
    ("path", "verb", "success", "schema_name", "failures"), OPERATIONS
)
def test_each_operation_documents_exactly_the_statuses_it_answers_with(
    document: dict[str, Any],
    path: str,
    verb: str,
    success: str,
    schema_name: str,
    failures: tuple[str, ...],
) -> None:
    """Un estado que el servicio puede enviar pero que el documento omite es un
    defecto."""
    responses = _operation(document, path, verb)["responses"]

    assert set(responses) == {success, *failures}


@pytest.mark.parametrize(
    ("path", "verb", "success", "schema_name", "failures"), OPERATIONS
)
def test_each_documented_failure_is_a_problem_document(
    document: dict[str, Any],
    path: str,
    verb: str,
    success: str,
    schema_name: str,
    failures: tuple[str, ...],
) -> None:
    responses = _operation(document, path, verb)["responses"]

    for status in failures:
        content = responses[status]["content"]["application/problem+json"]
        assert content["schema"] == PROBLEM_REF, status


@pytest.mark.parametrize(("verb", "schema_name"), BODY_VERBS)
def test_each_body_carrying_verb_documents_what_it_accepts(
    document: dict[str, Any], verb: str, schema_name: str
) -> None:
    request_body = _operation(document, "/texts", verb)["requestBody"]

    content = request_body["content"]["application/json"]

    assert content["schema"] == {"$ref": f"#/components/schemas/{schema_name}"}


def test_the_documented_codes_are_exactly_the_error_vocabulary(
    document: dict[str, Any],
) -> None:
    problem = document["components"]["schemas"]["Problem"]

    assert sorted(problem["properties"]["code"]["enum"]) == sorted(
        error.code for error in ALL_ERROR_CLASSES
    )


@pytest.mark.parametrize("verb", ["get", "put", "delete"])
def test_the_checksum_is_documented_as_a_required_query_parameter(
    document: dict[str, Any], verb: str
) -> None:
    parameter = _operation(document, "/texts", verb)["parameters"][0]

    assert parameter["name"] == "checksum"
    assert parameter["required"] is True


def test_no_response_promises_a_422_the_service_never_sends(
    document: dict[str, Any],
) -> None:
    for path in document["paths"].values():
        for operation in path.values():
            assert "422" not in operation.get("responses", {})


def test_the_pydantic_validation_schemas_are_not_published(
    document: dict[str, Any],
) -> None:
    """Nada responde con ellos, y el nombre choca con nuestro propio código."""
    schemas = document["components"]["schemas"]

    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas
