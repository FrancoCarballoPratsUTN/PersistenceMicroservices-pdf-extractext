"""El endpoint que un scraper de Prometheus raspa sin credenciales.

Al igual que las sondas, vive fuera del token: el scraper no habla OAuth. La
respuesta no es JSON sino el texto plano del registro de métricas.
"""

from fastapi import APIRouter
from starlette.responses import Response

from app.metrics import metrics_response

router = APIRouter()


@router.get("/metrics")
async def metrics() -> Response:
    return metrics_response()
