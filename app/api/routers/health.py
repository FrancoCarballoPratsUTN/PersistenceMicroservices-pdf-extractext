"""Las sondas de vivacidad y de disponibilidad (SPEC 3.1).

Ambas son rutas abiertas: el orquestador sondea sin token. Ninguna sabe qué es
MongoDB; la sonda de disponibilidad solo pregunta al callable que la raíz de
composición dejó en el estado de la aplicación, lo que mantiene esta capa libre
de cualquier detalle de base de datos.
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
    """GET /health: el proceso está en pie. A propósito no dice nada de MongoDB,
    así que una caída de la base de datos nunca saca al servicio de rotación.
    """
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
    """GET /readyz: el proceso está en pie y MongoDB responde.

    Raises:
        PersistenceError: MongoDB no respondió, así que quien llama recibe el
            503 de SPEC 6.2 como documento problem+json.
    """
    if not await request.app.state.readiness_check():
        raise PersistenceError("MongoDB is not available.")
    return JSONResponse({"status": "ok", "mongo": "ok"})
