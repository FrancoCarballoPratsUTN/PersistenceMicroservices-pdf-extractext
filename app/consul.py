"""es el cliente minimalista de Consul KV que se usa al arranque del servicio para leer la configuración.

arma la URL con la dirección de Consul, envía el encabezado X-Consul-Token, parsea el JSON de respuesta, 
y para cada entrada extrae la clave (quitando el prefijo) y decodifica el valor de base64 a texto.
"""

import base64
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ConsulConfigurationError(RuntimeError):
    """Consul could not provide a valid configuration prefix."""


def load_prefix(
    address: str,
    token: str,
    prefix: str,
    *,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> dict[str, str]:
    """Lee el prefijo de configuración desde el KV de Consul.

    Args:
        address: Dirección del agente Consul.
        token: Token de ACL de Consul.
        prefix: Prefijo KV bajo el que viven las claves de configuración.
        timeout: Tiempo de espera en segundos para la petición HTTP.
        ca_file: Ruta opcional al certificado CA para TLS.

    Returns:
        Diccionario con las pares clave-valor leídas del prefijo KV de Consul.
    """
    address = address.strip()
    token = token.strip()
    prefix = prefix.strip().strip("/")
    if not address or not token or not prefix:
        raise ConsulConfigurationError(
            "CONSUL_HTTP_ADDR, CONSUL_HTTP_TOKEN and CONSUL_KV_PREFIX are required"
        )

    url = f"{address.rstrip('/')}/v1/kv/{prefix}?recurse=true"
    request = Request(url, headers={"X-Consul-Token": token})
    try:
        context = ssl.create_default_context(cafile=ca_file) if ca_file else None
        with urlopen(request, timeout=timeout, context=context) as response:
            entries = json.load(response)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        UnicodeDecodeError,
        TypeError,
    ) as error:
        raise ConsulConfigurationError("unable to read Consul KV prefix") from error

    if not isinstance(entries, list):
        raise ConsulConfigurationError("Consul KV response must be a list")
    if not entries:
        raise ConsulConfigurationError("Consul KV prefix returned no keys")

    normalized_prefix = f"{prefix}/"
    values: dict[str, str] = {}
    for entry in entries:
        key, value = _decode_entry(entry, normalized_prefix)
        values[key] = value
    return values


def _decode_entry(entry: object, normalized_prefix: str) -> tuple[str, str]:
    """Decodifica una entrada del KV de Consul en clave y valor.

    Args:
        entry: Entrada devuelta por la API de Consul KV.
        normalized_prefix: Prefijo normalizado con el que iniciar la clave.

    Returns:
        Tupla con la clave (sin el prefijo) y el valor decodificado de base64.
    """
    try:
        key = entry["Key"]
        encoded = entry["Value"]
    except (KeyError, TypeError) as error:
        raise ConsulConfigurationError("invalid entry in Consul KV response") from error

    if not isinstance(key, str) or not isinstance(encoded, str):
        raise ConsulConfigurationError("invalid entry in Consul KV response")
    if not key.startswith(normalized_prefix) or key == normalized_prefix:
        raise ConsulConfigurationError(
            "Consul returned a key outside the configured prefix"
        )

    try:
        value = base64.b64decode(encoded, validate=True).decode()
    except ValueError as error:
        raise ConsulConfigurationError("invalid value in Consul KV response") from error

    return key.removeprefix(normalized_prefix), value
