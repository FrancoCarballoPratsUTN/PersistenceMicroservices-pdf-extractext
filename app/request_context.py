"""Contexto de la petición disponible también en las capas internas."""

from contextvars import ContextVar

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
