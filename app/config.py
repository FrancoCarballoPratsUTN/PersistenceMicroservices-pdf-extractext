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


@dataclass(frozen=True)
class Settings:
    service_api_token: str
    app_name: str = "Persistence Microservice"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "pdf_extractext"
    mongo_texts_collection: str = "texts"
    mongo_timeout_ms: int = 5000
    max_text_body_bytes: int = 10485760
    log_level: str = "INFO"

    @property
    def mongodb_uri(self) -> str:
        return self.mongo_uri

    @property
    def mongodb_database(self) -> str:
        return self.mongo_database

    @property
    def mongodb_texts_collection(self) -> str:
        return self.mongo_texts_collection

    @property
    def mongodb_timeout_ms(self) -> int:
        return self.mongo_timeout_ms


def get_settings(environ: Mapping[str, str] = os.environ) -> Settings:
    # El orquestador nombra el secreto compartido PERSISTENCE_API_TOKEN; es el
    # nombre canonico. SERVICE_API_TOKEN se sigue aceptando por compatibilidad.
    token = (
        environ.get("PERSISTENCE_API_TOKEN")
        or os.getenv("PERSISTENCE_API_TOKEN")
        or environ.get("SERVICE_API_TOKEN")
        or os.getenv("SERVICE_API_TOKEN")
    )

    if not token or not str(token).strip():
        raise ConfigurationError("PERSISTENCE_API_TOKEN is required.")

    timeout_value = environ.get(
        "MONGO_TIMEOUT_MS",
        environ.get(
            "MONGODB_TIMEOUT_MS",
            os.getenv("MONGO_TIMEOUT_MS", os.getenv("MONGODB_TIMEOUT_MS")),
        ),
    )

    body_limit_value = environ.get(
        "MAX_TEXT_BODY_BYTES",
        os.getenv("MAX_TEXT_BODY_BYTES"),
    )

    log_level_value = environ.get("LOG_LEVEL", os.getenv("LOG_LEVEL"))

    return Settings(
        service_api_token=str(token).strip(),
        app_name=environ.get(
            "APP_NAME",
            os.getenv("APP_NAME", "Persistence Microservice"),
        ),
        mongo_uri=environ.get(
            "MONGO_URI",
            environ.get(
                "MONGODB_URI",
                os.getenv("MONGO_URI", "mongodb://localhost:27017"),
            ),
        ),
        mongo_database=environ.get(
            "MONGO_DATABASE",
            environ.get(
                "MONGODB_DATABASE",
                os.getenv("MONGO_DATABASE", "pdf_extractext"),
            ),
        ),
        mongo_texts_collection=environ.get(
            "MONGO_TEXTS_COLLECTION",
            environ.get(
                "MONGODB_TEXTS_COLLECTION",
                os.getenv("MONGO_TEXTS_COLLECTION", "texts"),
            ),
        ),
        mongo_timeout_ms=_positive_integer(
            timeout_value,
            "MONGO_TIMEOUT_MS",
            5000,
        ),
        max_text_body_bytes=_positive_integer(
            body_limit_value,
            "MAX_TEXT_BODY_BYTES",
            10485760,
        ),
        log_level=_log_level(log_level_value),
    )


def get_settings_from_values(values: Mapping[str, str]) -> Settings:
    """Build settings from a validated external source such as Consul KV."""
    return get_settings(values)
