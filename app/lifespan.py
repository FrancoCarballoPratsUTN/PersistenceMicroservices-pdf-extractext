"""Ciclo de vida de la aplicación: arranque, apagado y señales."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI

from app.repositories.mongo_text_repository import MongoTextRepository
from app.repositories.mongodb import MongoConnection
from app.services.consul.agent import deregister_service
from app.services.consul.registration import (
    consul_registration,
    register_service_off_event_loop,
)
from app.services.text_service import TextService
from app.signal_handlers import install_deregister_signal_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Gestiona el arranque y apagado del servicio.

    Arranca la conexión de MongoDB, construye el TextService, registra en Consul
    (si está habilitado) e instala los manejadores de señal para deregistrar al
    apagar. Al finalizar, cierra la conexión de MongoDB limpiamente.

    Args:
        app: La aplicación FastAPI cuyo ciclo de vida se gestiona.

    Returns:
        Contexto asíncrono que cede el control mientras la app está activa.
    """
    connection: MongoConnection = app.state.mongo
    logger.info("Starting the service.")
    startup_started = perf_counter()
    await connection.start()
    app.state.text_service = TextService(MongoTextRepository(connection.texts()))

    registration = consul_registration()
    if registration is not None:
        await register_service_off_event_loop(registration)

    deregistered: dict[str, bool] = {"value": False}

    def deregister() -> None:
        if deregistered["value"] or registration is None:
            return
        try:
            deregister_service(
                registration["address"],
                registration["token"],
                registration["service_id"],
                ca_file=registration["ca_file"],
            )
        except Exception:
            logger.exception("Consul service deregistration failed.")
        else:
            deregistered["value"] = True

    restore_signal_handlers = (
        install_deregister_signal_handlers(deregister)
        if registration is not None
        else lambda: None
    )
    logger.info(
        "Service started in %.1f ms.", (perf_counter() - startup_started) * 1000
    )
    try:
        yield
    finally:
        restore_signal_handlers()
        deregister()
        logger.info("Shutting down: closing the MongoDB connection.")
        shutdown_started = perf_counter()
        try:
            await connection.close()
        except Exception:
            logger.exception("The MongoDB connection could not be closed cleanly.")
        else:
            logger.info(
                "Shutdown finished in %.1f ms.",
                (perf_counter() - shutdown_started) * 1000,
            )
