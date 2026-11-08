"""Composición de la aplicación FastAPI."""

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
from app.logging_setup import configure_logging
from app.lifespan import lifespan
from app.repositories.mongodb import MongoConnection
from app.settings_loader import settings_from_environment_or_consul


def create_app(
    settings: Settings | None = None, connection: MongoConnection | None = None
) -> FastAPI:
    """Construye la aplicación con sus middlewares, routers y manejadores de error.

    Args:
        settings: Configuración con la que correr. Se lee del entorno (o Consul)
            cuando se omite.
        connection: La conexión a MongoDB a usar. Se construye a partir de
            ``settings`` cuando se omite; los tests pasan una cuyo cliente es un
            doble.

    Returns:
        La app lista para servir.
    """
    resolved = (
        settings if settings is not None else settings_from_environment_or_consul()
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
