import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigurationError(Exception):
    """El entorno no describe un servicio al que se permita arrancar."""


def _positive_integer(
    value: str | int | None,
    variable_name: str,
    default: int,
) -> int:
    """Convierte una variable numérica y comprueba que sea positiva."""
    if value is None or not str(value).strip():
        return default

    try:
        number = int(value)
    except (ValueError, TypeError) as error:
        raise ConfigurationError(f"{variable_name} must be an integer.") from error

    if number <= 0:
        raise ConfigurationError(f"{variable_name} must be greater than zero.")

    return number


def _log_level(value: str | None, default: str = "INFO") -> str:
    """Convierte una variable en un nivel de logging válido de la stdlib.

    Se acepta el nombre estándar en cualquier capitalización (``info``, ``INFO``).
    Un nombre desconocido detiene el arranque: un nivel mal escrito subiría o
    bajaría el detalle del log en silencio, que es justo lo que no se quiere
    depurar un incidente.
    """
    if value is None or not str(value).strip():
        return default

    name = str(value).strip().upper()
    if name not in logging.getLevelNamesMapping():
        raise ConfigurationError(
            "LOG_LEVEL must be a standard logging level name such as DEBUG, "
            f"INFO, WARNING or ERROR, not {name!r}."
        )

    return name


def _cors_origins(value: str | None) -> tuple[str, ...]:
    """Lee una lista explicita de origenes separados por coma.

    El valor vacio deja CORS cerrado. El comodin se rechaza porque este servicio
    no necesita exponerse a cualquier origen.
    """
    if value is None:
        return ()

    origins = tuple(item.strip() for item in value.split(",") if item.strip())
    if "*" in origins:
        raise ConfigurationError(
            "CORS_ALLOW_ORIGINS must list explicit origins, not '*'."
        )

    return origins


@dataclass(frozen=True)
class Settings:
    service_api_token: str
    app_name: str = "Persistence Microservice"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "pdf_extractext"
    mongo_texts_collection: str = "texts"
    mongo_timeout_ms: int = 5000
    mongo_socket_timeout_ms: int = 5000
    mongo_max_pool_size: int = 100
    mongo_readiness_cache_ttl_seconds: int = 1
    max_text_body_bytes: int = 10485760
    log_level: str = "INFO"
    cors_allow_origins: tuple[str, ...] = ()


def get_settings(environ: Mapping[str, str] | None = None) -> Settings:
    if environ is None:
        environ = os.environ

    # El orquestador nombra el secreto compartido PERSISTENCE_API_TOKEN; es el
    # nombre canonico. SERVICE_API_TOKEN se sigue aceptando por compatibilidad.
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
            environ.get("MONGO_TIMEOUT_MS"),
            "MONGO_TIMEOUT_MS",
            5000,
        ),
        mongo_socket_timeout_ms=_positive_integer(
            environ.get("MONGO_SOCKET_TIMEOUT_MS"),
            "MONGO_SOCKET_TIMEOUT_MS",
            5000,
        ),
        mongo_max_pool_size=_positive_integer(
            environ.get("MONGO_MAX_POOL_SIZE"),
            "MONGO_MAX_POOL_SIZE",
            100,
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
