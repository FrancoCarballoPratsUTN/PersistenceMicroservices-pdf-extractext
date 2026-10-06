"""Validación de la petición de actualización (Capa 1).

Body crudo -> :class:`TextChanges`, con la tabla de SPEC 4.3. Los tipos se
comprueban contra :class:`UpdateTextBody`, el mismo modelo del que se genera el
esquema publicado (T18).

Ausente y ``null`` significan lo mismo aquí: *no enviado, déjalo igual*. ``""`` y
``{}`` significan lo contrario, *escribe este valor vacío*, y sólo se distinguen
porque los cambios se comparan contra ``None``.

Por qué los campos inmutables se rechazan antes de que el modelo vea el body
------------------------------------------------------------------------------
``text`` y ``checksum`` son una regla estructural, no de tipos. Comprobarlos
primero garantiza que un ``text`` en el body nunca pase desapercibido, ni
siquiera cuando el resto del body también es inválido, y evita que el código que
lo hace dependa de la política de ``extra`` de un modelo.
"""

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

    A diferencia de la petición de creación, la regla de campos inmutables tiene
    que leer el body como un mapping antes de que pueda hacerlo ningún modelo, así
    que esta guarda no se puede dejar en ``checked``.

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
