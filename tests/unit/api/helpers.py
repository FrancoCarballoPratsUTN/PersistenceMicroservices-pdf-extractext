"""Helpers de prueba para el middleware de límite de cuerpo."""

from __future__ import annotations

from typing import Any

from app.api.middleware import BodySizeLimitMiddleware
from app.config import Settings


async def _send_body_through_limit(
    body_messages: list[dict[str, Any]], *, content_length: str | None = None
) -> tuple[int, bytes, list[dict[str, Any]], int]:
    """Envía un cuerpo por partes a través de BodySizeLimitMiddleware."""
    downstream_messages: list[dict[str, Any]] = []
    response_messages: list[dict[str, Any]] = []
    receive_count = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_count
        receive_count += 1
        if body_messages:
            return body_messages.pop(0)
        return {"type": "http.disconnect"}

    async def downstream(scope, receive, send) -> None:
        while True:
            message = await receive()
            downstream_messages.append(message)
            if message["type"] != "http.request" or not message.get(
                "more_body", False
            ):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message: dict[str, Any]) -> None:
        response_messages.append(message)

    headers = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    settings = Settings(
        service_api_token="token-for-tests-0123456789",
        max_text_body_bytes=4,
    )
    middleware = BodySizeLimitMiddleware(downstream, settings=settings)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/texts",
        "raw_path": b"/texts",
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
        "client": ("testclient", 1234),
    }
    await middleware(scope, receive, send)

    status = next(
        message["status"]
        for message in response_messages
        if message["type"] == "http.response.start"
    )
    downstream_body = b"".join(
        message.get("body", b"")
        for message in downstream_messages
        if message["type"] == "http.request"
    )
    return status, downstream_body, downstream_messages, receive_count
