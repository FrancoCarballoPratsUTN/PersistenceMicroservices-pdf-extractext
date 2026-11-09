"""Parsers y validadores de variables de entorno."""

from __future__ import annotations

import logging


def _positive_integer(
    value: str | int | None,
    variable_name: str,
    default: int,
) -> int:
    """Convierte una variable numérica y comprueba que sea positiva.

    Args:
        value: Valor de la variable de entorno a convertir.
        variable_name: Nombre de la variable de entorno (para mensajes de error).
        default: Valor por defecto cuando la variable está vacía o ausente.

    Returns:
        El número entero positivo convertido, o el valor por defecto.
    """
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

    Args:
        value: Valor de la variable de entorno a convertir.
        default: Nivel por defecto cuando la variable está vacía o ausente.

    Returns:
        Nombre del nivel de logging válido (ej. ``DEBUG``, ``INFO``).
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
    """Lee una lista explícita de orígenes separados por coma.

    El valor vacío deja CORS cerrado. El comodín se rechaza porque este servicio
    no necesita exponerse a cualquier origen.

    Args:
        value: Valor de la variable de entorno con orígenes separados por coma.

    Returns:
        Tupla de orígenes CORS permitidos, vacía cuando no hay valor.
    """
    if value is None:
        return ()

    origins = tuple(item.strip() for item in value.split(",") if item.strip())
    if "*" in origins:
        raise ConfigurationError(
            "CORS_ALLOW_ORIGINS must list explicit origins, not '*'."
        )

    return origins


class ConfigurationError(Exception):
    """El entorno no describe un servicio al que se permita arrancar."""
