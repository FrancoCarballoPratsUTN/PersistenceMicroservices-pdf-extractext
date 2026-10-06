"""Tests del vocabulario de errores compartido de :mod:`app.errors`.

Cada fila de la tabla de abajo esta transcrita de la seccion 6.2 de SPEC. Estos
tests son la forma ejecutable de esa matriz: si se desvía un status, un code, un
type URI o un title, el fallo nombra el contrato que rompio.

Aqui conviven a proposito dos 404 independientes. ``TEXT_NOT_FOUND`` significa que
la ruta coincidio pero ningun documento tiene ese checksum; ``NOT_FOUND`` que la
ruta en si no existe. Los clientes las distinguen, asi que los tests tambien.
"""

import pytest

from app.errors import (
    ChecksumAlreadyExistsError,
    ServiceError,
    TextNotFoundError,
    UnauthorizedError,
)
from tests.unit.fixtures.error_cases import ALL_ERROR_CLASSES, ERROR_MATRIX


@pytest.mark.parametrize(
    ("error_cls", "code", "status", "type_uri", "title"), ERROR_MATRIX
)
def test_subclass_matches_the_specified_matrix(
    error_cls, code, status, type_uri, title
):
    assert (error_cls.code, error_cls.status, error_cls.type_uri, error_cls.title) == (
        code,
        status,
        type_uri,
        title,
    )


@pytest.mark.parametrize("error_cls", ALL_ERROR_CLASSES)
def test_every_subclass_is_a_service_error(error_cls):
    assert issubclass(error_cls, ServiceError)


def test_the_three_loading_bearing_statuses():
    assert ChecksumAlreadyExistsError.status == 409
    assert TextNotFoundError.status == 404
    assert UnauthorizedError.status == 401


def test_detail_behavior():
    error = ServiceError("detalle")
    assert error.detail == "detalle"
    assert "detalle" in str(error)
    assert ServiceError().detail == ServiceError.default_detail


def test_default_detail_never_leaks_driver_internals():
    for error_cls in ALL_ERROR_CLASSES:
        default = error_cls.default_detail
        assert "Traceback" not in default
        assert "pymongo" not in default.lower()
