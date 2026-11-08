"""Clase base de errores del servicio."""

from typing import ClassVar


class ServiceError(Exception):
    """Clase base de todo fallo que este servicio reporta a un cliente."""

    status: ClassVar[int] = 500
    code: ClassVar[str] = "INTERNAL_ERROR"
    type_uri: ClassVar[str] = "/problems/internal_error"
    title: ClassVar[str] = "Internal server error"
    default_detail: ClassVar[str] = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)
