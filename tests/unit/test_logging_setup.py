"""Tests del arranque del logging del proceso.

`configure_logging` existe para que los `logger.info` de la aplicación salgan de
verdad (sin él, los loggers `app.*` propagan a un logger raíz sin handler y sólo
sobreviven los WARNING). Lo que estos tests fijan es el contrato de la función:
aplica el nivel pedido, instala un único handler, y nunca pisa una configuración
que ya existe — que es la razón de que los tests con `caplog` sigan capturando.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from app.logging_setup import configure_logging


@contextmanager
def bare_root_logging() -> Iterator[logging.Logger]:
    """Deja el logger raíz sin handlers, como lo ve el proceso en producción, y lo
    restaura después.

    pytest instala sus propios handlers en el raíz durante cada test; sin
    quitarlos, ``configure_logging`` sería un no-op y estas aserciones no
    probarían nada.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers.clear()
    try:
        yield root
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_configure_logging_sets_the_root_level() -> None:
    with bare_root_logging() as root:
        configure_logging("DEBUG")

        assert root.level == logging.DEBUG


def test_configure_logging_installs_a_single_handler() -> None:
    """Llamarla dos veces no multiplica los handlers."""
    with bare_root_logging() as root:
        configure_logging("INFO")
        configure_logging("INFO")

        assert len(root.handlers) == 1


def test_configure_logging_leaves_an_existing_configuration_alone() -> None:
    """Si alguien ya configuró el logging (pytest, un runner), no se pisa."""
    with bare_root_logging() as root:
        existing = logging.NullHandler()
        root.addHandler(existing)

        configure_logging("DEBUG")

        assert root.handlers == [existing]
