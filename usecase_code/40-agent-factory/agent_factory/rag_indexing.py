"""Pinned, text-only indexing of verified ADF materializations in project storage."""

from __future__ import annotations

from datetime import datetime
import re
import time
from uuid import UUID

from .azure import ARM, AzureError
from .data import (
    SEARCH_AUDIENCE, index_schema, json_bytes, require_private_endpoint,
    search_url, sha256, validate_index, validate_target,
)
from .knowledge import (
    CONNECTION_API, _base_definition, _compatible, _connection_body, _ensure_search_resource, _source_definition,
)
from .rag_materialization import destination, verify_destination
from .rag_sources import MAX_BYTES, MAX_DOCUMENTS, RagSource, _https_reference, _pin, _text

SEARCH_ARM_API = "2025-05-01"
STORAGE_API = "2023-05-01"
OWNER = "45-rag-agent"
INDEXING_CONTRACT = "adf-materialized/v1"
_FIELDS = ("topic", "content", "source_url", "source_version", "license",
           "attribution", "dataset_sha256", "document_url", "content_sha256")


def artifact_names(source: RagSource) -> dict:
    key = re.sub(r"[^a-z0-9]+", "-", (source.source_key or source.dataset).lower()).strip("-")[:32].rstrip("-")
    fingerprint = sha256(f"{source.binding_fingerprint}|{INDEXING_CONTRACT}".encode("utf-8"))[:12]
    prefix = f"aif-rag-{key}-{fingerprint}"
    return {"indexing_contract": INDEXING_CONTRACT, **{key: f"{prefix}-{suffix}" for key, suffix in (
        ("index_name", "index"), ("data_source_name", "blob"), ("indexer_name", "indexer"),
        ("knowledge_source_name", "source"), ("knowledge_base_name", "knowledge"), ("connection_name", "mcp"),
    )}}


def definitions(source: RagSource) -> dict:
    names = artifact_names(source)
    dest = destination(source)
    owner = f"{OWNER};binding_fingerprint={source.binding_fingerprint};indexing_contract={INDEXING_CONTRACT}"
    shared = source.format == "shared-lake-jsonl"
    mappings = (
        [("/document_id", "topic"), ("/text", "content"), ("/source_uri", "source_url"),
         ("/source_version", "source_version"), ("/source_sha256", "content_sha256"),
         ("metadata_storage_path", "document_url")]
        if shared else [(f"/{field}", field) for field in _FIELDS[:-1]]
    )
    return {
        "index": index_schema(names["index_name"]),
        "data_source": {
            "name": names["data_source_name"], "description": owner, "type": "azureblob",
            "credentials": {"connectionString": f"ResourceId={dest['storage_id']};"},
            "container": {"name": dest["container"], "query": dest["query"]},
        },
        "indexer": {
            "name": names["indexer_name"], "description": owner,
            "dataSourceName": names["data_source_name"], "targetIndexName": names["index_name"],
            "disabled": False,
            "parameters": {
                "maxFailedItems": 0, "maxFailedItemsPerBatch": 0,
                "configuration": {"parsingMode": "jsonLines" if shared else "jsonArray",
                                  "executionEnvironment": "private", "dataToExtract": "contentAndMetadata"},
            },
            "fieldMappings": [
                {"sourceFieldName": "AzureSearch_DocumentKey", "targetFieldName": "id",
                 "mappingFunction": {"name": "base64Encode"}},
                *[{"sourceFieldName": left, "targetFieldName": right} for left, right in mappings],
            ],
        },
    }


def _validate(target, source):
    if not isinstance(source, RagSource) or source.target != target:
        raise ValueError("Indexing must retain the source's original project target.")
    validate_target(target)
    require_private_endpoint(target.search_endpoint)


def _search_id(target):
    return (f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
            f"/providers/Microsoft.Search/searchServices/{target.search_name}")


def _optional(read):
    try:
        return read()
    except AzureError as exc:
        if exc.status != 404:
            raise
        return None


def _collection(session, resource_id, api):
    page = session.arm("GET", resource_id, api_version=api)
    rows, seen = list(page.get("value", [])), set()
    while page.get("nextLink"):
        url = page["nextLink"]
        if url in seen or len(seen) >= 20 or not url.startswith(f"{ARM}{resource_id}?"):
            raise RuntimeError("Unexpected ARM collection continuation.")
        seen.add(url)
        page = session.request("GET", url)
        rows.extend(page.get("value", []))
    return rows


def _child(resource_id, collection):
    return (isinstance(resource_id, str) and resource_id.lower().startswith(collection.lower() + "/")
            and bool(resource_id[len(collection) + 1:]) and "/" not in resource_id[len(collection) + 1:])


def _private_link(session, target):
    collection = _search_id(target) + "/sharedPrivateLinkResources"
    links = _collection(session, collection, SEARCH_ARM_API)
    matches = [link for link in links
               if link.get("properties", {}).get("privateLinkResourceId", "").lower() == target.storage_id.lower()
               and link.get("properties", {}).get("groupId") == "blob"]
    if len(matches) > 1:
        raise ValueError("Ambiguous Blob shared private links for the selected storage.")
    if not matches:
        return None
    link = matches[0]
    props = link.get("properties", {})
    if (not _child(link.get("id"), collection)
            or props.get("privateLinkResourceId", "").lower() != target.storage_id.lower()
            or props.get("groupId") != "blob"):
        raise ValueError("Shared private link is not bound to the selected Search and Blob storage.")
    return link


def _verified_destination(session, target, source):
    verified = verify_destination(session, target, source)
    if (not isinstance(verified, dict) or verified.get("content_verified") is not True
            or verified.get("destination") != destination(source)
            or verified.get("binding_fingerprint") != source.binding_fingerprint
            or verified.get("sha256") != source.sha256
            or type(verified.get("bytes")) is not int or not 0 < verified["bytes"] <= MAX_BYTES):
        raise ValueError("Materialized destination verification differs from the exact source binding and SHA-256.")
    return verified


def _inputs(session, target, source, create):
    bodies = definitions(source)
    name = bodies["index"]["name"]
    url = search_url(target, f"indexes/{name}")
    current = _optional(lambda: session.request("GET", url, audience=SEARCH_AUDIENCE))
    if current is None and create:
        session.request("PUT", url, bodies["index"], audience=SEARCH_AUDIENCE,
                        headers={"If-None-Match": "*", "Prefer": "return=representation"})
        current = session.request("GET", url, audience=SEARCH_AUDIENCE)
    if current is None:
        raise RuntimeError("Pinned Search index is missing; configure indexing first.")
    validate_index(current, name)
    url = search_url(target, f"datasources/{bodies['data_source']['name']}")
    if create:
        _ensure_search_resource(session, url, bodies["data_source"])
    else:
        current = session.request("GET", url, audience=SEARCH_AUDIENCE)
        if not _compatible(current, bodies["data_source"]):
            raise ValueError("Pinned data source changed or credentials are redacted; configure before starting.")


def configure_indexing(session, target, source, *, apply=False):
    """Reuse existing project networking; create Search metadata only after staged SHA verification."""
    _validate(target, source)
    if type(apply) is not bool:
        raise ValueError("apply must be an explicit boolean.")
    dest = destination(source)
    storage = session.arm("GET", target.storage_id, api_version=STORAGE_API).get("properties", {})
    service = session.arm("GET", _search_id(target), api_version=SEARCH_ARM_API)
    props, identity = service.get("properties", {}), service.get("identity", {})
    if (storage.get("publicNetworkAccess", "").lower() != "disabled"
            or storage.get("allowBlobPublicAccess") is not False):
        raise ValueError("Selected staging storage must already be private and forbid anonymous access.")
    if (props.get("publicNetworkAccess", "").lower() != "disabled"
            or props.get("semanticSearch", "").lower() not in {"free", "standard"}):
        raise ValueError("Search must already be private with semantic free/standard; no upgrade is performed.")
    principal = identity.get("principalId")
    if "SystemAssigned" not in identity.get("type", "") or not principal:
        raise ValueError("Search requires its existing system-assigned managed identity.")
    UUID(principal)
    link = _private_link(session, target)
    prerequisites = []
    if not link or link["properties"].get("status") != "Approved" or link["properties"].get("provisioningState") != "Succeeded":
        prerequisites.append("Existing project Search Blob shared private link to selected storage must be Approved/Succeeded.")
    verified = None
    if apply and not prerequisites:
        verified = _verified_destination(session, target, source)
        _inputs(session, target, source, True)
    return {**artifact_names(source), "status": "needs-setup" if prerequisites else "configured" if apply else "ready",
            "prerequisites": prerequisites, "binding_fingerprint": source.binding_fingerprint,
            "search_identity_principal_id": principal, "private_link": link,
            "destination": dest, "destination_verification": verified,
            "storage": target.storage_summary(legacy="agent-factory-rag"),
            "original_source_blob": source.blob_url, "materialized_blob": dest["blob_url"],
            "content_verified": False}


def _execution(response):
    result = response.get("lastResult")
    if response.get("status") != "running":
        raise RuntimeError("Indexer service is not healthy; inspect secured Search diagnostics.")
    if result is None or result.get("status") in {"inProgress", "reset"}:
        return "running"
    if (result.get("status") != "success" or result.get("errors") or result.get("warnings")
            or type(result.get("itemsFailed")) is not int or result["itemsFailed"] != 0
            or type(result.get("itemsProcessed")) is not int or result["itemsProcessed"] < 1):
        raise RuntimeError("Indexer execution failed, warned, or processed no content; no automatic restart.")
    try:
        start, end = (datetime.fromisoformat(result[key].replace("Z", "+00:00")) for key in ("startTime", "endTime"))
        valid = start.tzinfo is not None and end.tzinfo is not None and end >= start
    except (KeyError, TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise RuntimeError("Indexer execution lacks valid start/end evidence.")
    return "success"


def _indexer(session, target, source):
    body = definitions(source)["indexer"]
    url = search_url(target, f"indexers/{body['name']}")
    current = _optional(lambda: session.request("GET", url, audience=SEARCH_AUDIENCE))
    if current is not None and not _compatible(current, body):
        raise ValueError("Existing indexer is incompatible; refusing overwrite or execution.")
    return body, url, current


def start_indexing(session, target, source, *, retry_failed=False):
    if type(retry_failed) is not bool:
        raise ValueError("retry_failed must be an explicit boolean.")
    configured = configure_indexing(session, target, source)
    if configured["status"] != "ready":
        raise RuntimeError("Existing project Search private-link prerequisites are not ready.")
    verified = _verified_destination(session, target, source)
    body, url, current = _indexer(session, target, source)
    _inputs(session, target, source, True)
    if current is None:
        _ensure_search_resource(session, url, body)
        _, _, current = _indexer(session, target, source)
        status = "running"  # Creation is the initial run; never issue a second start.
    else:
        response = session.request("GET", search_url(target, f"indexers/{body['name']}/status"), audience=SEARCH_AUDIENCE)
        last = response.get("lastResult") or {}
        if retry_failed and response.get("status") == "running" and last.get("status") in {
            "transientFailure", "persistentFailure", "success",
        } and (last.get("status") != "success" or last.get("errors") or last.get("warnings")
               or (type(last.get("itemsFailed")) is int and last["itemsFailed"] > 0)
               or (type(last.get("itemsProcessed")) is int and last["itemsProcessed"] == 0)):
            session.request("POST", search_url(target, f"indexers/{body['name']}/run"), audience=SEARCH_AUDIENCE)
            status = "running"
        else:
            status = "reused" if _execution(response) == "success" else "running"
    return {**artifact_names(source), "status": status, "binding_fingerprint": source.binding_fingerprint,
            "storage": target.storage_summary(legacy="agent-factory-rag"),
            "indexer_etag": (current or {}).get("@odata.etag"), "content_verified": False,
            "destination_verification": verified}


def poll_indexing(session, target, source, *, timeout=900, interval=5):
    if type(timeout) is not int or not 0 < timeout <= 900 or type(interval) is not int or not 0 < interval <= timeout:
        raise ValueError("Polling requires integer 0 < interval <= timeout <= 900 seconds.")
    _validate(target, source)
    body, _, current = _indexer(session, target, source)
    if current is None:
        raise RuntimeError("Pinned indexer does not exist; start it explicitly.")
    deadline = time.monotonic() + timeout
    while True:
        response = session.request("GET", search_url(target, f"indexers/{body['name']}/status"), audience=SEARCH_AUDIENCE)
        if _execution(response) == "success":
            _, _, latest = _indexer(session, target, source)
            if latest is None or latest.get("@odata.etag") != current.get("@odata.etag"):
                raise RuntimeError("Pinned indexer version changed during polling; inspect before accepting execution.")
            return {**artifact_names(source), "status": "success", "binding_fingerprint": source.binding_fingerprint,
                    "storage": target.storage_summary(legacy="agent-factory-rag"),
                    "indexer_etag": latest.get("@odata.etag"), "content_verified": False,
                    "execution": {key: response["lastResult"][key] for key in ("startTime", "endTime", "itemsProcessed", "itemsFailed")}}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Pinned indexer still running; resume polling, do not create another run.")
        time.sleep(min(interval, remaining))


def verify_indexed(session, target, source, expected_rows):
    """Independently hash every indexed text; never return corpus text or trust stored hashes."""
    _validate(target, source)
    verified = _verified_destination(session, target, source)
    if not isinstance(expected_rows, (list, tuple)) or not 0 < len(expected_rows) <= MAX_DOCUMENTS:
        raise ValueError("Expected corpus must contain 1-1000 parsed documents.")
    shared = source.format == "shared-lake-jsonl"
    expected = {}
    for row in expected_rows:
        if (not isinstance(row, dict) or set(row) != set(_FIELDS)
                or not isinstance(row.get("topic"), str) or not row["topic"].strip()
                or row["topic"] in expected or not isinstance(row.get("content"), str) or not row["content"].strip()
                or row["document_url"] != source.blob_url
                or sha256(row["content"].encode("utf-8")) != row["content_sha256"]):
            raise ValueError("Expected corpus has invalid fields, duplicates, provenance or content hashes.")
        _https_reference(row["source_url"], "Expected source URL")
        _text(row["source_version"], "Expected source version", 256)
        if not shared and row["source_version"] != source.version:
            raise ValueError("Expected source version differs from the pinned source.")
        for field in ("license", "attribution"):
            if not shared or row[field] is not None:
                _text(row[field], f"Expected {field}")
        if not shared or row["dataset_sha256"] is not None:
            _pin(row["dataset_sha256"], "Expected dataset SHA-256")
        expected[row["topic"]] = row
    name = artifact_names(source)["index_name"]
    validate_index(session.request("GET", search_url(target, f"indexes/{name}"), audience=SEARCH_AUDIENCE), name)
    response = session.request("POST", search_url(target, f"indexes/{name}/docs/search"), {
        "search": "*", "count": True, "top": MAX_DOCUMENTS, "select": ",".join(("id", *_FIELDS)),
    }, audience=SEARCH_AUDIENCE)
    rows = response.get("value", [])
    if (type(response.get("@odata.count")) is not int or response["@odata.count"] != len(expected)
            or len(rows) != len(expected) or response.get("@odata.nextLink") or response.get("@search.nextPageParameters")):
        raise RuntimeError("Indexed count differs from the exact pinned corpus.")
    seen, keys, hashes = set(), set(), []
    fields = ("source_url", "source_version", "content_sha256") if shared else _FIELDS[2:-1]
    document_url = verified["destination"]["blob_url"] if shared else source.blob_url
    for row in rows:
        topic, content, key = row.get("topic"), row.get("content"), row.get("id")
        if (not isinstance(topic, str) or topic not in expected or topic in seen
                or not isinstance(key, str) or not key.strip() or key in keys
                or not isinstance(content, str) or not content.strip()):
            raise RuntimeError("Indexed documents contain invalid, duplicate or unexpected keys/topics/content.")
        digest = sha256(content.encode("utf-8"))
        if digest != expected[topic]["content_sha256"]:
            raise RuntimeError("Indexed content SHA-256 differs from the pinned source.")
        if (row.get("document_url") != document_url
                or any(row.get(field) != expected[topic][field] for field in fields)):
            raise RuntimeError("Indexed mapped provenance differs from the pinned source.")
        if shared and any(row.get(field) is not None for field in ("license", "attribution", "dataset_sha256")):
            raise RuntimeError("Shared index contains unexpected unmapped retrieval metadata.")
        seen.add(topic)
        keys.add(key)
        hashes.append({"topic_sha256": sha256(topic.encode("utf-8")), "content_sha256": digest})
    hashes.sort(key=lambda item: item["topic_sha256"])
    return {**artifact_names(source), "binding_fingerprint": source.binding_fingerprint,
            "storage": target.storage_summary(legacy="agent-factory-rag"),
            "document_count": len(rows), "content_verified": True, "documents": hashes,
            "original_source_blob": source.blob_url, "materialized_blob": verified["destination"]["blob_url"],
            "source_sha256": source.sha256, "materialized_sha256": verified["sha256"],
            "materialized_bytes": verified["bytes"], "destination": verified["destination"],
            "corpus_sha256": sha256(json_bytes(hashes)), "embeddings_required": False}


def verify_retrieval_binding(session, target, source):
    """Check the live retrieval chain, not just a same-name agent or journal."""
    names = artifact_names(source)
    for path, expected in (
        (f"knowledgesources/{names['knowledge_source_name']}",
         _source_definition(names["index_name"], names["knowledge_source_name"])),
        (f"knowledgebases/{names['knowledge_base_name']}",
         _base_definition(names["knowledge_source_name"], names["knowledge_base_name"])),
    ):
        current = session.request("GET", search_url(target, path), audience=SEARCH_AUDIENCE)
        if not _compatible(current, expected):
            raise RuntimeError("Live RAG retrieval binding differs from the pinned source; refusing invocation.")
    connection_id = f"{target.project_id}/connections/{names['connection_name']}"
    endpoint = search_url(target, f"knowledgebases/{names['knowledge_base_name']}/mcp")
    expected = _connection_body(endpoint)["properties"]
    actual = session.arm("GET", connection_id, api_version=CONNECTION_API).get("properties", {})
    if (any(not _compatible(actual.get(key), value) for key, value in expected.items())
            or actual.get("credentials") or actual.get("sharedUserList")):
        raise RuntimeError("Live RAG connection authentication or target changed; refusing invocation.")
