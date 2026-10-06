"""Sustituto en memoria de :class:`pymongo.AsyncMongoClient`.

El ciclo de vida habla con MongoDB a través de una fábrica, de modo que los
tests pueden darle este fake en lugar del cliente real. Nada de lo que hay aquí
abre un socket ni espera un timeout: un ping responde o lanza excepción, ambas
cosas en memoria.

Los documentos viven en un dict plano indexado por ``_id``, que basta para las
operaciones que realiza este servicio.
"""

from typing import Any

from pymongo.errors import (
    DuplicateKeyError,
    OperationFailure,
    ServerSelectionTimeoutError,
)


class FakeDatabase:
    """El handle ``client[database]``, que nombra las colecciones que contiene."""

    def __init__(self, client: FakeMongoClient, name: str) -> None:
        self._client = client
        self._name = name

    async def command(self, name: str) -> dict[str, Any]:
        """Responde a un comando de base de datos como lo haría un servidor
        accesible."""
        if self._client.ping_fails:
            raise ServerSelectionTimeoutError(f"no MongoDB host answered '{name}'")
        self._client.pings += 1
        return {"ok": 1}

    def __getitem__(self, collection: str) -> FakeCollection:
        return FakeCollection(self._client, f"{self._name}.{collection}")


class FakeCollection:
    """El handle ``client[database][collection]``, con las llamadas que hacemos."""

    def __init__(self, client: FakeMongoClient, path: str) -> None:
        self._client = client
        self._path = path

    async def command(self, name: str) -> dict[str, Any]:
        if self._client.ping_fails:
            raise ServerSelectionTimeoutError(f"no MongoDB host answered '{name}'")
        self._client.pings += 1
        return {"ok": 1}

    async def create_index(self, key: Any, **kwargs: Any) -> str:
        if self._client.index_fails:
            raise OperationFailure("cannot create the index")
        self._client.indexes.append((self._path, str(key)))
        return str(key)

    async def insert_one(self, document: dict[str, Any]) -> Any:
        if self._client.insert_error is not None:
            raise self._client.insert_error
        identifier = document.get("_id")
        if identifier in self._client.documents:
            raise DuplicateKeyError(f"duplicate key {identifier}")
        self._client.documents[identifier] = document
        return _Result(inserted_id=identifier)

    async def find_one(
        self,
        filter: dict[str, Any],
        projection: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if self._client.find_error is not None:
            raise self._client.find_error
        document = self._client.documents.get(filter.get("_id"))
        if document is None:
            return None
        if projection is not None:
            return {"_id": document["_id"]}
        return dict(document)

    async def find_one_and_update(
        self, filter: dict[str, Any], update: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any] | None:
        identifier = filter.get("_id")
        document = self._client.documents.get(identifier)
        if document is None:
            return None
        document.update(update.get("$set", {}))
        return dict(document)

    async def delete_one(self, filter: dict[str, Any], **kwargs: Any) -> Any:
        identifier = filter.get("_id")
        if self._client.documents.pop(identifier, None) is None:
            return _Result(deleted_count=0)
        return _Result(deleted_count=1)

    async def count_documents(self, filter: dict[str, Any], **kwargs: Any) -> int:
        return len(self._client.documents)


class _Result:
    """El pequeño reconocimiento que pymongo devuelve tras una escritura."""

    def __init__(self, *, inserted_id: Any = None, deleted_count: int = 0) -> None:
        self.inserted_id = inserted_id
        self.deleted_count = deleted_count


class FakeMongoClient:
    """Un cliente que recuerda cómo se construyó y qué se le pidió.

    Args:
        uri: Cadena de conexión solicitada por la conexión.
        options: Opciones con palabra clave que pasó la conexión.
        ping_fails: Si es verdadero, todo ping lanza excepción, como ante un
            servidor ausente.
        index_fails: Si es verdadero, la creación del índice lanza excepción.
        insert_error: Si está definido, toda inserción lanza este error en lugar de
            almacenar.
        find_error: Si está definido, toda lectura lanza este error en lugar de
            responder.
    """

    def __init__(
        self,
        uri: str,
        options: dict[str, Any],
        *,
        ping_fails: bool,
        index_fails: bool,
        insert_error: Exception | None = None,
        find_error: Exception | None = None,
    ) -> None:
        self.uri = uri
        self.options = options
        self.ping_fails = ping_fails
        self.index_fails = index_fails
        self.insert_error = insert_error
        self.find_error = find_error
        self.pings = 0
        self.indexes: list[tuple[str, str]] = []
        self.documents: dict[Any, dict[str, Any]] = {}
        self.closed = False

    def __getitem__(self, database: str) -> FakeDatabase:
        return FakeDatabase(self, database)

    async def close(self) -> None:
        self.closed = True


class FakeMongoClientFactory:
    """Construye instancias de :class:`FakeMongoClient` y las guarda para las
    aserciones.

    Args:
        ping_fails: Si es verdadero, todo ping lanza excepción, como ocurriría
            contra un servidor que no está ahí.
        index_fails: Si es verdadero, la creación del índice lanza excepción.
    """

    def __init__(
        self,
        *,
        ping_fails: bool = False,
        index_fails: bool = False,
        insert_error: Exception | None = None,
        find_error: Exception | None = None,
    ) -> None:
        self.ping_fails = ping_fails
        self.index_fails = index_fails
        self.insert_error = insert_error
        self.find_error = find_error
        self.clients: list[FakeMongoClient] = []

    def __call__(self, uri: str, **options: Any) -> FakeMongoClient:
        client = FakeMongoClient(
            uri,
            options,
            ping_fails=self.ping_fails,
            index_fails=self.index_fails,
            insert_error=self.insert_error,
            find_error=self.find_error,
        )
        self.clients.append(client)
        return client

    @property
    def client(self) -> FakeMongoClient:
        """El cliente construido hasta ahora. Cada test construye exactamente uno."""
        return self.clients[-1]
