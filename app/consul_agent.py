import json
import ssl
from time import sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.consul import ConsulConfigurationError

_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.1


def register_service(
    address: str,
    token: str,
    *,
    service_id: str,
    service_name: str,
    service_address: str,
    service_port: int,
    check_url: str,
    tags: list[str] | None = None,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> None:
    _request(
        address,
        token,
        "/v1/agent/service/register",
        {
            "ID": service_id,
            "Name": service_name,
            "Address": service_address,
            "Port": service_port,
            "Tags": tags or [],
            "Check": {
                "HTTP": check_url,
                "Interval": "10s",
                "Timeout": "3s",
                "DeregisterCriticalServiceAfter": "1m",
            },
        },
        timeout,
        ca_file,
    )


def deregister_service(
    address: str,
    token: str,
    service_id: str,
    *,
    timeout: float = 5.0,
    ca_file: str | None = None,
) -> None:
    if not service_id.strip():
        raise ConsulConfigurationError("CONSUL_SERVICE_ID must not be empty")
    _request(
        address,
        token,
        f"/v1/agent/service/deregister/{service_id}",
        None,
        timeout,
        ca_file,
    )


def _request(
    address: str,
    token: str,
    path: str,
    payload: dict[str, object] | None,
    timeout: float,
    ca_file: str | None,
) -> None:
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
