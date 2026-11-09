"""Registro y deregistro del servicio en Consul (orquestadores)."""

from __future__ import annotations

from app.consul_request import send_request


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
    """Registra el servicio actual en el agente Consul."""
    payload = {
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
    }
    send_request(
        address,
        token,
        "/v1/agent/service/register",
        payload,
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
    """Deregistra el servicio actual del agente Consul."""
    if not service_id.strip():
        from app.consul import ConsulConfigurationError

        raise ConsulConfigurationError("CONSUL_SERVICE_ID must not be empty")
    send_request(
        address,
        token,
        f"/v1/agent/service/deregister/{service_id}",
        None,
        timeout,
        ca_file,
    )
