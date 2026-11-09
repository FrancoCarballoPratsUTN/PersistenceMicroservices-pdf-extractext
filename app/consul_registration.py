"""Registro y deregistro del servicio en Consul."""

import asyncio
import os
import socket

from app.consul_agent import deregister_service, register_service


def consul_registration() -> dict[str, object] | None:
    """Construye el diccionario de registro de Consul, o None si está deshabilitado.

    Lee las variables de entorno de Consul y devuelve los campos necesarios para
    registrar el servicio. Cuando Consul está deshabilitado devuelve None.
    """
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return None
    address = os.getenv("CONSUL_SERVICE_ADDRESS") or socket.gethostname()
    port = int(os.getenv("CONSUL_SERVICE_PORT", os.getenv("PORT", "8000")))
    service_name = os.getenv("CONSUL_SERVICE_NAME", "persistence")
    service_id = os.getenv("CONSUL_SERVICE_ID") or f"{service_name}-{address}"
    tags_env = os.getenv("CONSUL_SERVICE_TAGS", "")
    tags: list[str] = []
    for part in tags_env.split(";"):
        tag = part.strip()
        if tag:
            tags.append(tag)
    return {
        "address": os.getenv("CONSUL_HTTP_ADDR", ""),
        "token": os.getenv("CONSUL_HTTP_TOKEN", ""),
        "ca_file": os.getenv("CONSUL_HTTP_CA_FILE"),
        "service_id": service_id,
        "service_name": service_name,
        "service_address": address,
        "service_port": port,
        "check_url": os.getenv(
            "CONSUL_SERVICE_CHECK_URL",
            f"http://{address}:{port}/readyz",
        ),
        "tags": tags,
    }


async def register_service_off_event_loop(
    registration: dict[str, object],
) -> None:
    """Registrar en Consul sin bloquear el event loop durante el arranque.

    Args:
        registration: Diccionario de registro obtenido de
            :func:`consul_registration`.

    Returns:
        Ninguno.
    """
    await asyncio.to_thread(register_service, **registration)


def deregister_consul_service(
    registration: dict[str, object],
    deregistered_flag: dict[str, bool],
    logger,
) -> None:
    """Deregistra el servicio de Consul si aún no se ha deregistrado.

    Args:
        registration: Diccionario de registro obtenido de
            :func:`consul_registration`.
        deregistered_flag: Diccionario con la clave ``"value"`` usada como
            bandera mutable para evitar doble deregistro.
        logger: Instancia de logger para registrar errores de deregistro.

    Returns:
        Ninguno.
    """
    if deregistered_flag.get("value") or registration is None:
        return
    try:
        deregister_service(
            registration["address"],
            registration["token"],
            registration["service_id"],
            ca_file=registration["ca_file"],
        )
    except Exception:
        logger.exception("Consul service deregistration failed.")
    else:
        deregistered_flag["value"] = True
