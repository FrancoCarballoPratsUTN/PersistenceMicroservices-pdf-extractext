"""Resolución de configuración: variables de entorno o Consul KV."""

import os

from app.config import Settings, get_settings
from app.consul import load_prefix


def settings_from_environment_or_consul() -> Settings:
    """Lee los settings del entorno o de Consul, según CONSUL_ENABLED.

    Cuando Consul está habilitado, lee el prefijo KV y lo inyecta en
    ``get_settings``; en caso contrario, se usa directamente el entorno.
    """
    if os.getenv("CONSUL_ENABLED", "").lower() != "true":
        return get_settings()
    address = os.getenv("CONSUL_HTTP_ADDR", "")
    token = os.getenv("CONSUL_HTTP_TOKEN", "")
    prefix = os.getenv("CONSUL_KV_PREFIX", "")
    values = load_prefix(
        address, token, prefix, ca_file=os.getenv("CONSUL_HTTP_CA_FILE")
    )
    return get_settings(values)
