"""Arranque del logging del proceso.

Un único sitio decide dónde van las líneas del servicio y con qué formato, para
que los ``logger.info`` de la aplicación (acceso, ciclo de vida) salgan de verdad:
sin esta llamada, los loggers ``app.*`` propagan a un logger raíz sin handler, y
sólo sobreviven los WARNING por el ``lastResort`` de la stdlib.

``basicConfig`` es deliberadamente conservador: si el logger raíz ya tiene
handlers (el caso de los tests, que capturan con ``caplog``) no hace nada. Eso
hace que arrancar el logging nunca pise una configuración que ya existe.
"""

import logging
from typing import Any

from app.request_context import request_id_context

LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s %(name)s request_id=%(request_id)s %(message)s"
)
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class RequestIdLogRecordFactory:
    """Añade el request ID actual a cada registro de logging."""

    def __init__(self, original_factory: Any) -> None:
        self._original_factory = original_factory

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        record = self._original_factory(*args, **kwargs)
        record.request_id = request_id_context.get() or "-"
        return record


def configure_logging(level: str) -> None:
    """Instala el handler raíz del servicio si nadie lo configuró ya.

    Args:
        level: Nivel mínimo a registrar, ya validado por la configuración
            (``DEBUG``, ``INFO``, ``WARNING``, ...).
    """
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT)
    if not isinstance(logging.getLogRecordFactory(), RequestIdLogRecordFactory):
        logging.setLogRecordFactory(
            RequestIdLogRecordFactory(logging.getLogRecordFactory())
        )
