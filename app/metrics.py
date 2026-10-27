"""Métricas HTTP del microservicio, en formato Prometheus.

Un único módulo concentra la definición de las métricas y la exposición, de
modo que el registro global de ``prometheus_client`` se llena una sola vez por
proceso: definirlas en ``create_app`` registraría cada métrica dos veces en
cuanto la raíz de composición se llamara más de una vez, que es exactamente lo
que hacen los tests.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

LABELS = ["method", "route", "status"]
BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)

http_requests_total = Counter(
    "http_requests_total",
    "Peticiones HTTP recibidas, por método, ruta y estado.",
    LABELS,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Duración de las peticiones HTTP en segundos.",
    LABELS,
    buckets=BUCKETS,
)


def metrics_response() -> Response:
    """El snapshot actual del registro, como lo espera un scraper."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
