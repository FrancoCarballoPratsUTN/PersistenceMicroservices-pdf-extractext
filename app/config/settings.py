"""Modelo de configuración del servicio."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_api_token: str
    app_name: str = "Persistence Microservice"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "pdf_extractext"
    mongo_texts_collection: str = "texts"
    mongo_timeout_ms: int = 5000
    mongo_socket_timeout_ms: int = 5000
    mongo_max_pool_size: int = 100
    mongo_readiness_cache_ttl_seconds: int = 1
    max_text_body_bytes: int = 10485760
    log_level: str = "INFO"
    cors_allow_origins: tuple[str, ...] = ()
