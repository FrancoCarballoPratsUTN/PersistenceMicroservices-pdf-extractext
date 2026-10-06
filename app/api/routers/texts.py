"""Los cuatro verbos de /texts (T10, T12, T13, T14).

Solo Capa 1: leer el cuerpo, validarlo, entregar un comando al servicio y dar
forma a la respuesta. Ningún detalle de persistencia cruza esta línea (SPEC 2.1).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.status import HTTP_201_CREATED

from app.api.dependencies import get_text_service
from app.api.schemas import (
    SECURITY,
    accepts,
    answered_with,
    failing_with,
)
from app.api.validators.common import ValidationError, require_str
from app.api.validators.create_text import validate as validate_create
from app.api.validators.update_text import validate as validate_update
from app.repositories.serialization import to_api_dict
from app.services.text_service import TextService

router = APIRouter()


def _ok(checksum: str) -> dict[str, str]:
    """La respuesta que dan los dos verbos de escritura: qué pasó, y a qué."""
    return {"message": "OK", "checksum": checksum}


async def _read_json(request: Request) -> Any:
    """Devuelve el cuerpo como Python nativo, o lo rechaza.

    Compartido por los dos endpoints que llevan cuerpo, para que la respuesta a
    un cuerpo roto esté escrita una sola vez.
    """
    try:
        return await request.json()
    except ValueError as error:
        raise ValidationError("The body must be JSON.") from error


@router.get(
    "/texts",
    openapi_extra={
        "responses": {
            "200": answered_with("Text", "The text as it stands."),
            **failing_with("400", "401", "404"),
        },
        "security": SECURITY,
    },
)
async def get_text(
    checksum: str | None = None,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Devuelve el texto almacenado bajo un checksum.

    Args:
        checksum: El checksum que se quiere leer, como cadena opaca.
        service: El caso de uso que recupera el texto o informa de que no está.

    Returns:
        ``200`` con los seis miembros que promete la API.

    Raises:
        ValidationError: Si el parámetro de consulta falta o está en blanco.
        TextNotFoundError: Si ningún texto lleva ese checksum.
    """
    item = await service.find_by_checksum(require_str(checksum))
    return JSONResponse(content=to_api_dict(item))


@router.post(
    "/texts",
    status_code=HTTP_201_CREATED,
    openapi_extra={
        "requestBody": accepts("CreateText"),
        "responses": {
            "201": answered_with("Acknowledgement", "The text was stored."),
            **failing_with("400", "401", "409", "413", "415"),
        },
        "security": SECURITY,
    },
)
async def create_text(
    request: Request,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Almacena un texto y apunta a dónde se puede leer.

    Args:
        request: La petición entrante, cuyo cuerpo lleva el texto a almacenar.
        service: El caso de uso que decide si se puede almacenar.

    Returns:
        ``201`` con ``Location`` y un cuerpo que nombra el checksum almacenado.

    Raises:
        ValidationError: Si el cuerpo no es JSON, o no es un texto que se pueda
            almacenar. El manejador lo convierte en un ``400`` con la forma de
            RFC 9457.
    """
    command = validate_create(await _read_json(request))
    await service.create(command)
    return JSONResponse(
        status_code=HTTP_201_CREATED,
        content=_ok(command.checksum),
        headers={"Location": f"/texts?checksum={quote(command.checksum, safe='')}"},
    )


@router.put(
    "/texts",
    openapi_extra={
        "requestBody": accepts("UpdateText"),
        "responses": {
            "200": answered_with("Text", "The text after the change."),
            **failing_with("400", "401", "404", "413", "415"),
        },
        "security": SECURITY,
    },
)
async def update_text(
    request: Request,
    checksum: str | None = None,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Cambia el nombre, los metadatos, o ambos, de un texto almacenado.

    El checksum es el objetivo y vive en la cadena de consulta; el cuerpo solo
    lleva lo que cambia (SPEC 4.3).

    Args:
        request: La petición entrante, cuyo cuerpo lleva los cambios.
        checksum: El checksum del texto que se quiere cambiar.
        service: El caso de uso que los aplica o informa de que el texto no está.

    Returns:
        ``200`` con el texto tal como queda tras la actualización.

    Raises:
        ValidationError: Si el parámetro de consulta o el cuerpo no son usables,
            o si el cuerpo no pide ningún cambio.
        ImmutableFieldError: Si el cuerpo lleva ``text`` o ``checksum``.
        TextNotFoundError: Si ningún texto lleva ese checksum.
    """
    changes = validate_update(await _read_json(request))
    item = await service.update(require_str(checksum), changes)
    return JSONResponse(content=to_api_dict(item))


@router.delete(
    "/texts",
    openapi_extra={
        "responses": {
            "200": answered_with("Acknowledgement", "The text was removed."),
            **failing_with("400", "401", "404"),
        },
        "security": SECURITY,
    },
)
async def delete_text(
    checksum: str | None = None,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Elimina un texto almacenado.

    El cuerpo no se lee: un borrado no lleva nada que cambiar, solo el checksum
    de lo que hay que eliminar (SPEC 4.4).

    Args:
        checksum: El checksum del texto que se quiere eliminar.
        service: El caso de uso que lo elimina o informa de que no había ninguno.

    Returns:
        ``200`` con el checksum que se eliminó.

    Raises:
        ValidationError: Si el parámetro de consulta falta o está en blanco.
        TextNotFoundError: Si ningún texto lleva ese checksum.
    """
    await service.delete(require_str(checksum))
    return JSONResponse(content=_ok(checksum))
