"""Guardas compartidas por los validadores de la petición (Capa 1).

``checked`` es la frontera entre Pydantic y el vocabulario de errores de este
servicio. Existe porque el rechazo de Pydantic y el nuestro discrepan en dos
cosas que ambas importan: el nuestro es una clase RFC 9457 con un ``code``, y su
``detail`` tiene que ser nuestro.

Por qué el detail se reconstruye en vez de reenviarse
------------------------------------------------------
Un mensaje de Pydantic es prosa inglesa que cambia entre versiones ("String
should have at least 1 character"). ``detail`` es parte del contrato de cable, así
que se reconstruye a partir del nombre del campo, que es vocabulario que este
servicio ya posee. El ``loc`` está vacío exactamente cuando el body no era un
objeto, y ese caso recibe su propia redacción.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.errors import ValidationError


def checked[ModelT: BaseModel](model: type[ModelT], raw: Any) -> ModelT:
    """Valida ``raw`` contra ``model``, o lo rechaza con nuestras palabras.

    Args:
        model: El modelo que describe el body aceptado.
        raw: El body tal como llegó del cable.

    Returns:
        El modelo validado.

    Raises:
        ValidationError: Si el body no encaja en el modelo. El ``detail`` nombra
            el campo culpable, o dice que el body no es un objeto; el manejador
            lo convierte en un ``400`` con la forma de RFC 9457.
    """
    try:
        return model.model_validate(raw)
    except PydanticValidationError as error:
        raise ValidationError(_detail(error)) from error


def _detail(error: PydanticValidationError) -> str:
    """Devuelve la redacción de un rechazo, nombrando el primer campo culpable.

    Args:
        error: El rechazo que produjo Pydantic.

    Returns:
        ``"invalid body"`` cuando el body no era un objeto -- el ``loc`` de tal
        rechazo está vacío -- y ``"invalid <campo>"`` en el resto de casos. El
        nombre del campo se interpola en vez de buscarse en una tabla: los nombres
        pertenecen a este servicio, y una tabla sólo sería un segundo sitio donde
        olvidar uno.
    """
    location = error.errors()[0]["loc"]
    return f"invalid {location[0]}" if location else "invalid body"


def require_str(value: Any) -> str:
    """Devuelve ``value`` si es una cadena no vacía, y lo rechaza en otro caso.

    Args:
        value: El candidato, normalmente un query param.

    Returns:
        La propia cadena.

    Raises:
        ValidationError: Si el valor no es una cadena, o está en blanco. Esta
            guarda protege el query param ``checksum``, que deliberadamente no
            pasa por un modelo: tiene que responder ``400`` y no el ``422`` de
            FastAPI.
    """
    if not isinstance(value, str) or not value:
        raise ValidationError("invalid string")
    return value
