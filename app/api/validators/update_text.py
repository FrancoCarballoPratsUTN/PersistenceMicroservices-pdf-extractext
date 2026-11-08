from __future__ import annotations

from typing import Any

from app.api.models import UpdateTextBody
from app.api.validators.common import checked
from app.errors import ImmutableFieldError, ValidationError
from app.use_cases.ports import TextChanges

IMMUTABLE_FIELDS = ("text", "checksum")


def validate(raw: object) -> TextChanges:
    """Convierte un body JSON crudo en los cambios a aplicar, o lo rechaza.

    Args:
        raw: El body tal como llegó del cable.

    Returns:
        Los cambios que el servicio debe aplicar.

    Raises:
        ImmutableFieldError: Si el body lleva ``text`` o ``checksum``, que este
            endpoint no puede cambiar.
        ValidationError: Si el body no es un objeto, un campo tiene el tipo
            equivocado, o pide ningún cambio.
    """
    body = _mapping(raw)
    _refuse_immutable_fields(body)

    changes = checked(UpdateTextBody, body)
    result = TextChanges(name=changes.name, metadata=changes.metadata)
    if result.name is None and result.metadata is None:
        raise ValidationError("no changes requested")
    return result


def _mapping(raw: object) -> dict[str, Any]:
    """Devuelve ``raw`` como objeto, o lo rechaza con nuestras palabras.
    Args:
        raw: El body tal como llegó del cable.

    Returns:
        El propio body, cuando es un objeto JSON.

    Raises:
        ValidationError: Si es cualquier otra cosa. La redacción es la misma que
            usa ``checked`` para ese mismo rechazo, así que un body que no es un
            objeto se lee igual en los dos verbos.
    """
    if not isinstance(raw, dict):
        raise ValidationError("invalid body")
    return raw


def _refuse_immutable_fields(body: dict[str, Any]) -> None:
    for field in IMMUTABLE_FIELDS:
        if field in body:
            raise ImmutableFieldError(f"immutable field: {field}")
