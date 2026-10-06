"""Configuración operativa, leída del entorno.

SPEC 2.5 define siete variables: seis con valores por defecto documentados y
``SERVICE_API_TOKEN`` sin ninguno. Aquí se leen una sola vez, en un dataclass
congelado. No interviene Pydantic (SPEC 2.3): ``pydantic`` queda confinado a
``app/api``, y la configuración no es el contrato de cable -- son tipos nativos
sobre ``os.environ``, y un dataclass congelado dice lo que un objeto de
configuración mutable sólo insinuaría -- un valor leído al arrancar no es algo
que una capa pueda reescribir.

Por qué un token ausente mata el proceso
----------------------------------------
Un token bearer compartido con un valor por defecto es un token bearer
compartido que nadie eligió, y un servicio que arranca sin protección es peor
que un servicio que no arranca. Por eso el token es la única variable sin valor
por defecto, y un valor ausente, vacío o compuesto sólo de espacios en blanco
lanza :class:`ConfigurationError` antes de que el proceso empiece a servir.

Por qué ``ConfigurationError`` no es un ``ServiceError``
--------------------------------------------------------
Las once clases de :mod:`app.errors` son el vocabulario RFC 9457: cada una es
una promesa sobre una respuesta. Este error nunca se convierte en respuesta --
la raíz de composición lo transforma en un arranque fallido -- y a propósito
no lleva ningún ``status`` que pueda reportar mal. Es un error del operador,
no de la petición.

El token nunca se registra en el log
------------------------------------
El mensaje de fallo nombra la *variable*, nunca su valor, y el token no se
almacena en ningún otro sitio. ``SERVICE_API_TOKEN`` no se compara ni se
reproduce en ningún sitio; SPEC 2.5 y la tabla de riesgos de la sección 10
dependen ambos de eso.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

APP_NAME = "Persistence Microservice"
MONGO_URI = "mongodb://localhost:27017"
MONGO_DATABASE = "pdf_extractext"
MONGO_TEXTS_COLLECTION = "texts"
MONGO_TIMEOUT_MS = 5000
MAX_TEXT_BODY_BYTES = 10485760


class ConfigurationError(Exception):
    """El entorno no describe un servicio al que se permita arrancar."""


@dataclass(frozen=True)
class Settings:
    """La configuración que lee todo el servicio, resuelta una vez al arrancar.

    Attributes:
        service_api_token: Secreto compartido que el orquestador envía como
            token bearer. Obligatorio: no hay valor por defecto, a propósito.
        app_name: Título usado en el documento OpenAPI.
        mongo_uri: Cadena de conexión a MongoDB.
        mongo_database: Base de datos que contiene la colección.
        mongo_texts_collection: Colección que guarda los documentos de texto.
        mongo_timeout_ms: Tiempo máximo aplicado a cada operación de MongoDB.
        max_text_body_bytes: Mayor cuerpo de petición aceptado, en bytes. 10 MiB
            mantiene el documento BSON resultante por debajo del límite de
            16 MiB de MongoDB.
    """

    service_api_token: str
    app_name: str = APP_NAME
    mongo_uri: str = MONGO_URI
    mongo_database: str = MONGO_DATABASE
    mongo_texts_collection: str = MONGO_TEXTS_COLLECTION
    mongo_timeout_ms: int = MONGO_TIMEOUT_MS
    max_text_body_bytes: int = MAX_TEXT_BODY_BYTES


def get_settings(environ: Mapping[str, str] = os.environ) -> Settings:
    """Construye la configuración desde el entorno y falla rápido si falta el token.

    Args:
        environ: Mapping del que leer. Por defecto, el entorno del proceso; el
            parámetro existe para que un test pueda entregar un mapping en
            lugar de mutar el real.

    Returns:
        La configuración resuelta.

    Raises:
        ConfigurationError: Si el token falta, está en blanco o sólo contiene
            espacios, o si una variable numérica no es un entero positivo. El
            mensaje nombra la variable y nunca repite un valor.
    """
    return Settings(
        service_api_token=_required_token(environ),
        app_name=_text(environ, "APP_NAME", APP_NAME),
        mongo_uri=_text(environ, "MONGO_URI", MONGO_URI),
        mongo_database=_text(environ, "MONGO_DATABASE", MONGO_DATABASE),
        mongo_texts_collection=_text(
            environ, "MONGO_TEXTS_COLLECTION", MONGO_TEXTS_COLLECTION
        ),
        mongo_timeout_ms=_positive_int(environ, "MONGO_TIMEOUT_MS", MONGO_TIMEOUT_MS),
        max_text_body_bytes=_positive_int(
            environ, "MAX_TEXT_BODY_BYTES", MAX_TEXT_BODY_BYTES
        ),
    )


def _required_token(environ: Mapping[str, str]) -> str:
    """Devuelve el token bearer, o se niega a continuar sin uno.

    Args:
        environ: Mapping del que leer.

    Returns:
        El token, sin los espacios que lo rodean, para que un salto de línea
        final en un fichero de secretos montado no provoque un desajuste más
        adelante.

    Raises:
        ConfigurationError: Si la variable no está definida, está vacía o sólo
            contiene espacios. El mensaje nombra la variable; el valor nunca
            se incluye.
    """
    raw = environ.get("SERVICE_API_TOKEN")
    token = raw.strip() if raw else ""
    if not token:
        raise ConfigurationError(
            "SERVICE_API_TOKEN is required: the service does not start without a "
            "bearer token."
        )
    return token


def _text(environ: Mapping[str, str], name: str, default: str) -> str:
    """Devuelve un ajuste de tipo cadena, tratando un valor en blanco como ausente.

    Args:
        environ: Mapping del que leer.
        name: Nombre de la variable de entorno.
        default: Valor a usar cuando la variable no está definida o está en
            blanco.

    Returns:
        El valor recortado, o ``default``.
    """
    raw = environ.get(name)
    return raw.strip() if raw and raw.strip() else default


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    """Devuelve un ajuste entero que debe ser mayor que cero.

    Args:
        environ: Mapping del que leer.
        name: Nombre de la variable de entorno.
        default: Valor a usar cuando la variable no está definida o está en
            blanco.

    Returns:
        El entero leído.

    Raises:
        ConfigurationError: Si el valor no es un entero, o es cero o negativo.
            Un tiempo máximo o un límite de cuerpo cero o negativo desactivaría
            ese límite en silencio, que es un modo de fallo por el que merece
            la pena negarse a arrancar.
    """
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ConfigurationError(
            f"{name} must be an integer, got {raw.strip()!r}."
        ) from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be greater than zero, got {value}.")
    return value
