"""Vocabulario de errores de dominio compartido por las tres capas.

Contrato entre capas
--------------------
La Capa 3 (repositorios) lanza estos errores cuando falla el driver, la Capa 2
(servicios) decide qué fallo significa un caso de uso, y la Capa 1 (api)
traduce uno a un documento de problema RFC 9457. Nada de aquí importa FastAPI,
Starlette ni pymongo, así que el vocabulario sigue siendo utilizable desde
cualquier capa y trivial de testear.

Por qué estas clases llevan un ``status`` HTTP
----------------------------------------------
Un status HTTP sobre un error de dominio parece una fuga entre capas, y se lleva
a propósito. De lo contrario la Capa 1 necesitaría su propia tabla
``{clase de error -> status}``: la misma información en un segundo sitio, libre
de derivar. Una definición, leída por la capa que la necesita.

Atributos de clase frente a atributos de instancia
---------------------------------------------------
``status``, ``code``, ``type_uri``, ``title`` y ``default_detail`` son
``ClassVar``: describen una *clase* de fallo y la comparten todas las
ocurrencias. ``detail`` es por instancia porque describe una ocurrencia, y es el
único sitio donde puede aparecer un dato variable como un checksum.

Los valores de abajo reflejan la sección 6.2 del SPEC fila por fila.
``tests/unit/test_errors.py`` afirma la misma tabla, así que un cambio en
cualquiera de las dos falla ruidosamente.

Los valores de ``title`` y ``default_detail`` son contrato de cable: los lee el
cliente Go, así que no se traducen aunque esta documentación esté en español.
"""

from typing import ClassVar


class ServiceError(Exception):
    """Clase base de todo fallo que este servicio reporta a un cliente.

    La base lleva el contrato de último recurso, así que un error que nunca se
    clasificó se serializa igualmente sin lanzar ``AttributeError`` mientras se
    construye la respuesta.
    """

    status: ClassVar[int] = 500
    code: ClassVar[str] = "INTERNAL_ERROR"
    type_uri: ClassVar[str] = "/problems/internal_error"
    title: ClassVar[str] = "Internal server error"
    default_detail: ClassVar[str] = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class ChecksumAlreadyExistsError(ServiceError):
    """Ya hay un documento guardado con este checksum.

    Se lanza por las dos barreras de duplicado de SPEC 5.3, así que el cliente ve
    un único resultado sea cual sea la barrera que perdiera la carrera.
    """

    status = 409
    code = "CHECKSUM_ALREADY_EXISTS"
    type_uri = "/problems/checksum_already_exists"
    title = "Checksum already exists"
    default_detail = "A document with this checksum already exists."


class TextNotFoundError(ServiceError):
    """La ruta coincidió, pero ningún documento tiene ese checksum."""

    status = 404
    code = "TEXT_NOT_FOUND"
    type_uri = "/problems/text_not_found"
    title = "Text not found"
    default_detail = "No document exists for the requested checksum."


class UnauthorizedError(ServiceError):
    """El token bearer faltaba, venía mal formado o no era el configurado."""

    status = 401
    code = "UNAUTHORIZED"
    type_uri = "/problems/unauthorized"
    title = "Unauthorized"
    default_detail = "A valid bearer token is required."


class ValidationError(ServiceError):
    """El body o el query string de la petición son inválidos estructuralmente.

    Cubre JSON malformado, un body que no es objeto, tipos equivocados, un campo
    obligatorio ausente y un checksum fuera del query string.
    """

    status = 400
    code = "VALIDATION_ERROR"
    type_uri = "/problems/validation_error"
    title = "Request validation error"
    default_detail = "The request body or query parameters are invalid."


class ImmutableFieldError(ServiceError):
    """Un ``PUT`` intentó llevar ``text`` o ``checksum`` en el body."""

    status = 400
    code = "IMMUTABLE_FIELD"
    type_uri = "/problems/immutable_field"
    title = "Immutable field"
    default_detail = "The request tried to modify an immutable field."


class PayloadTooLargeError(ServiceError):
    """El body de la petición, o el documento resultante, excede el tamaño permitido.

    Tiene dos orígenes según SPEC 6.2 (límite del body en la Capa 1, límite BSON
    detectado en la Capa 3 y decidido en la Capa 2) y una respuesta idéntica en
    ambos casos.
    """

    status = 413
    code = "PAYLOAD_TOO_LARGE"
    type_uri = "/problems/payload_too_large"
    title = "Payload too large"
    default_detail = "The document exceeds the maximum allowed size."


class UnsupportedMediaTypeError(ServiceError):
    """El ``Content-Type`` de la petición no fue ``application/json``."""

    status = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    type_uri = "/problems/unsupported_media_type"
    title = "Unsupported media type"
    default_detail = "The request Content-Type must be application/json."


class MethodNotAllowedError(ServiceError):
    """La ruta que coincidió no admite el verbo HTTP."""

    status = 405
    code = "METHOD_NOT_ALLOWED"
    type_uri = "/problems/method_not_allowed"
    title = "Method not allowed"
    default_detail = "The HTTP method is not supported by this resource."


class ResourceNotFoundError(ServiceError):
    """La ruta solicitada no existe.

    Distinta de :class:`TextNotFoundError`: ambas son 404, pero ésta significa que
    la URL está mal mientras aquélla significa que falta el documento.
    """

    status = 404
    code = "NOT_FOUND"
    type_uri = "/problems/not_found"
    title = "Resource not found"
    default_detail = "The requested resource does not exist."


class PersistenceError(ServiceError):
    """MongoDB estaba inalcanzable o devolvió un error del servidor.

    Deliberadamente no hereda de los demás errores: es un 503 sobre
    disponibilidad, no un 409 sobre un documento en conflicto.
    """

    status = 503
    code = "PERSISTENCE_ERROR"
    type_uri = "/problems/persistence_error"
    title = "Persistence unavailable"
    default_detail = "The persistence layer is unavailable."


# Los lanza la capa de persistencia/repositorio y se traducen a las excepciones
# de dominio de servicio/API de arriba. Existen aquí para mantener el repositorio
# libre de conocimiento sobre códigos de estado HTTP cuando eso resulta cómodo en
# los tests.
class DuplicateKeyError(Exception):
    """Error de clave duplicada de MongoDB (pymongo.errors.DuplicateKeyError)."""


class DocumentTooLargeError(Exception):
    """Error de documento demasiado grande de MongoDB.

    Equivale a ``pymongo.errors.DocumentTooLarge``.
    """


class InternalError(ServiceError):
    """Último recurso para una excepción que ninguna capa anticipó.

    Hereda todo el contrato de :class:`ServiceError` en vez de repetirlo: un
    error sin clasificar es exactamente un error interno, y restatear los valores
    daría a las dos definiciones la oportunidad de discrepar.
    """
