"""Handle fake de colección en memoria para operaciones de MongoDB."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, OperationFailure, ServerSelectionTimeoutError

from tests.fakes.fake_result import _Result

if TYPE_CHECKING:
    from tests.fakes.fake_mongo_client import FakeMongoClient


class FakeCollection:
    """El handle ``client[database][collection]``, con las llamadas que hacemos."""

    def __init__(self, client: "FakeMongoClient") -> None:
        self._client = client

    async def command(self, name: str) -> dict[str, Any]:
        if self._client.ping_fails:
            raise ServerSelectionTimeoutError(
                f"no MongoDB host answered '{name}'"
            )
        self._client.pings += 1
        return {"ok": 1}

    async def create_index(self, key: Any, **kwargs: Any) -> str:
        if self._client.index_fails:
            raise OperationFailure("cannot create the index")
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
        if self._client.update_error is not None:
            raise self._client.update_error
        if kwargs.get("return_document") is not ReturnDocument.AFTER:
            raise AssertionError("update must return the document after the change")
        identifier = filter.get("_id")
        document = self._client.documents.get(identifier)
        if document is None:
            return None
        document.update(update.get("$set", {}))
        return dict(document)

    async def delete_one(self, filter: dict[str, Any], **kwargs: Any) -> Any:
        if self._client.delete_error is not None:
            raise self._client.delete_error
        identifier = filter.get("_id")
        if self._client.documents.pop(identifier, None) is None:
            return _Result(deleted_count=0)
        return _Result(deleted_count=1)

    async def count_documents(self, filter: dict[str, Any], **kwargs: Any) -> int:
        return len(self._client.documents)
