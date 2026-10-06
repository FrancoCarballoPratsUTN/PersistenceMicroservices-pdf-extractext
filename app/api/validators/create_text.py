"""Validación de la petición de creación (Capa 1).

Body crudo -> :class:`CreateTextCommand`, con las reglas del paso 6 de SPEC 3.4. El
body se comprueba contra :class:`CreateTextBody`, que es también de donde sale el
esquema OpenAPI publicado (T18), así que las reglas y la documentación de las
reglas no pueden separarse.
"""

from __future__ import annotations

from app.api.models import CreateTextBody
from app.api.validators.common import checked
from app.use_cases.ports import CreateTextCommand


def validate(raw: object) -> CreateTextCommand:
    """Convierte un body JSON crudo en un comando, o lo rechaza.

    Args:
        raw: El body tal como llegó del cable.

    Returns:
        El comando sobre el que actuar.

    Raises:
        ValidationError: Si el body no es un objeto, falta un campo obligatorio o
            está en blanco, o un campo tiene el tipo equivocado. El manejador de
            excepciones lo convierte en un ``400`` de problem details.
    """
    body = checked(CreateTextBody, raw)
    return CreateTextCommand(
        checksum=body.checksum,
        text=body.text,
        name=body.name,
        metadata=body.metadata,
    )
