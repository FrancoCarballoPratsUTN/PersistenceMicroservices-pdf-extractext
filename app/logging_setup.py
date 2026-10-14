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

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(level: str) -> None:
    """Instala el handler raíz del servicio si nadie lo configuró ya.

    Args:
        level: Nivel mínimo a registrar, ya validado por la configuración
            (``DEBUG``, ``INFO``, ``WARNING``, ...).
    """
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT)
