"""Cómo llega una petición a los casos de uso.

El servicio lo construye la raíz de composición y se guarda en el estado de la
aplicación, así que este módulo solo lo entrega. Por eso ``app/api`` nunca nombra
un repositorio ni importa pymongo (SPEC 2.1).
"""

from __future__ import annotations

from fastapi import Request

from app.services.text_service import TextService


def get_text_service(request: Request) -> TextService:
    """Devuelve el servicio con el que se construyó la aplicación en marcha.

    Args:
        request: La petición entrante, cuyo estado lleva el servicio.

    Returns:
        El servicio que se encarga de esta petición.
    """
    return request.app.state.text_service
