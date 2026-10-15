"""Exhaustive authorized arithmetic; no oracle, lake listing or shared user cache."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from .identity import NoRedirects, SalesUnavailable


def config_fingerprint(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or
            any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."}
                for part in value.split("/"))):
        raise SalesUnavailable()
    return value


@dataclass
class RowPages:
    rows: list[dict]

    def page(self, cursor: str | None, limit: int) -> dict:
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise SalesUnavailable()
        offset = 0 if cursor is None else int(cursor)
        if offset < 0 or offset > len(self.rows):
            raise SalesUnavailable()
        end = min(offset + limit, len(self.rows))
        return {"rows": self.rows[offset:end], "next": str(end) if end < len(self.rows) else None}


class DelegatedRowStore:
    """Read only the exact allowlisted files, with user OAuth and ETag pinning."""
    def __init__(self, config: dict, *, max_bytes: int = 32 * 1024 * 1024):
        self.config = deepcopy(config)
        self.max_bytes = max_bytes
        account, container = config["storage_account"], config["container"]
        if (not re.fullmatch(r"[a-z0-9]{3,24}", account)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container)
                or "--" in container or type(max_bytes) is not int or max_bytes < 1):
            raise SalesUnavailable()
        self.root = f"https://{account}.blob.core.windows.net/{container}/{_relative_path(config['project_prefix'])}/"

    def _selected(self, partition: dict, kind: str) -> tuple[str, str]:
        matches = [p for p in self.config["partitions"] if p["id"] == partition.get("id")]
        if len(matches) != 1 or matches[0] != partition:
            raise SalesUnavailable()
        path = _relative_path(partition[kind + "_path"])
        required_prefix = "ingestion/" if kind == "input" else "structured/" + partition["id"] + "/"
        digest = partition[kind + "_sha256"]
        if not path.startswith(required_prefix) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise SalesUnavailable()
        return self.root + path, digest

    def _read(self, url: str, identity) -> tuple[bytes, str]:
        allowed = {self._selected(p, kind)[0] for p in self.config["partitions"] for kind in ("input", "rows")}
        if url not in allowed or identity.tenant_id != self.config["tenant_id"]:
            raise SalesUnavailable()
        from agent_factory.data import require_private_endpoint
        require_private_endpoint(url)
        headers = {"Authorization": f"Bearer {identity.storage_token}", "x-ms-version": "2023-11-03"}
        opener = build_opener(ProxyHandler({}), NoRedirects())
        with opener.open(Request(url, headers=headers, method="HEAD"), timeout=45) as response:
            etag = response.headers.get("ETag")
            size = int(response.headers["Content-Length"])
            if not etag or not 0 < size <= self.max_bytes:
                raise SalesUnavailable()
        with opener.open(Request(url, headers={**headers, "If-Match": etag}), timeout=45) as response:
            if response.headers.get("ETag") != etag or int(response.headers["Content-Length"]) != size:
                raise SalesUnavailable()
            raw = response.read(self.max_bytes + 1)
        if len(raw) != size or len(raw) > self.max_bytes:
            raise SalesUnavailable()
        return raw, etag

    def _verified(self, partition: dict, kind: str, identity) -> tuple[bytes, dict]:
        try:
            url, digest = self._selected(partition, kind)
            raw, etag = self._read(url, identity)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise SalesUnavailable()
            return raw, {"url": url, "sha256": digest, "etag": etag}
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            raise SalesUnavailable() from None

    def open_rows(self, partition: dict, identity) -> RowPages:
        try:
            raw, _ = self._verified(partition, "rows", identity)
            lines = raw.decode("utf-8").splitlines()
            if not lines or any(not line.strip() for line in lines):
                raise SalesUnavailable()
            return RowPages([json.loads(line) for line in lines])
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            raise SalesUnavailable() from None

    def read_input(self, partition: dict, identity) -> dict:
        _, receipt = self._verified(partition, "input", identity)
        return receipt

    def read_input_bytes(self, partition: dict, identity) -> bytes:
        raw, _ = self._verified(partition, "input", identity)
        return raw

    def verify_native_denial(self, identity, *, allowed_partition: str) -> bool:
        """Evaluator only: a missing object is not proof of native ACL denial."""
        if identity.tenant_id != self.config["tenant_id"]:
            return False
        denied = [p for p in self.config["partitions"] if p["id"] != allowed_partition]
        if allowed_partition not in {p["id"] for p in self.config["partitions"]} or not denied:
            return False
        opener = build_opener(ProxyHandler({}), NoRedirects())
        headers = {"Authorization": f"Bearer {identity.storage_token}", "x-ms-version": "2023-11-03"}
        for partition in denied:
            for kind in ("input", "rows"):
                url, _ = self._selected(partition, kind)
                try:
                    with opener.open(Request(url, headers=headers, method="HEAD"), timeout=45):
                        return False
                except HTTPError as exc:
                    if exc.code != 403:
                        return False
                except (ValueError, TypeError, KeyError, OSError, RuntimeError):
                    return False
        return True


class SalesRuntime:
    """Adapters are trusted local dependencies, never model-supplied arguments.

    search.verify_partition must enumerate native ACL-protected Search results and
    validate complete chunk content against the pinned source and live successful
    ingestion state. A local readiness marker alone is never sufficient.
    """
    def __init__(self, config: dict, readiness: dict, authorization, store, search, *, page_size: int = 100):
        self.config = deepcopy(config)
        self.readiness = deepcopy(readiness)
        self.authorization, self.store, self.search = authorization, store, search
        if type(page_size) is not int or not 1 <= page_size <= 10000:
            raise ValueError("page_size must be between 1 and 10000.")
        self.page_size = page_size
        self.trace: list[dict] = []

    def _scope(self, source: str):
        if source not in {"all", "json", "excel"}:
            raise SalesUnavailable()
        if (self.readiness.get("state") != "verified"
                or self.readiness.get("config_sha256") != config_fingerprint(self.config)
                or any(self.readiness.get(k) != self.config[k] for k in ("owner", "dataset", "version"))):
            raise SalesUnavailable()
        identity = self.authorization.authorize()
        if identity.tenant_id != self.config["tenant_id"]:
            raise SalesUnavailable()
        partitions = self.config["partitions"]
        if len({p["id"] for p in partitions}) != len(partitions):
            raise SalesUnavailable()
        authorized = [
            p for p in partitions
            if (identity.oid in p.get("allowed_user_ids", [])
                or identity.group_ids.intersection(p.get("allowed_group_ids", [])))
            and (source == "all" or source == p["id"])
        ]
        if not authorized:
            raise SalesUnavailable()
        return identity, authorized

    def _coverage(self, partition: dict, identity) -> dict:
        receipt = self.search.verify_partition(partition, identity)
        if (receipt.get("verified") is not True
                or receipt.get("ingestion_succeeded") is not True
                or receipt.get("chunk_count") != partition["expected_chunks"]
                or receipt.get("input_sha256") != partition["input_sha256"]
                or not isinstance(receipt.get("index"), str) or not receipt["index"]):
            raise SalesUnavailable()
        return receipt

    def _rows(self, partition: dict, identity) -> list[dict]:
        from .arithmetic import validate_row
        reader = self.store.open_rows(partition, identity)
        rows, seen = [], set()
        cursor = None
        for _ in range(100000):
            page = reader.page(cursor, self.page_size)
            incoming, following = page["rows"], page.get("next")
            if not isinstance(incoming, list) or (following is not None and not incoming):
                raise SalesUnavailable()
            for value in incoming:
                validate_row(value, self.config["dataset"], self.config["version"])
            rows.extend(incoming)
            if len(rows) > partition["row_count"]:
                raise SalesUnavailable()
            if following is None:
                break
            if not isinstance(following, str) or following in seen or not following:
                raise SalesUnavailable()
            seen.add(following)
            cursor = following
        else:
            raise SalesUnavailable()
        ids = ("\n".join(sorted(r["sale_id"] for r in rows)) + "\n").encode()
        if (len(rows) != partition["row_count"]
                or hashlib.sha256(ids).hexdigest() != partition["sale_ids_sha256"]):
            raise SalesUnavailable()
        return rows

    def aggregate_sales(self, source: str = "all") -> dict:
        try:
            from .arithmetic import aggregate_records
            identity, partitions = self._scope(source)
            partition_rows, provenance, indexes, accessed_indexes = {}, [], [], []
            for partition in partitions:
                receipt = self._coverage(partition, identity)
                source_receipt = self.store.read_input(partition, identity)
                partition_rows[partition["id"]] = self._rows(partition, identity)
                indexes.append(receipt["index"])
                accessed_indexes.extend(receipt.get("accessed_indexes", [receipt["index"]]))
                provenance.append({
                    "partition": partition["id"], "index": receipt["index"],
                    "input_sha256": partition["input_sha256"], "rows_sha256": partition["rows_sha256"],
                    "chunk_count": receipt["chunk_count"], "source_url": source_receipt["url"],
                    "source_etag": source_receipt["etag"],
                })
            result = aggregate_records(partition_rows)
            result.update({"scope": source, "currency": "USD", "basis": "net pretax",
                           "provenance": provenance, "authorized_scope_only": True})
            self.trace.append({"tool": "aggregate_sales", "arguments": {"source": source},
                               "indexes": indexes, "accessed_indexes": list(dict.fromkeys(accessed_indexes)),
                               "result": deepcopy(result)})
            return result
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            raise SalesUnavailable() from None

    def retrieve_sales(self, question: str) -> dict:
        try:
            if not isinstance(question, str) or not question.strip() or len(question) > 8000:
                raise SalesUnavailable()
            identity, partitions = self._scope("all")
            verified, accessed_indexes = {}, []
            for partition in partitions:
                coverage = self._coverage(partition, identity)
                citation = self.store.read_input(partition, identity)
                verified[partition["id"]] = (coverage, citation["url"])
                accessed_indexes.extend(coverage.get("accessed_indexes", [coverage["index"]]))
            documents = self.search.retrieve(question, partitions, identity)
            evidence = []
            for doc in documents:
                coverage, url = verified[doc["partition"]]
                index = coverage["index"]
                if doc["index"] != index or not isinstance(doc["text"], str):
                    raise SalesUnavailable()
                hashes = coverage.get("chunk_hashes")
                if hashes is not None and hashes.get(doc.get("chunk_id")) != hashlib.sha256(doc["text"].encode()).hexdigest():
                    raise SalesUnavailable()
                evidence.append({"partition": doc["partition"], "index": index,
                                 "text": doc["text"][:8000], "source_url": url})
            result = {"evidence": evidence, "top_k_is_not_arithmetic": True}
            self.trace.append({"tool": "retrieve_sales", "arguments": {"question": question},
                               "indexes": [v[0]["index"] for v in verified.values()],
                               "accessed_indexes": list(dict.fromkeys(accessed_indexes)),
                               "result": deepcopy(result)})
            return result
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            raise SalesUnavailable() from None
