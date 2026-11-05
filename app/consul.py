"""Minimal Consul KV client used during service startup."""

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
