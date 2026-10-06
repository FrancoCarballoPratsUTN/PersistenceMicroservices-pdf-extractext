"""El contrato de cable, declarado una sola vez (T18).

Cinco modelos describen los seis cuerpos que este servicio intercambia, y son el
único sitio donde se escriben esas formas. ``app/api/schemas.py`` deriva de
ellos el documento OpenAPI publicado, así que una regla expresada aquí no puede
alejarse del documento que informa al cliente sobre ella.

Dos trabajos, deliberadamente distintos
--------------------------------------
``CreateTextBody`` y ``UpdateTextBody`` **se validan**: los validadores de la
petición les entregan un body crudo y convierten el rechazo en un ``400``.
``TextOut``, ``AcknowledgementOut`` y ``ProbeOut`` **no**: nada se valida contra
ellos. Existen porque un documento del que nadie deriva el código es un
documento que deriva, y los schemas escritos a mano ya se habían derivado una vez.

Se quedan como modelos y no como ``response_model=`` porque entonces FastAPI
serializaría ``datetime`` con precisión de microsegundos, rompiendo el RFC 3339
con milisegundos que fija SPEC 5.2. ``repositories/serialization.py`` sigue
siendo dueño de ese renderizado.

Por qué este módulo es la parte alta de la capa de API, y no la baja
---------------------------------------------------------------------
``app/services/`` y ``app/use_cases/`` no importan Pydantic: los comandos que
reciben son dataclasses congeladas, y un dominio que hereda el rango de versiones
de una librería ha perdido más de lo que ha ganado. Todo esto es presentación, y
la presentación es exactamente donde pertenece el formato de cable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreateTextBody(BaseModel):
    """El body que acepta ``POST /texts``.

    ``text`` y ``checksum`` son obligatorios y no pueden estar vacíos: un ``_id``
    vacío es un documento al que ninguna petición posterior podría llegar.
    ``name`` y ``metadata`` son opcionales, y una clave que el cliente invente se
    ignora en vez de rechazarse, para que añadir un campo al DTO del orquestador
    no pueda romperlo.
    """

    text: str = Field(min_length=1, description="The extracted text.")
    checksum: str = Field(min_length=1, description="Never format-validated.")
    name: str | None = None
    metadata: dict[str, Any] | None = None


class UpdateTextBody(BaseModel):
    """El body que acepta ``PUT /texts``: sólo lo que cambia.

    Nada es obligatorio. Un campo omitido es *no enviado*, y ``null`` significa
    lo mismo (SPEC 4.3); la cadena vacía y el objeto vacío son valores reales
    que el cliente puede escribir, y el validador los distingue comparando contra
    ``None`` en vez de por su veracidad.
    """

    name: str | None = None
    metadata: dict[str, Any] | None = None


class TextOut(BaseModel):
    """Los seis miembros con los que responden ``GET`` y ``PUT``.

    Ninguno es opcional ni puede ser nulo: ``to_api_dict`` manda ``""`` y ``{}``
    para los que el documento guardado deja vacíos, porque el cliente Go
    decodifica un miembro ausente como su valor cero y si no reportaría datos
    vacíos para un texto que sí tiene nombre.
    """

    checksum: str = Field(description="Never format-validated.")
    text: str
    name: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AcknowledgementOut(BaseModel):
    """Lo que responden ``POST`` y ``DELETE``: qué pasó, y sobre qué.

    ``message`` es siempre ``"OK"``. ``checksum`` es el documento escrito o
    eliminado, devuelto literalmente y sin escapar, porque este cuerpo es dato y
    no una URL.
    """

    message: str = Field(examples=["OK"])
    checksum: str


class ProbeOut(BaseModel):
    """Lo que responden las sondas.

    ``status`` es siempre ``"ok"``. ``mongo`` aparece sólo en ``/readyz``, que es
    la sonda que dice algo sobre la base de datos, así que no puede ser obligatorio.
    """

    status: str = Field(examples=["ok"])
    mongo: str | None = Field(default=None, examples=["ok"])


def schema_of[ModelT: BaseModel](
    model: type[ModelT], description: str
) -> dict[str, Any]:
    """Devuelve el JSON Schema de ``model`` como debe llevarlo el documento.

    Args:
        model: El modelo que describe el body.
        description: Qué significa el body, para quien lea ``/docs``.

    Returns:
        El esquema sin el ``title`` ni el ``description`` de la raíz que Pydantic
        deriva del nombre de la clase y de su docstring, y con ambos sustituidos
        por los nuestros. El componente ya tiene nombre, así que repetirlo en
        cada propiedad es ruido; y estos docstrings son Google-style, cuyos
        bloques ``Args:`` se leen como ruido en un esquema publicado. Las
        descripciones de los *campos* sueltos se conservan: esas están
        escritas para el lector y son parte del contrato.
    """
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.pop("description", None)
    return {"description": description, **_untitled(schema)}


def _untitled(node: Any) -> Any:
    """Devuelve ``node`` sin ninguna clave ``title``, a cualquier profundidad.

    Args:
        node: Un fragmento de un esquema: un objeto, un array de fragmentos, o una
            palabra clave escalar.

    Returns:
        El mismo fragmento sin títulos. Las listas se recorren igual que los
        objetos, porque un ``title`` puede esconderse dentro de una rama
        ``anyOf``.
    """
    if isinstance(node, dict):
        return {key: _untitled(value) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [_untitled(value) for value in node]
    return node
