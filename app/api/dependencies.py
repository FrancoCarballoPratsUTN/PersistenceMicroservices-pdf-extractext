"""Inyección de dependencias para la capa de API."""

from __future__ import annotations

from fastapi import Request

from app.services.text_service import TextService


def get_text_service(request: Request) -> TextService:
    """Devuelve el servicio de textos almacenado en el estado de la app.

    Args:
        request: Petición entrante.

    Returns:
        Instancia de :class:`TextService` lista para usar.
    """
    return request.app.state.text_service
