"""Routers HTTP para el recurso de textos.

Define los endpoints GET, POST, PUT y DELETE sobre ``/texts``. Los handlers se
mantienen finos: leen y validan la petición, delegan en el servicio, y traducen
el resultado a una respuesta. No contienen reglas de negocio.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.status import HTTP_201_CREATED

from app.api.dependencies import get_text_service
from app.api.responses import ok_response
from app.api.schemas import SECURITY, accepts, answered_with, failing_with
from app.api.validators.common import read_json_body, require_str
from app.api.validators.create_text import validate as validate_create
from app.api.validators.update_text import validate as validate_update
from app.repositories.serialization import to_api_dict
from app.services.text_service import TextService

router = APIRouter()


@router.get(
    "/texts",
    openapi_extra={
        "responses": {
            "200": answered_with("Text", "The text as it stands."),
            **failing_with("400", "401", "404", "503"),
        },
        "security": SECURITY,
    },
)
async def get_text(
    checksum: str | None = None,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Obtiene un texto por su checksum.

    Args:
        checksum: Checksum del texto a recuperar.
        service: Servicio de textos inyectado por dependencia.

    Returns:
        Respuesta JSON con el texto serializado.
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
            **failing_with("400", "401", "409", "413", "415", "503"),
        },
        "security": SECURITY,
    },
)
async def create_text(
    request: Request,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Crea un nuevo texto a partir del cuerpo de la petición.

    Args:
        request: Petición entrante con el cuerpo JSON del texto.
        service: Servicio de textos inyectado por dependencia.

    Returns:
        Respuesta JSON 201 con el acknowledge y el checksum.
    """
    command = validate_create(await read_json_body(request))
    await service.create(command)
    return JSONResponse(
        status_code=HTTP_201_CREATED,
        content=ok_response(command.checksum),
        headers={"Location": f"/texts?checksum={quote(command.checksum, safe='')}"},
    )


@router.put(
    "/texts",
    openapi_extra={
        "requestBody": accepts("UpdateText"),
        "responses": {
            "200": answered_with("Text", "The text after the change."),
            **failing_with("400", "401", "404", "413", "415", "503"),
        },
        "security": SECURITY,
    },
)
async def update_text(
    request: Request,
    checksum: str | None = None,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Actualiza un texto existente con los cambios proporcionados.

    Args:
        request: Petición entrante con el cuerpo JSON de cambios.
        checksum: Checksum del texto a actualizar.
        service: Servicio de textos inyectado por dependencia.

    Returns:
        Respuesta JSON con el texto actualizado serializado.
    """
    changes = validate_update(await read_json_body(request))
    item = await service.update(require_str(checksum), changes)
    return JSONResponse(content=to_api_dict(item))


@router.delete(
    "/texts",
    openapi_extra={
        "responses": {
            "200": answered_with("Acknowledgement", "The text was removed."),
            **failing_with("400", "401", "404", "503"),
        },
        "security": SECURITY,
    },
)
async def delete_text(
    checksum: str | None = None,
    service: TextService = Depends(get_text_service),
) -> JSONResponse:
    """Elimina un texto por su checksum.

    Args:
        checksum: Checksum del texto a eliminar.
        service: Servicio de textos inyectado por dependencia.

    Returns:
        Respuesta JSON con el acknowledge y el checksum.
    """
    await service.delete(require_str(checksum))
    return JSONResponse(content=ok_response(checksum))
