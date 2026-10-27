from __future__ import annotations

from fastapi import Request

from app.services.text_service import TextService


def get_text_service(request: Request) -> TextService:
    return request.app.state.text_service
