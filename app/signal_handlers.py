"""Manejadores de señal para deregistro graceful en Consul."""

from collections.abc import Callable
from contextlib import suppress
from typing import Any

import signal


def install_deregister_signal_handlers(
    deregister: Callable[[], None],
) -> Callable[[], None]:
    """Instala manejadores de señal que deregistran en Consul antes de salir.

    Guarda los manejadores previos y los restaura al devolver el callable de
    limpieza.
    """
    previous_handlers: dict[int, Any] = {}

    def handle_signal(signum: int, frame: Any) -> None:
        deregister()
        previous = previous_handlers.get(signum)
        if callable(previous):
            previous(signum, frame)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, handle_signal)
        except (ValueError, AttributeError):
            previous_handlers.pop(sig, None)

    def restore() -> None:
        for sig, previous in previous_handlers.items():
            with suppress((ValueError, AttributeError)):
                signal.signal(sig, previous)

    return restore
