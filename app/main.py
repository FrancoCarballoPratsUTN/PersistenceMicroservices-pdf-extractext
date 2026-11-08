import asyncio
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
from app.config import Settings, get_settings
from app.consul import load_prefix
from app.consul_agent import deregister_service, register_service
from app.logging_setup import configure_logging
from app.repositories.mongo_text_repository import MongoTextRepository
from app.repositories.mongodb import MongoConnection
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
    return get_settings(values)


def _consul_registration() -> dict[str, object] | None:
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return None
    address = os.getenv("CONSUL_SERVICE_ADDRESS") or socket.gethostname()
    port = int(os.getenv("CONSUL_SERVICE_PORT", os.getenv("PORT", "8000")))
    service_name = os.getenv("CONSUL_SERVICE_NAME", "persistence")
    service_id = os.getenv("CONSUL_SERVICE_ID") or f"{service_name}-{address}"
    tags_env = os.getenv("CONSUL_SERVICE_TAGS", "")
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


async def _register_service_off_event_loop(registration: dict[str, object]) -> None:
    """Registrar en Consul sin bloquear el event loop durante el arranque."""
    await asyncio.to_thread(register_service, **registration)


def _install_deregister_handler(
    deregister: Callable[[], None],
) -> Callable[[], None]:
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
        except ValueError, AttributeError:
            previous_handlers.pop(sig, None)

    def restore() -> None:
        for sig, previous in previous_handlers.items():
            with suppress(ValueError, AttributeError):
                signal.signal(sig, previous)

    return restore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    connection: MongoConnection = app.state.mongo
    logger.info("Starting the service.")
    startup_started = perf_counter()
    await connection.start()
    app.state.text_service = TextService(MongoTextRepository(connection.texts()))
    registration = _consul_registration()
    if registration is not None:
        await _register_service_off_event_loop(registration)

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
    app.state.readiness_check = mongo.is_available
    app.include_router(health.router)
    app.include_router(texts.router)
    register_exception_handlers(app)
    publish(app)

    app.add_middleware(BodySizeLimitMiddleware, settings=resolved)
    app.add_middleware(ContentTypeMiddleware)
    app.add_middleware(BearerAuthMiddleware, settings=resolved)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)
    if resolved.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved.cors_allow_origins),
            allow_methods=CORS_METHODS,
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    return app
