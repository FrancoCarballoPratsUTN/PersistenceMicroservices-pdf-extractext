"""Las correcciones aplicadas al documento que FastAPI no puede escribir (T17).

``tests/integration/api/test_openapi.py`` comprueba el documento que el servicio
publica de verdad. Estos tests cubren las dos correcciones cuyo unico caso
interesante es un documento que el servicio no tiene: un parametro que no es el
checksum, y una ruta que no declara parametro alguno.
"""

from typing import Any

import pytest

from app.api.schemas import _drop_pydantic_validation, _require_the_checksum


def _document(*parameters: dict[str, Any]) -> dict[str, Any]:
    """Un documento con la forma del publicado, con los parametros dados."""
    return {"paths": {"/texts": {"get": {"parameters": list(parameters)}}}}


def _parameter(name: str) -> dict[str, Any]:
    """Un parametro de query tal como lo construye FastAPI: opcional y anulable."""
    return {
        "name": name,
        "in": "query",
        "required": False,
        "schema": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    }


def test_the_checksum_is_made_required_and_stops_being_nullable() -> None:
    document = _document(_parameter("checksum"))

    _require_the_checksum(document)

    parameter = document["paths"]["/texts"]["get"]["parameters"][0]
    assert parameter["required"] is True
    assert parameter["schema"] == {"type": "string", "minLength": 1}


def test_another_parameter_is_left_as_it_is() -> None:
    """La correccion va sobre el checksum, no sobre cualquier parametro."""
    document = _document(_parameter("checksum"), _parameter("limit"))

    _require_the_checksum(document)

    limit = document["paths"]["/texts"]["get"]["parameters"][1]
    assert limit == _parameter("limit")


def test_an_operation_without_parameters_is_not_an_error() -> None:
    """POST /texts no tiene parametro de query, y no hay nada que corregir."""
    _require_the_checksum({"paths": {"/texts": {"post": {}}}})


def test_the_invented_422_and_the_schemas_describing_it_are_dropped() -> None:
    document: dict[str, Any] = {
        "paths": {"/texts": {"get": {"responses": {"200": {}, "422": {}}}}},
        "components": {
            "schemas": {
                "HTTPValidationError": {},
                "ValidationError": {},
                "Problem": {},
            }
        },
    }

    _drop_pydantic_validation(document)

    assert set(document["paths"]["/texts"]["get"]["responses"]) == {"200"}
    assert set(document["components"]["schemas"]) == {"Problem"}


def test_a_document_with_nothing_to_drop_is_left_alone() -> None:
    """Las sondas no publican ningun 422 ni componente alguno."""
    document: dict[str, Any] = {"paths": {"/health": {"get": {"responses": {}}}}}

    _drop_pydantic_validation(document)


@pytest.mark.parametrize("document", [{}, {"paths": {}}])
def test_a_document_without_paths_is_left_alone(document: dict[str, Any]) -> None:
    """Una app sin rutas sigue publicando un documento, y es valido."""
    _drop_pydantic_validation(document)
