"""Read-only, hash-pinned text corpora approved for project-wide retrieval.

The approval is for every reader of the project's index, not per-user ACL
enforcement. Operator OAuth reads validate inputs; Search uses its own identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .azure import AzureSession
from .config import FactoryConfig, Target
from .data import json_bytes, require_private_endpoint, sha256

MAX_BYTES = 4 * 1024 * 1024
MAX_DOCUMENTS = 1000
MAX_CONTENT_CHARACTERS = 60000
_HASH = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}")
_STORAGE_ID = re.compile(
    r"/subscriptions/([0-9a-f-]{36})/resourceGroups/([A-Za-z0-9_.-]+)"
    r"/providers/Microsoft\.Storage/storageAccounts/([a-z0-9]{3,24})", re.I,
)
_SHARED_PATH = re.compile(
    r"mlops/v1/projects/project(?P<project>[0-9]{3})/environments/(?P<environment>dev|test|prod)"
    r"/usecases/(?P<use_case>[A-Za-z0-9][A-Za-z0-9_.-]*)/rag/corpora/"
    r"(?P<corpus>[A-Za-z0-9][A-Za-z0-9_.-]*)/versions/"
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9_.-]*)/documents\.jsonl"
)
_PROJECT_FIELDS = {
    "id", "topic", "content", "source_url", "source_version", "license",
    "attribution", "dataset_sha256", "document_url", "content_sha256",
}
_SHARED_FIELDS = {
    "document_id", "text", "source_uri", "source_sha256", "source_version", "acl", "deleted",
}


def _text(value, label: str, limit: int = 4096) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in "\n\r\t" for c in value)):
        raise ValueError(f"{label} must be nonempty bounded text without control characters.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label} must be valid UTF-8 text.") from None
    return value


def _identifier(value, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or ".." in value:
        raise ValueError(f"Invalid literal {label}.")
    return value


def _pin(value, label: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"{label} requires an exact lowercase SHA-256 pin.")
    return value


def _path(value, label: str = "blob path") -> str:
    if (not isinstance(value, str) or len(value) > 1024 or not value
            or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part)
                   or ".." in part for part in value.split("/"))):
        raise ValueError(f"{label} must be a literal relative path; URLs, escapes and traversal are forbidden.")
    return value


def _https_reference(value, label: str) -> str:
    _text(value, label)
    try:
        parsed = urlsplit(value)
        valid = (
            value.startswith("https://") and parsed.scheme == "https"
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and parsed.hostname
            and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", parsed.hostname)
            and not parsed.query and "?" not in value
            and re.fullmatch(r"[A-Za-z0-9/_.-]*", parsed.path)
            and re.fullmatch(r"[A-Za-z0-9_.-]*", parsed.fragment)
            and ".." not in parsed.path
            and not any(c.isspace() for c in value)
            and parsed.hostname.lower() not in {
                "login.microsoftonline.com", "login.live.com", "accounts.google.com",
            }
            and not set(parsed.path.lower().split("/")) & {
                "login", "signin", "sign-in", "authorize", "oauth", "oauth2",
                "token", "access_token", "api_key", "apikey", "sig", "signature",
            }
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{label} requires a credential-free HTTPS reference without query strings or escapes.")
    return value


@dataclass(frozen=True)
class RagSource:
    config: FactoryConfig = field(repr=False, compare=False)
    target: Target = field(repr=False, compare=False)
    location: str
    storage_account_resource_id: str
    container: str
    blob_path: str
    format: str
    sha256: str
    approved_audience: str
    dataset: str
    version: str
    description: str
    provenance: tuple[str, ...] = ()
    manifest_path: str = ""
    manifest_sha256: str = ""
    source_key: str = ""
    aifactory: str = ""

    @classmethod
    def from_binding(cls, binding: dict, config: FactoryConfig, target: Target, *,
                     source_key: str = "") -> RagSource:
        """Bind an explicit config object; never discover or fall back to storage."""
        if not isinstance(binding, dict):
            raise ValueError("A RAG source binding must be an object.")
        allowed = set(cls.__dataclass_fields__) - {"config", "target", "source_key"}
        required = allowed - {"provenance", "manifest_path", "manifest_sha256", "aifactory"}
        if set(binding) - allowed or required - set(binding):
            raise ValueError("RAG source binding has unknown fields or missing required fields.")
        return cls(config=config, target=target, source_key=source_key, **binding)

    def __post_init__(self):
        config, target = self.config, self.target
        for name in ("tenant_id", "subscription_id", "resource_group", "common_resource_group"):
            if getattr(config, name).lower() != getattr(target, name).lower():
                raise ValueError("Source configuration and target must select the same tenant, subscription and groups.")
        if not re.fullmatch(r"[0-9]{3}", config.project_number) or config.environment not in {"dev", "test", "prod"}:
            raise ValueError("The source requires an explicit project number and environment.")
        match = _STORAGE_ID.fullmatch(self.storage_account_resource_id) if isinstance(self.storage_account_resource_id, str) else None
        if not match or match[1].lower() != config.subscription_id.lower():
            raise ValueError("Source storage must be an exact account resource ID in the selected subscription.")
        if self.location not in {"common", "project"}:
            raise ValueError("Source location must be common or project.")
        expected_format = "shared-lake-jsonl" if self.location == "common" else "knowledge-json-array"
        if self.format != expected_format:
            raise ValueError("Common sources require shared-lake-jsonl with project scope and ACL validation; project sources require knowledge-json-array.")
        expected_group = config.common_resource_group if self.location == "common" else config.resource_group
        if match[2].lower() != expected_group.lower():
            raise ValueError("Source storage is outside the selected common/project resource group.")
        storage = match[3]
        if storage != storage.lower() or "1001" in storage:
            raise ValueError("Source storage must be lowercase and must never use the 1001 account.")
        if self.location == "project" and (storage != target.storage_name or "2001" not in storage):
            raise ValueError("Project source storage must be the target's selected 2001 account.")
        if (not isinstance(self.container, str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.container)
                or "--" in self.container):
            raise ValueError("Invalid literal Azure blob container name.")
        _path(self.blob_path)
        _pin(self.sha256, "Source sha256")
        for name in ("dataset", "version"):
            _identifier(getattr(self, name), name)
        if self.source_key:
            _identifier(self.source_key, "source_key")
        if self.aifactory:
            _identifier(self.aifactory, "aifactory")
        _text(self.description, "Source description")
        if self.approved_audience != f"project{config.project_number}":
            raise ValueError("Approve the exact project-wide reader audience; per-user ACLs are not enforced.")
        if not isinstance(self.provenance, (tuple, list)) or len(self.provenance) > 20:
            raise ValueError("Provenance must be a bounded list of HTTPS or literal lake-path references.")
        for reference in self.provenance:
            if isinstance(reference, str) and reference.startswith("https://"):
                _https_reference(reference, "Provenance")
            else:
                _path(reference, "Provenance")
        object.__setattr__(self, "provenance", tuple(self.provenance))
        if self.format == "shared-lake-jsonl":
            scoped = _SHARED_PATH.fullmatch(self.blob_path)
            if (not scoped or scoped["project"] != config.project_number
                    or scoped["environment"] != config.environment
                    or scoped["corpus"] != self.dataset or scoped["version"] != self.version):
                raise ValueError("Shared source path must match the selected project/environment/corpus/version.")
            if self.manifest_path != self.blob_path.rsplit("/", 1)[0] + "/_SUCCESS.json":
                raise ValueError("Shared source requires its exact sibling _SUCCESS.json manifest.")
            _pin(self.manifest_sha256, "Manifest sha256")
        elif self.format == "knowledge-json-array":
            parts = self.blob_path.split("/")
            forbidden = {"raw", "eval", "evals", "evaluation", "evaluations", "ground_truth",
                         "ground-truth", "landing", "training", "fine-tuning", "images", "audio", "tombstones"}
            if parts[-2:] != ["knowledge", "items.json"] or any(p.lower() in forbidden for p in parts[:-2]):
                raise ValueError("Knowledge source must be knowledge/items.json, never raw/evaluation or binary data.")
            if self.manifest_path or self.manifest_sha256:
                raise ValueError("Knowledge arrays use the mandatory blob hash pin, not a snapshot manifest.")
        else:
            raise ValueError("Only shared-lake-jsonl and knowledge-json-array text sources are supported.")

    @property
    def storage_id(self) -> str:
        return self.storage_account_resource_id

    @property
    def storage_name(self) -> str:
        return self.storage_id.rsplit("/", 1)[1]

    @property
    def blob_url(self) -> str:
        return f"https://{self.storage_name}.blob.core.windows.net/{self.container}/{self.blob_path}"

    def as_dict(self) -> dict:
        """A fresh JSON-compatible journal record; never includes credentials."""
        names = set(self.__dataclass_fields__) - {"config", "target"}
        result = {name: getattr(self, name) for name in sorted(names)}
        result["provenance"] = list(self.provenance)
        result.update(tenant_id=self.config.tenant_id, subscription_id=self.config.subscription_id,
                      project_number=self.config.project_number, environment=self.config.environment)
        return result

    @property
    def binding_fingerprint(self) -> str:
        return sha256(json_bytes(self.as_dict()))


class _NoBlobRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RuntimeError("Storage redirected an authenticated read; refusing to forward the bearer token.")


def read_blob(session: AzureSession, source: RagSource, blob_path: str | None = None,
              max_bytes: int = MAX_BYTES) -> bytes:
    """Read only the pinned document blob or pinned snapshot manifest, privately."""
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_BYTES:
        raise ValueError("Blob read limit must be between 1 byte and 4 MiB.")
    if (session.subscription_id.lower() != source.config.subscription_id.lower()
            or session.tenant_id.lower() != source.config.tenant_id.lower()):
        raise ValueError("Blob OAuth session must match the explicitly selected target tenant and subscription.")
    path = source.blob_path if blob_path is None else blob_path
    allowed = {source.blob_path: source.sha256}
    if source.manifest_path:
        allowed[source.manifest_path] = source.manifest_sha256
    if path not in allowed:
        raise ValueError("Only the exact pinned document blob or its pinned _SUCCESS.json may be read.")
    url = f"https://{source.storage_name}.blob.core.windows.net/{source.container}/{path}"
    require_private_endpoint(url)
    request = Request(url, method="GET", headers={
        "Authorization": f"Bearer {session.token('https://storage.azure.com/')}",
        "x-ms-version": "2023-11-03", "Accept-Encoding": "identity",
    })
    try:
        with build_opener(ProxyHandler({}), _NoBlobRedirects()).open(request, timeout=60) as response:
            if response.geturl() != url:
                raise RuntimeError("Storage response URL changed; authenticated redirects are forbidden.")
            if response.status != 200:
                raise RuntimeError(f"Storage read requires HTTP 200, received {response.status}.")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > max_bytes):
                raise ValueError("Blob exceeds the read size limit or has an invalid Content-Length.")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Encoded/compressed source blobs are unsupported; supply pinned UTF-8 text.")
            raw = bytearray()
            while True:
                chunk = response.read(min(64 * 1024, max_bytes + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    raise ValueError("Blob exceeds the read size limit.")
            if length is not None and len(raw) != int(length):
                raise ValueError("Blob read was truncated or differs from Content-Length.")
    except HTTPError as exc:
        status = exc.code
        exc.close()
        advice = ("check Storage Blob Data Reader and private endpoint access" if status in {401, 403}
                  else "check the exact pinned container and blob path" if status == 404
                  else "check private storage connectivity and retry the read")
        raise RuntimeError(f"Storage read failed: HTTP {status}; {advice}. No public or account-key fallback.") from None
    except (URLError, OSError):
        raise RuntimeError("Storage read failed; check private DNS/VNet connectivity. No public fallback.") from None
    result = bytes(raw)
    if sha256(result) != allowed[path]:
        raise ValueError("Blob SHA-256 differs from its approved pin; do not index a changed source.")
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are forbidden.")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite JSON numbers are forbidden.")


def _json(text: str):
    try:
        return json.loads(text, object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError("Malformed JSON in the pinned source; only UTF-8 text records are supported.") from None


def _decode(raw: bytes, pin: str, label: str) -> str:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ValueError(f"{label} is empty or exceeds the 4 MiB size limit.")
    if sha256(raw) != pin:
        raise ValueError(f"{label} SHA-256 differs from the approved pin.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{label} must be UTF-8 text; binary extraction is not supported.") from None
    if "\x00" in text:
        raise ValueError(f"{label} contains NUL characters.")
    return text


def _manifest(source: RagSource, raw: bytes | None) -> dict:
    manifest = _json(_decode(raw, source.manifest_sha256, "Manifest"))
    if not isinstance(manifest, dict):
        raise ValueError("Snapshot manifest must be a JSON object.")
    scope = _SHARED_PATH.fullmatch(source.blob_path)
    expected = {
        "schema": "ml-model-factory-publication/v1", "state": "committed",
        "kind": "rag_snapshot", "format": "jsonl", "project": source.config.project_number,
        "environment": source.config.environment, "use_case": scope["use_case"],
        "key": source.blob_path.rsplit("/", 1)[0],
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Snapshot manifest must be a committed publication of the selected kind, project, environment, use case and version path.")
    _identifier(manifest.get("aifactory"), "manifest aifactory")
    if source.aifactory and manifest["aifactory"] != source.aifactory:
        raise ValueError("Snapshot manifest belongs to a different AI factory.")
    files, index = manifest.get("files"), manifest.get("index")
    if not isinstance(files, dict) or files.get("documents.jsonl") != source.sha256:
        raise ValueError("Snapshot manifest must pin documents.jsonl to the approved source hash.")
    if not isinstance(index, dict) or index.get("deleted_document_ids") != []:
        raise ValueError("Tombstones are unsupported: snapshot deleted_document_ids must be explicitly empty.")
    if type(manifest.get("document_count")) is not int or not 0 < manifest["document_count"] <= MAX_DOCUMENTS:
        raise ValueError("Snapshot document_count must be between 1 and 1000.")
    return manifest


def parse_source(source: RagSource, raw: bytes, manifest_raw: bytes | None = None) -> list[dict]:
    """Validate pins and project-wide approval; project exactly nine Search fields.

    Shared topic/content/source_url map from document_id/text/source_uri.
    Content hashes are checked/computed, not an assertion that the indexer maps
    absent fields. Missing shared license/attribution/dataset_sha256 become None.
    """
    text = _decode(raw, source.sha256, "Source")
    shared = source.format == "shared-lake-jsonl"
    manifest = _manifest(source, manifest_raw) if shared else None
    if shared:
        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        if len(lines) > MAX_DOCUMENTS:
            raise ValueError("Source exceeds the 1000-document limit.")
        rows = [_json(line) for line in lines]
    else:
        if manifest_raw is not None:
            raise ValueError("Knowledge arrays must not supply an unrelated snapshot manifest.")
        rows = _json(text)
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_DOCUMENTS:
        raise ValueError("Source must contain between 1 and 1000 knowledge documents.")
    if manifest and manifest["document_count"] != len(rows):
        raise ValueError("Snapshot document_count differs from documents.jsonl.")
    provenance = (manifest.get("provenance") or {}) if manifest else {}
    if not isinstance(provenance, dict):
        raise ValueError("Snapshot provenance must be an object or null.")
    normalized, seen, seen_ids = [], set(), set()
    for row in rows:
        allowed = _SHARED_FIELDS if shared else _PROJECT_FIELDS
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError("Unexpected source fields; raw/evaluation data and non-text records are forbidden.")
        if shared and (row.get("acl") != [source.approved_audience] or row.get("deleted") is not False):
            raise ValueError("Only live documents with the exact approved project-wide ACL are supported; no per-user ACL enforcement or tombstones.")
        topic = _text(row.get("document_id" if shared else "topic"), "Document topic/id", 1024)
        content = _text(row.get("text" if shared else "content"), "Document content", MAX_CONTENT_CHARACTERS)
        if topic in seen:
            raise ValueError("Duplicate source document id/topic.")
        seen.add(topic)
        if "id" in row:
            original_id = _text(row["id"], "Document id", 1024)
            if original_id in seen_ids:
                raise ValueError("Duplicate source document id.")
            seen_ids.add(original_id)
        digest = sha256(content.encode("utf-8"))
        hash_field = "source_sha256" if shared else "content_sha256"
        if shared or hash_field in row:
            if _pin(row.get(hash_field), hash_field) != digest:
                raise ValueError("Document content hash does not match its exact UTF-8 text.")
        origin = _https_reference(row.get("source_uri" if shared else "source_url"), "Source URL")
        version = _text(row.get("source_version"), "Source version", 256)
        if not shared and version != source.version:
            raise ValueError("Knowledge source_version differs from the bound version.")
        if not shared and row.get("document_url") != source.blob_url:
            raise ValueError("Knowledge document_url must equal the exact bound blob URL.")
        metadata = provenance if shared else row
        license_value = metadata.get("license")
        if not shared or license_value is not None:
            _text(license_value, "License", 1024)
        attribution = metadata.get("attribution")
        if not shared or attribution is not None:
            _text(attribution, "Attribution")
        dataset_hash = metadata.get("dataset_sha256")
        if not shared or dataset_hash is not None:
            _pin(dataset_hash, "Dataset sha256")
        normalized.append({
            "topic": topic, "content": content, "source_url": origin, "source_version": version,
            "license": license_value, "attribution": attribution, "dataset_sha256": dataset_hash,
            "document_url": source.blob_url, "content_sha256": digest,
        })
    return normalized
