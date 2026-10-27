"""Raíz de composición: el único módulo que sabe que existen todas las capas.

Aquí se cablea todo y en ningún otro sitio, así que importar un router, un
servicio o un repositorio nunca arrastra el framework, y cada uno se puede
testear por separado. El servicio arranca con::

    uvicorn app.main:create_app --factory

Se usa la fábrica en vez de una instancia a nivel de módulo para que importar
este módulo no necesite entorno alguno: la configuración se resuelve cuando
arranca el proceso, que es donde un ``SERVICE_API_TOKEN`` ausente es fatal
(SPEC 2.5).
"""

import logging
import os
import signal
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from time import perf_counter
from typing import Any

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.auth import BearerAuthMiddleware
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import (
    CORS_METHODS,
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    ContentTypeMiddleware,
    RequestIdMiddleware,
)
from app.api.routers import health, texts
from app.api.schemas import publish
from app.config import Settings, get_settings, get_settings_from_values
from app.consul import load_prefix
from app.consul_agent import deregister_service, register_service
from app.logging_setup import configure_logging
from app.repositories.mongodb import MongoConnection
from app.repositories.mongodb_text_repository import MongoTextRepository
from app.services.text_service import TextService

logger = logging.getLogger(__name__)


def _settings_from_environment_or_consul() -> Settings:
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return get_settings()
    address = os.getenv("CONSUL_HTTP_ADDR", "")
    token = os.getenv("CONSUL_HTTP_TOKEN", "")
    prefix = os.getenv("CONSUL_KV_PREFIX", "")
    values = load_prefix(
        address, token, prefix, ca_file=os.getenv("CONSUL_HTTP_CA_FILE")
    )
    return get_settings_from_values(values)


def _consul_registration() -> dict[str, object] | None:
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return None
    address = os.getenv("CONSUL_SERVICE_ADDRESS") or socket.gethostname()
    port = int(os.getenv("CONSUL_SERVICE_PORT", os.getenv("PORT", "8000")))
    service_name = os.getenv("CONSUL_SERVICE_NAME", "persistence")
    service_id = os.getenv("CONSUL_SERVICE_ID") or f"{service_name}-{address}"
    tags_env = os.getenv("CONSUL_SERVICE_TAGS", "")
    # Separador de tags: ';'. Las comas son parte del valor (p. ej. la lista de
    # middlewares de Traefik: "security-headers@file,persistence-cb@file"), por lo
    # que NO deben usarse como separador.
    tags: list[str] = []
    for part in tags_env.split(";"):
        tag = part.strip()
        if tag:
            tags.append(tag)
    return {
        "address": os.getenv("CONSUL_HTTP_ADDR", ""),
        "token": os.getenv("CONSUL_HTTP_TOKEN", ""),
        "ca_file": os.getenv("CONSUL_HTTP_CA_FILE"),
        "service_id": service_id,
        "service_name": service_name,
        "service_address": address,
        "service_port": port,
        "check_url": os.getenv(
            "CONSUL_SERVICE_CHECK_URL",
            f"http://{address}:{port}/readyz",
        ),
        "tags": tags,
    }


def _install_deregister_handler(
    deregister: Callable[[], None],
) -> Callable[[], None]:
    """Deregistrar al recibir SIGTERM/SIGINT, antes de que uvicorn drene.

    Uvicorn instala sus handlers antes de ejecutar el lifespan. Este handler se
    encadena al anterior: primero saca la instancia de Consul y después deja que
    uvicorn deje de aceptar tráfico y termine las peticiones en vuelo. Devuelve
    una función para restaurar los handlers al cerrar el lifespan.
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
            with suppress(ValueError, AttributeError):
                signal.signal(sig, previous)

    return restore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepara MongoDB al subir y lo libera al bajar.

    Una base de datos que no contesta se registra, no se propaga: el servicio
    sigue en pie y ``/readyz`` reporta la caída, que es lo que el orquestador
    necesita para sacar la instancia de rotación sin un bucle de reinicio
    (SPEC 5.5).

    Arranque y apagado se registran con su duración, así que el timeline de una
    instancia se lee de un vistazo. El estado de MongoDB no se repite aquí: ``start()``
    ya lo avisa por su cuenta.

    El apagado tampoco puede fallar. La deregistración se intenta al recibir la
    señal, antes de que uvicorn drene; el ``finally`` queda como fallback para
    las salidas que no pasan por ese camino. Uvicorn ya terminó las peticiones
    en vuelo antes de llegar aquí: lo que queda es soltar el pool, y un error al
    hacerlo se registra en vez de convertir una parada limpia en una salida con
    error.
    """
    connection: MongoConnection = app.state.mongo
    logger.info("Starting the service.")
    startup_started = perf_counter()
    await connection.start()
    # La colección sólo existe una vez construido el cliente, así que el servicio
    # se cablea aquí: una conexión, un repositorio, un pool (SPEC 2.1).
    app.state.text_service = TextService(MongoTextRepository(connection.texts()))
    registration = _consul_registration()
    if registration is not None:
        register_service(**registration)

    deregistered = False

    def deregister() -> None:
        nonlocal deregistered
        if deregistered or registration is None:
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
            deregistered = True

    restore_signal_handlers = (
        _install_deregister_handler(deregister)
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
            # El apagado nunca debe romper el proceso: se registra y se sigue.
            logger.exception("The MongoDB connection could not be closed cleanly.")
        else:
            logger.info(
                "Shutdown finished in %.1f ms.",
                (perf_counter() - shutdown_started) * 1000,
            )


def create_app(
    settings: Settings | None = None, connection: MongoConnection | None = None
) -> FastAPI:
    """Construye la aplicación.

    Args:
        settings: Configuración con la que correr. Se lee del entorno cuando se
            omite, que es el camino que sigue el proceso y la razón de que un
            token ausente detenga el arranque en vez de dejar un servicio sin
            protección.
        connection: La conexión a MongoDB a usar. Se construye a partir de
            ``settings`` cuando se omite; los tests pasan una cuyo cliente es un
            doble.

    Returns:
        La app con sus manejadores de error, sus sondas y su autenticación
        instalados. Los routers restantes los añaden las tareas que definen los
        endpoints.
    """
    resolved = (
        settings if settings is not None else _settings_from_environment_or_consul()
    )
    configure_logging(resolved.log_level)
    mongo = connection if connection is not None else MongoConnection(resolved)

    app = FastAPI(title=resolved.app_name, lifespan=lifespan)
    app.state.settings = resolved
    app.state.mongo = mongo
    # Las sondas sólo preguntan a un callable, nunca a la base de datos, así que
    # las rutas de app/api no saben nada de pymongo (SPEC 2.1).
    app.state.readiness_check = mongo.is_available
    app.include_router(health.router)
    app.include_router(texts.router)
    register_exception_handlers(app)
    publish(app)
    # Starlette ejecuta el middleware añadido más recientemente como el más
    # externo, así que este bloque se lee al revés: añadir aquí significa
    # ejecutarse el último. El orden de ejecución resultante es el que pide
    # SPEC 3.3 -- 401 antes que 415, 415 antes que 413, y ambos antes que el 400
    # que produciría el parseo del body.
    app.add_middleware(BodySizeLimitMiddleware, settings=resolved)
    app.add_middleware(ContentTypeMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(BearerAuthMiddleware, settings=resolved)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=CORS_METHODS,
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    return app
