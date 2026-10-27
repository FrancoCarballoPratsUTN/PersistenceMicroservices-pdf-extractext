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
    return {"message": "OK", "checksum": checksum}


async def _read_json(request: Request) -> Any:
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
    await service.delete(require_str(checksum))
    return JSONResponse(content=_ok(checksum))
