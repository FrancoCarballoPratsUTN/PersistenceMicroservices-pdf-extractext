"""Carga de configuración desde variables de entorno."""

from __future__ import annotations

import os
from collections.abc import Mapping

from dotenv import load_dotenv

from app.config.parsers import (
    ConfigurationError,
    _cors_origins,
    _log_level,
    _positive_integer,
)
from app.config.settings import Settings

load_dotenv()


def get_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Construye un :class:`Settings` a partir de un mapping de variables.

    Args:
        environ: Variables de entorno. Cuando se omite se usa ``os.environ``.

    Returns:
        Los ajustes resueltos con sus valores por defecto.

    Raises:
        ConfigurationError: Si falta ``SERVICE_API_TOKEN`` o alguna variable
            numérica no es válida.
    """
    if environ is None:
        environ = os.environ
    token = environ.get("PERSISTENCE_API_TOKEN") or environ.get("SERVICE_API_TOKEN")

    if not token or not str(token).strip():
        raise ConfigurationError("PERSISTENCE_API_TOKEN is required.")

    return Settings(
        service_api_token=str(token).strip(),
        app_name=environ.get("APP_NAME", "Persistence Microservice"),
        mongo_uri=environ.get("MONGO_URI", "mongodb://localhost:27017"),
        mongo_database=environ.get("MONGO_DATABASE", "pdf_extractext"),
        mongo_texts_collection=environ.get("MONGO_TEXTS_COLLECTION", "texts"),
        mongo_timeout_ms=_positive_integer(
            environ.get("MONGO_TIMEOUT_MS"), "MONGO_TIMEOUT_MS", 5000
        ),
        mongo_socket_timeout_ms=_positive_integer(
            environ.get("MONGO_SOCKET_TIMEOUT_MS"),
            "MONGO_SOCKET_TIMEOUT_MS",
            5000,
        ),
        mongo_max_pool_size=_positive_integer(
            environ.get("MONGO_MAX_POOL_SIZE"), "MONGO_MAX_POOL_SIZE", 100
        ),
        mongo_readiness_cache_ttl_seconds=_positive_integer(
            environ.get("MONGO_READINESS_CACHE_TTL_SECONDS"),
            "MONGO_READINESS_CACHE_TTL_SECONDS",
            1,
        ),
        max_text_body_bytes=_positive_integer(
            environ.get("MAX_TEXT_BODY_BYTES"),
            "MAX_TEXT_BODY_BYTES",
            10485760,
        ),
        log_level=_log_level(environ.get("LOG_LEVEL")),
        cors_allow_origins=_cors_origins(environ.get("CORS_ALLOW_ORIGINS")),
    )
