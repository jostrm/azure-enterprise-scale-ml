"""State stores: memory (tests), JSON file (local `func start`) and Azure Table Storage (managed identity)."""

from __future__ import annotations

import copy
import itertools
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from ..ports import StoreConflict, StoreMissing

_KEY = re.compile(r"[A-Za-z0-9._:@=+-]{1,256}")


def _check_key(partition: str, key: str) -> None:
    for value in (partition, key):
        if not isinstance(value, str) or not _KEY.fullmatch(value):
            raise ValueError(f"Unsupported store key {value!r}.")


class MemoryStore:
    def __init__(self):
        self._items: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
        self._lock = threading.Lock()
        self._versions = itertools.count(1)

    def _etag(self) -> str:
        return f'W/"{next(self._versions)}"'

    def get(self, partition, key):
        _check_key(partition, key)
        with self._lock:
            item = self._items.get((partition, key))
            return (copy.deepcopy(item[0]), item[1]) if item else None

    def insert(self, partition, key, value):
        _check_key(partition, key)
        with self._lock:
            if (partition, key) in self._items:
                raise StoreConflict(key)
            etag = self._etag()
            self._items[(partition, key)] = (copy.deepcopy(value), etag)
            return etag

    def replace(self, partition, key, value, etag):
        _check_key(partition, key)
        with self._lock:
            item = self._items.get((partition, key))
            if item is None:
                raise StoreMissing(key)
            if item[1] != etag:
                raise StoreConflict(key)
            new_etag = self._etag()
            self._items[(partition, key)] = (copy.deepcopy(value), new_etag)
            return new_etag

    def upsert(self, partition, key, value):
        _check_key(partition, key)
        with self._lock:
            etag = self._etag()
            self._items[(partition, key)] = (copy.deepcopy(value), etag)
            return etag

    def delete(self, partition, key):
        _check_key(partition, key)
        with self._lock:
            self._items.pop((partition, key), None)

    def query(self, partition, *, status=None):
        with self._lock:
            return [(key, copy.deepcopy(value), etag) for (part, key), (value, etag) in self._items.items()
                    if part == partition and (status is None or value.get("status") == status)]


class FileStore(MemoryStore):
    """MemoryStore persisted to one JSON file after every write (single local process only)."""

    def __init__(self, path: str | os.PathLike):
        super().__init__()
        self._path = Path(path)
        if self._path.is_file():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = {(item["partition"], item["key"]): (item["value"], item["etag"]) for item in data["items"]}
            self._versions = itertools.count(int(data.get("version", 0)) + 1)

    def _flush(self) -> None:
        items = [{"partition": p, "key": k, "value": v, "etag": e} for (p, k), (v, e) in self._items.items()]
        version = max([int(e.strip('W/"')) for _, e in self._items.values()] or [0])
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": version, "items": items}, indent=1), encoding="utf-8")
        os.replace(temporary, self._path)

    def insert(self, partition, key, value):
        etag = super().insert(partition, key, value)
        with self._lock:
            self._flush()
        return etag

    def replace(self, partition, key, value, etag):
        new_etag = super().replace(partition, key, value, etag)
        with self._lock:
            self._flush()
        return new_etag

    def upsert(self, partition, key, value):
        etag = super().upsert(partition, key, value)
        with self._lock:
            self._flush()
        return etag

    def delete(self, partition, key):
        super().delete(partition, key)
        with self._lock:
            self._flush()


class TableStore:
    """Azure Table Storage through Entra ID (the Function's managed identity); no account keys.

    Values are JSON split over string properties d0..dN (64 KiB each); `status` is a separate column for queries.
    """

    CHUNK = 30000
    MAX_CHUNKS = 14

    def __init__(self, account: str, table: str, credential=None, endpoint_suffix: str = "core.windows.net"):
        from azure.data.tables import TableServiceClient

        if credential is None:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
        service = TableServiceClient(endpoint=f"https://{account}.table.{endpoint_suffix}", credential=credential)
        self._table = service.create_table_if_not_exists(table)

    def _entity(self, partition, key, value):
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        chunks = [text[i:i + self.CHUNK] for i in range(0, len(text), self.CHUNK)] or [""]
        if len(chunks) > self.MAX_CHUNKS:
            raise ValueError("The record is too large for one table entity.")
        entity = {"PartitionKey": partition, "RowKey": key, "status": str(value.get("status") or ""),
                  "chunks": len(chunks)}
        entity.update({f"d{index}": chunk for index, chunk in enumerate(chunks)})
        return entity

    @staticmethod
    def _value(entity) -> dict[str, Any]:
        return json.loads("".join(entity[f"d{index}"] for index in range(int(entity["chunks"]))))

    def get(self, partition, key):
        from azure.core.exceptions import ResourceNotFoundError

        _check_key(partition, key)
        try:
            entity = self._table.get_entity(partition, key)
        except ResourceNotFoundError:
            return None
        return self._value(entity), entity.metadata["etag"]

    def insert(self, partition, key, value):
        from azure.core.exceptions import ResourceExistsError

        _check_key(partition, key)
        try:
            return self._table.create_entity(self._entity(partition, key, value))["etag"]
        except ResourceExistsError:
            raise StoreConflict(key) from None

    def replace(self, partition, key, value, etag):
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
        from azure.data.tables import UpdateMode

        _check_key(partition, key)
        try:
            return self._table.update_entity(self._entity(partition, key, value), mode=UpdateMode.REPLACE,
                                             etag=etag, match_condition=MatchConditions.IfNotModified)["etag"]
        except ResourceModifiedError:
            raise StoreConflict(key) from None
        except ResourceNotFoundError:
            raise StoreMissing(key) from None

    def upsert(self, partition, key, value):
        from azure.data.tables import UpdateMode

        _check_key(partition, key)
        return self._table.upsert_entity(self._entity(partition, key, value), mode=UpdateMode.REPLACE)["etag"]

    def delete(self, partition, key):
        _check_key(partition, key)
        self._table.delete_entity(partition, key)

    def query(self, partition, *, status=None):
        _check_key(partition, "x")
        if status is None:
            entities = self._table.query_entities("PartitionKey eq @p", parameters={"p": partition})
        else:
            entities = self._table.query_entities("PartitionKey eq @p and status eq @s",
                                                  parameters={"p": partition, "s": status})
        return [(entity["RowKey"], self._value(entity), entity.metadata["etag"]) for entity in entities]
