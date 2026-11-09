"""Petición HTTP con reintento hacia la API de Consul."""

from __future__ import annotations

import json
import ssl
from time import sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.consul import ConsulConfigurationError

_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.1


def send_request(
    address: str,
    token: str,
    path: str,
    payload: dict[str, object] | None,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> None:
    """Envía una petición PUT a Consul con reintentos ante fallos transitorios.

    Args:
        address: Dirección del agente Consul.
        token: Token de ACL de Consul.
        path: Ruta de la API, p.ej. ``/v1/agent/service/register``.
        payload: Cuerpo JSON a enviar, o ``None`` para peticiones sin cuerpo.
        timeout: Tiempo de espera en segundos para cada intento.
        ca_file: Ruta al certificado CA para TLS.

    Returns:
        Ninguno.
    """
    address = address.strip()
    token = token.strip()
    if not address or not token:
        raise ConsulConfigurationError(
            "CONSUL_HTTP_ADDR and CONSUL_HTTP_TOKEN are required"
        )

    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        f"{address.rstrip('/')}{path}",
        data=body,
        method="PUT",
        headers={"X-Consul-Token": token, "Content-Type": "application/json"},
    )
    context = ssl.create_default_context(cafile=ca_file) if ca_file else None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                response.read()
            return
        except HTTPError as error:
            if error.code < 500 or attempt == _MAX_ATTEMPTS - 1:
                raise ConsulConfigurationError(
                    f"Consul service request returned HTTP {error.code}"
                ) from error
        except OSError as error:
            if attempt == _MAX_ATTEMPTS - 1:
                raise ConsulConfigurationError(
                    "unable to update Consul service registry"
                ) from error

        sleep(_BACKOFF_SECONDS * (2**attempt))
