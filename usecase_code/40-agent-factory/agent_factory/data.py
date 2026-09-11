"""Private, UAMI-only Kaggle ingestion. Run on Azure compute, not an operator PC."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import ipaddress
import json
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from .azure import AzureError, AzureSession
from .config import Target

SEARCH_API = "2026-08-01-preview"
SEARCH_AUDIENCE = "https://search.azure.com"
SEMANTIC_CONFIGURATION = "aif-semantic"
OWNER = "agent-factory:kaggle-rag:v1"
DATASET_URL = "https://www.kaggle.com/datasets/dkhundley/sample-rag-knowledge-item-dataset"
DATASET_VERSION = "1"
DATASET_FILE = "rag_sample_qas_from_kis.csv"
DOWNLOAD_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "dkhundley/sample-rag-knowledge-item-dataset/"
    f"{DATASET_FILE}?datasetVersionNumber={DATASET_VERSION}"
)
ATTRIBUTION = "D. K. Hundley (dkhundley), Sample RAG Knowledge Item Dataset, version 1, MIT"
MAX_DOWNLOAD_BYTES = 4 * 1024 * 1024
MAX_ROWS = 10000
CSV_COLUMNS = ("ki_topic", "ki_text", "sample_question", "sample_ground_truth")


def search_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,126}[a-z0-9]", value):
        raise ValueError("Search resource names must be 3-128 lowercase alphanumeric/hyphen characters.")
    if "--" in value:
        raise ValueError("Search resource names cannot contain consecutive hyphens.")
    return value


def validate_target(target: Target) -> None:
    # This ingestion is deliberately bound to the requested project storage family.
    if not re.fullmatch(r"[a-z0-9]{3,24}", target.storage_name):
        raise ValueError("Invalid project storage account name.")
    if "2001" not in target.storage_name or "1001" in target.storage_name:
        raise ValueError("Refusing storage: the project account must contain 2001, never 1001.")
    search_name(target.search_name)
    UUID(target.identity_client_id)
    expected = (
        f"/subscriptions/{target.subscription_id}/resourceGroups/{target.resource_group}"
        "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
    )
    if not target.identity_id.lower().startswith(expected.lower()):
        raise ValueError("The ingestion UAMI must belong to the selected project resource group.")
    if not re.fullmatch(r"[\w.-]+", target.identity_id[len(expected):]):
        raise ValueError("Invalid project managed identity resource ID.")


def require_private_endpoint(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("An HTTPS Azure private endpoint is required.")
    private_networks = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")))
    try:
        addresses = {ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(parsed.hostname, 443)}
    except OSError as exc:
        raise RuntimeError(f"Private DNS unavailable for {parsed.hostname}; connect the Azure host/VPN.") from exc
    if not addresses or any(not any(address in network for network in private_networks) for address in addresses):
        raise RuntimeError(f"{parsed.hostname} must resolve exclusively to private VNet addresses; no public fallback.")


class _HttpsDatasetRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        parsed = urlsplit(newurl)
        host = parsed.hostname or ""
        allowed = (
            host in {"www.kaggle.com", "kaggle.com", "storage.googleapis.com"}
            or host.endswith(".storage.googleapis.com")
            or host.endswith(".kaggleusercontent.com")
        )
        if parsed.scheme != "https" or not allowed or parsed.username or parsed.password:
            raise RuntimeError("Kaggle redirected outside its approved HTTPS download hosts.")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def download_dataset() -> bytes:
    """Fetch only the pinned public CSV; never send Azure credentials to Kaggle."""
    request = Request(DOWNLOAD_URL, headers={"Accept": "text/csv,application/octet-stream", "User-Agent": "agent-factory/1"})
    try:
        with build_opener(_HttpsDatasetRedirects()).open(request, timeout=60) as response:
            content_type = response.headers.get_content_type().lower()
            if content_type in {"text/html", "application/xhtml+xml"}:
                raise ValueError("Kaggle returned an HTML authentication/challenge page, not the dataset.")
            if content_type not in {"text/csv", "application/csv", "text/plain", "application/octet-stream", "application/vnd.ms-excel"}:
                raise ValueError(f"Unexpected Kaggle content type: {content_type}.")
            length = response.headers.get("Content-Length")
            if length and (not length.isdecimal() or int(length) > MAX_DOWNLOAD_BYTES):
                raise ValueError("Kaggle CSV exceeds the download size limit or has an invalid length.")
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    except HTTPError as exc:
        raise RuntimeError(f"Kaggle CSV download failed: HTTP {exc.code}; no interactive/account-key fallback.") from None
    except URLError:
        # A redirected URL can contain a signed credential. Do not persist/log it.
        raise RuntimeError("Kaggle CSV download failed; check approved outbound HTTPS connectivity.") from None
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Kaggle CSV exceeds the download size limit.")
    if raw.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError("Kaggle returned an HTML authentication/challenge page, not the dataset.")
    return raw


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class Dataset:
    documents: tuple[dict, ...]
    evaluations: tuple[dict, ...]
    raw_sha256: str
    row_count: int


def parse_dataset(raw: bytes) -> Dataset:
    if not raw or len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("The CSV is empty or exceeds the size limit.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The dataset CSV must be UTF-8.") from exc
    if "\x00" in text:
        raise ValueError("The CSV contains invalid NUL characters.")
    if text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise ValueError("Kaggle returned an HTML authentication/challenge page.")
    documents: dict[str, dict] = {}
    evaluations = []
    digest = sha256(raw)
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    try:
        if reader.fieldnames != list(CSV_COLUMNS):
            raise ValueError(f"Malformed Kaggle CSV header; expected {','.join(CSV_COLUMNS)}.")
        for number, row in enumerate(reader, 1):
            if number > MAX_ROWS:
                raise ValueError("The CSV exceeds the row limit.")
            if None in row or any(not isinstance(row.get(key), str) or not row[key].strip() for key in CSV_COLUMNS):
                raise ValueError(f"Malformed or empty CSV fields in data row {number}.")
            topic = row["ki_topic"].strip()
            content = row["ki_text"].replace("\r\n", "\n").replace("\r", "\n").strip()
            document_id = sha256(json_bytes([topic, content]))
            documents[document_id] = {
                "id": document_id, "topic": topic, "content": content,
                "source_url": DATASET_URL, "source_version": DATASET_VERSION,
                "license": "MIT", "attribution": ATTRIBUTION,
                "dataset_sha256": digest, "content_sha256": sha256(content.encode("utf-8")),
            }
            evaluations.append({
                "document_id": document_id, "sample_question": row["sample_question"],
                "sample_ground_truth": row["sample_ground_truth"],
            })
    except csv.Error as exc:
        raise ValueError(f"Malformed Kaggle CSV near line {reader.line_num}.") from exc
    if not documents:
        raise ValueError("The CSV contains no knowledge documents.")
    return Dataset(tuple(documents[key] for key in sorted(documents)), tuple(evaluations), digest, len(evaluations))


def index_schema(index_name: str) -> dict:
    fields = []
    for name in ("id", "topic", "content", "source_url", "source_version", "license",
                 "attribution", "dataset_sha256", "content_sha256", "document_url"):
        fields.append({
            "name": name, "type": "Edm.String", "key": name == "id",
            "searchable": name in {"topic", "content"}, "retrievable": True,
            "filterable": False, "sortable": False, "facetable": False,
        })
    return {
        "name": search_name(index_name), "description": OWNER,
        "fields": fields,
        "semantic": {
            "defaultConfiguration": SEMANTIC_CONFIGURATION,
            "configurations": [{
                "name": SEMANTIC_CONFIGURATION,
                "prioritizedFields": {
                    "titleField": {"fieldName": "topic"},
                    "prioritizedContentFields": [{"fieldName": "content"}],
                    "prioritizedKeywordsFields": [],
                },
            }],
        },
    }


def validate_index(actual: dict, index_name: str) -> None:
    expected = index_schema(index_name)
    if actual.get("name") != index_name or actual.get("description") != OWNER:
        raise ValueError("Existing index is not owned by this factory dataset; refusing a collision.")
    fields = {field["name"]: field for field in actual.get("fields", [])}
    if len(fields) != len(actual.get("fields", [])) or set(fields) != {field["name"] for field in expected["fields"]}:
        raise ValueError("Existing index fields are incompatible (evaluation fields are never permitted).")
    for field in expected["fields"]:
        if any(fields[field["name"]].get(key) != value for key, value in field.items()):
            raise ValueError(f"Incompatible existing index field: {field['name']}.")
        if any(fields[field["name"]].get(key) for key in ("analyzer", "searchAnalyzer", "indexAnalyzer", "synonymMaps")):
            raise ValueError("Existing index uses unexpected analyzers/synonyms; refusing a collision.")
    semantic = actual.get("semantic") or {}
    if semantic.get("defaultConfiguration") != SEMANTIC_CONFIGURATION:
        raise ValueError("A compatible default semantic configuration is required.")
    configurations = semantic.get("configurations", [])
    required = expected["semantic"]["configurations"][0]
    if len(configurations) != 1 or any(configurations[0].get(key) != value for key, value in required.items()):
        raise ValueError("Existing semantic fields/configuration are incompatible.")
    if any(actual.get(key) for key in ("vectorSearch", "scoringProfiles", "defaultScoringProfile", "suggesters")):
        raise ValueError("Existing index has unrelated vector/scoring configuration; refusing to change it.")


def search_url(target: Target, path: str) -> str:
    return f"{target.search_endpoint}/{path}?api-version={SEARCH_API}"


class _ManagedIdentitySession(AzureSession):
    def __init__(self, target: Target, credential):
        super().__init__(target.subscription_id, target.tenant_id)
        self.credential = credential

    def token(self, audience: str) -> str:
        if audience.rstrip("/") != SEARCH_AUDIENCE:
            raise ValueError("The ingestion REST transport only permits the Search audience.")
        return self.credential.get_token(f"{SEARCH_AUDIENCE}/.default").token


def _managed_identity(client_id: str):
    try:
        from azure.identity import ManagedIdentityCredential
    except ImportError as exc:
        raise RuntimeError("Install 43-data\\requirements.txt on the Azure ingestion host.") from exc
    return ManagedIdentityCredential(client_id=client_id)


def _blob_service(account_url: str, credential):
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise RuntimeError("Install 43-data\\requirements.txt on the Azure ingestion host.") from exc
    return BlobServiceClient(account_url=account_url, credential=credential)


def _put_blob(container, name: str, raw: bytes, content_type: str, metadata: dict) -> None:
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import ContentSettings

    blob = container.get_blob_client(name)
    digest = sha256(raw)
    expected_metadata = {**metadata, "sha256": digest, "owner": OWNER}
    try:
        blob.upload_blob(
            raw, overwrite=False, metadata=expected_metadata,
            content_settings=ContentSettings(content_type=content_type),
            validate_content=True,
        )
    except ResourceExistsError:
        properties = blob.get_blob_properties()
        if properties.size != len(raw) or any(properties.metadata.get(key) != value for key, value in expected_metadata.items()):
            raise ValueError(f"Existing Blob is not the identical factory artifact: {name}.") from None
        if sha256(blob.download_blob().readall()) != digest:
            raise ValueError(f"Existing Blob content differs: {name}.")
    properties = blob.get_blob_properties()
    if properties.size != len(raw) or properties.metadata.get("sha256") != digest:
        raise RuntimeError(f"Blob persistence verification failed: {name}.")


def _private_container(service, name: str):
    from azure.core.exceptions import ResourceExistsError

    container = service.get_container_client(name)
    try:
        container.create_container()
    except ResourceExistsError:
        pass
    if container.get_container_properties().get("public_access"):
        raise ValueError("Existing Blob container permits public access; refusing to use or modify it.")
    return container


def _index_inventory(session, target: Target, index_name: str, expected: dict[str, dict]) -> set[str]:
    seen = set()
    for skip in range(0, MAX_ROWS + 1000, 1000):
        result = session.request(
            "POST", search_url(target, f"indexes/{index_name}/docs/search"),
            {"search": "*", "select": "id,dataset_sha256,content_sha256", "top": 1000, "skip": skip, "count": True},
            audience=SEARCH_AUDIENCE,
        )
        count = result.get("@odata.count")
        if not isinstance(count, int) or count > len(expected):
            raise ValueError("Existing index contains unexpected documents; refusing to mix datasets.")
        rows = result.get("value", [])
        for row in rows:
            document = expected.get(row.get("id"))
            if not document or any(row.get(key) != document[key] for key in ("dataset_sha256", "content_sha256")):
                raise ValueError("Existing index document belongs to another dataset/version; refusing overwrite.")
            seen.add(row["id"])
        if len(rows) < 1000:
            if len(seen) != count:
                raise RuntimeError("Search returned an inconsistent document inventory; retry after indexing settles.")
            return seen
    raise RuntimeError("Search inventory exceeded the bounded dataset limit.")


def ingest(target: Target, *, container: str = "agent-factory", prefix: str = "kaggle-rag-v1",
           index_name: str = "aif-kaggle-rag-v1") -> dict:
    """Download and persist using only the explicitly selected Azure-host UAMI."""
    validate_target(target)
    search_name(index_name)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container) or "--" in container:
        raise ValueError("Invalid private Blob container name.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_/-]{0,180}", prefix) or "//" in prefix or prefix.endswith("/"):
        raise ValueError("Invalid Blob artifact prefix.")
    account_url = f"https://{target.storage_name}.blob.core.windows.net"
    require_private_endpoint(account_url)
    require_private_endpoint(target.search_endpoint)
    credential = _managed_identity(target.identity_client_id)
    try:
        # Fail before download/writes when the explicit UAMI is not available.
        credential.get_token("https://storage.azure.com/.default")
        credential.get_token(f"{SEARCH_AUDIENCE}/.default")
        session = _ManagedIdentitySession(target, credential)
        raw = download_dataset()
        dataset = parse_dataset(raw)
        documents = [
            {**doc, "document_url": f"{account_url}/{container}/{prefix}/documents/{doc['id']}.md"}
            for doc in dataset.documents
        ]
        expected = {doc["id"]: doc for doc in documents}
        index_url = search_url(target, f"indexes/{index_name}")
        try:
            existing = session.request("GET", index_url, audience=SEARCH_AUDIENCE)
        except AzureError as exc:
            if exc.status != 404:
                raise
            session.request("PUT", index_url, index_schema(index_name), audience=SEARCH_AUDIENCE,
                            headers={"If-None-Match": "*", "Prefer": "return=representation"})
            existing = session.request("GET", index_url, audience=SEARCH_AUDIENCE)
        validate_index(existing, index_name)
        _index_inventory(session, target, index_name, expected)
        service = _blob_service(account_url, credential)
        try:
            blobs = _private_container(service, container)
            metadata = {"dataset_version": DATASET_VERSION, "dataset_sha256": dataset.raw_sha256, "license": "MIT"}
            _put_blob(blobs, f"{prefix}/raw/{DATASET_FILE}", raw, "text/csv; charset=utf-8", metadata)
            evaluations = b"\n".join(json_bytes(row) for row in dataset.evaluations) + b"\n"
            _put_blob(blobs, f"{prefix}/evaluation/samples.jsonl", evaluations, "application/x-ndjson", metadata)
            for doc in documents:
                _put_blob(blobs, f"{prefix}/documents/{doc['id']}.md", doc["content"].encode("utf-8"),
                          "text/markdown; charset=utf-8", {**metadata, "document_id": doc["id"]})
            manifest = {
                "owner": OWNER, "source_url": DATASET_URL, "download_url": DOWNLOAD_URL,
                "dataset_version": DATASET_VERSION, "license": "MIT", "attribution": ATTRIBUTION,
                "raw_sha256": dataset.raw_sha256, "raw_bytes": len(raw),
                "row_count": dataset.row_count, "document_count": len(documents),
                "evaluation_sha256": sha256(evaluations),
                "documents": [{key: doc[key] for key in ("id", "topic", "content_sha256", "document_url")} for doc in documents],
            }
            _put_blob(blobs, f"{prefix}/manifest.json", json_bytes(manifest), "application/json", metadata)
        finally:
            service.close()
        for offset in range(0, len(documents), 100):
            batch = documents[offset:offset + 100]
            result = session.request(
                "POST", search_url(target, f"indexes/{index_name}/docs/index"),
                {"value": [{"@search.action": "upload", **doc} for doc in batch]}, audience=SEARCH_AUDIENCE,
            )
            statuses = result.get("value", [])
            if len(statuses) != len(batch) or {item.get("key") for item in statuses} != {doc["id"] for doc in batch}:
                raise RuntimeError("Search upload returned incomplete document acknowledgments.")
            failed = [item for item in statuses if item.get("status") is not True]
            if failed:
                codes = sorted({str(item.get("statusCode", "missing")) for item in failed})
                raise RuntimeError(f"Search rejected {len(failed)} documents (status codes {', '.join(codes)}); ingestion incomplete.")
        for attempt in range(10):
            if _index_inventory(session, target, index_name, expected) == set(expected):
                break
            if attempt == 9:
                raise RuntimeError("Search documents did not become queryable within the verification window.")
            time.sleep(3)
        probe = session.request(
            "POST", search_url(target, f"indexes/{index_name}/docs/search"),
            {"search": documents[0]["topic"], "queryType": "semantic",
             "semanticConfiguration": SEMANTIC_CONFIGURATION, "select": "id", "top": 1},
            audience=SEARCH_AUDIENCE,
        )
        if not probe.get("value") or probe["value"][0].get("@search.rerankerScore") is None:
            raise RuntimeError("Semantic ranking did not return grounded documents; check service region, enablement and quota.")
        return {
            "status": "ingested", "storage_account": target.storage_name, "container": container,
            "prefix": prefix, "index_name": index_name, "row_count": dataset.row_count,
            "document_count": len(documents), "evaluation_count": len(dataset.evaluations),
            "raw_sha256": dataset.raw_sha256, "manifest_url": f"{account_url}/{container}/{prefix}/manifest.json",
            "identity_client_id": target.identity_client_id, "embeddings_required": False,
        }
    finally:
        credential.close()
