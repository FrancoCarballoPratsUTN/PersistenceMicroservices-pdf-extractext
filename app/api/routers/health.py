"""Endpoints de salud y disponibilidad del servicio.

Exponde ``/health`` (sonda de proceso vivo) y ``/readyz`` (sonda de
disponibilidad que también verifica que MongoDB responde).
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.schemas import answered_with, failing_with
from app.errors import PersistenceError

ReadinessCheck = Callable[[], Awaitable[bool]]

router = APIRouter()


@router.get(
    "/health",
    openapi_extra={"responses": {"200": answered_with("Probe", "The process is up.")}},
)
async def health() -> JSONResponse:
    """Indica que el proceso del servicio está activo."""
    return JSONResponse({"status": "ok"})


@router.get(
    "/readyz",
    openapi_extra={
        "responses": {
            "200": answered_with("Probe", "The process is up and MongoDB answers."),
            **failing_with("503"),
        }
    },
)
async def readyz(request: Request) -> JSONResponse:
    """Verifica que el proceso y MongoDB están disponibles.

    Args:
        request: Petición entrante.

    Returns:
        Respuesta JSON con el estado del servicio y de MongoDB.
    """
    if not await request.app.state.readiness_check():
        raise PersistenceError("MongoDB is not available.")
    return JSONResponse({"status": "ok", "mongo": "ok"})
