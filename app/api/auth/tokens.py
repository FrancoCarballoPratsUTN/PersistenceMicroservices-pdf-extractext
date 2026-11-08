"""Constantes y lógica de validación del token Bearer."""

from __future__ import annotations

import secrets

from app.api.problem import instance_of, problem_response
from app.errors import UnauthorizedError

BEARER_SCHEME = "Bearer"

# Las sondas de la plataforma no pueden llevar credenciales (SPEC 3.1), así que
# estas dos quedan abiertas. Cualquier otra ruta, presente o futura, está protegida.
PUBLIC_PATHS = frozenset({"/health", "/readyz"})

REJECTION_DETAIL = "Missing or invalid bearer token."


def rejection_reason(header: str | None, expected_token: str) -> str | None:
    """Explica por qué una credencial no es aceptable, en palabras seguras para el log.

    Args:
        header: La cabecera ``Authorization`` tal cual, o ``None`` cuando quien
            llama no envió ninguna.
        expected_token: El token configurado.

    Returns:
        ``None`` cuando la credencial es válida; en caso contrario, una frase
        breve que nombre el paso que falló. El valor presentado nunca aparece en
        ella.
    """
    if header is None:
        return "missing header"
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != BEARER_SCHEME.lower():
        return "unexpected scheme"
    presented = credentials.strip()
    if not presented:
        return "missing credentials"
    if not secrets.compare_digest(
        presented.encode("utf-8"), expected_token.encode("utf-8")
    ):
        return "token mismatch"
    return None


def unauthorized_response(request) -> object:
    """Devuelve el rechazo 401 con desafío WWW-Authenticate (RFC 6750)."""
    return problem_response(
        UnauthorizedError(REJECTION_DETAIL),
        instance_of(request),
        headers={"WWW-Authenticate": BEARER_SCHEME},
    )
