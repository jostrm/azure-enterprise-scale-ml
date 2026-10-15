"""Native ADLS permissions, whole-text splitting, and user-bound Search REST I/O."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

API_VERSION = "2026-08-01-preview"
SEARCH_AUDIENCE = "https://search.azure.com"
METADATA = ("dataset", "version", "source", "site", "library", "source_uri", "input_sha256", "aif48owner")
PERMISSIONS = {"UserIds": "metadata_user_ids", "GroupIds": "metadata_group_ids",
               "RbacScope": "metadata_rbac_scope"}
UNITS = {"utf8": "utf8", "utf16": "utf16", "codepoint": "codePoint"}
CHUNK_SELECT = ",".join(("chunk_id", "parent_id", "chunk_text", *METADATA))


def endpoint(value, suffix):
    parsed = urlsplit(str(value))
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(suffix)
            or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError(f"An explicit canonical HTTPS {suffix} endpoint is required.")
    return f"https://{parsed.hostname}"


def storage_id(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"/subscriptions/[A-Za-z0-9-]+/resourceGroups/[A-Za-z0-9_.()-]+/"
        r"providers/Microsoft\.Storage/storageAccounts/[a-z0-9]{3,24}", value, re.IGNORECASE
    ):
        raise ValueError("An explicit storage-account resource ID is required.")
    return value


def _segment(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError(f"{label} must contain lowercase letters, digits, and single hyphens.")
    return value


def scoped_name(owner, version, partition, role):
    parts = [_segment(value, "Resource namespace") for value in (owner, version, partition, role)]
    name = "-".join(parts)
    return name if len(name) <= 63 else name[:50].rstrip("-") + "-" + hashlib.sha256(name.encode()).hexdigest()[:12]


def _path(value, *, empty=False):
    if empty and value == "":
        return ""
    if (not isinstance(value, str) or not value or value.startswith("/")
            or any(part in ("", ".", "..") for part in value.rstrip("/").split("/"))
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)):
        raise ValueError("Storage paths must be relative, unescaped paths without traversal.")
    return value.rstrip("/")


def _container(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value) or "--" in value:
        raise ValueError("A canonical storage container name is required.")
    return value


def _marker(value):
    return "aif48:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _field(name, kind="Edm.String", **kwargs):
    return {"name": name, "type": kind, "searchable": False, "filterable": False,
            "sortable": False, "facetable": False, "retrievable": True, "stored": True, **kwargs}


def _permission_fields():
    return [
        _field(name, "Edm.String" if name == "RbacScope" else "Collection(Edm.String)",
               filterable=True, retrievable=False, permissionFilter=permission)
        for name, permission in (("UserIds", "userIds"), ("GroupIds", "groupIds"), ("RbacScope", "rbacScope"))
    ]


def build_definitions(config: dict) -> dict:
    """Return a deterministic, local-only plan; no SDK import or network access."""
    config = copy.deepcopy(config)
    search_endpoint = endpoint(config["search_endpoint"], ".search.windows.net")
    embedding_endpoint = endpoint(config["embedding_endpoint"], ".openai.azure.com")
    storage = storage_id(config["storage_resource_id"])
    if storage.rsplit("/", 1)[1].lower() != config["storage_account"].lower():
        raise ValueError("Storage account name and resource ID disagree.")
    container = _container(config["container"])
    prefix = _path(config.get("project_prefix", ""), empty=True)
    for key in ("owner", "dataset", "version"):
        _segment(config[key], key)
    deployment = config["embedding_deployment"]
    if not isinstance(deployment, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", deployment):
        raise ValueError("An explicit embedding deployment is required.")
    partitions = config["partitions"]
    if not isinstance(partitions, list) or not 1 <= len(partitions) <= 8:
        raise ValueError("Provide between one and eight isolated partitions.")
    result, seen_ids, directories = [], set(), set()
    for partition in partitions:
        identifier = _segment(partition["id"], "Partition")
        relative = _path(partition["input_path"])
        if not relative.startswith(f"ingestion/{identifier}/") or "/" not in relative:
            raise ValueError("Each normalized input must be in its own ingestion directory.")
        extension = "." + relative.rsplit(".", 1)[-1].lower()
        if extension not in (".json", ".txt"):
            raise ValueError("Index only whole UTF-8 JSON or normalized Excel text, never source workbooks.")
        directory = "/".join(filter(None, (prefix, relative.rsplit("/", 1)[0]))) + "/"
        if identifier in seen_ids or any(directory.startswith(d) or d.startswith(directory) for d in directories):
            raise ValueError("Partition IDs and ingestion directories must be distinct and nonoverlapping.")
        seen_ids.add(identifier)
        directories.add(directory)
        names = {kind: scoped_name(config["owner"], config["version"], identifier, role)
                 for kind, role in (("datasource", "source"), ("index", "chunks"), ("audit_index", "audit"),
                                    ("skillset", "skills"), ("indexer", "indexer"))}
        description = _marker({"owner": config["owner"], "dataset": config["dataset"],
                               "version": config["version"], "partition": partition,
                               "storage": storage, "container": container, "directory": directory,
                               "embedding": [embedding_endpoint, deployment]})
        metadata = [_field(name, filterable=True) for name in METADATA]
        index = {
            "name": names["index"], "description": description, "permissionFilterOption": "enabled",
            "similarity": {"@odata.type": "#Microsoft.Azure.Search.BM25Similarity"},
            "fields": [
                _field("chunk_id", key=True, filterable=True, sortable=True, searchable=True, analyzer="keyword"),
                _field("parent_id", filterable=True),
                _field("chunk_text", searchable=True),
                _field("chunk_vector", "Collection(Edm.Single)", searchable=True, retrievable=False,
                       stored=False, dimensions=3072, vectorSearchProfile="vector-profile"),
                *metadata, *_permission_fields(),
            ],
            "semantic": {"configurations": [{"name": "sem", "prioritizedFields": {
                "prioritizedContentFields": [{"fieldName": "chunk_text"}], "prioritizedKeywordsFields": [],
            }}]},
            "vectorSearch": {
                "algorithms": [{"name": "hnsw", "kind": "hnsw", "hnswParameters": {
                    "metric": "cosine", "m": 4, "efConstruction": 400, "efSearch": 500}}],
                "profiles": [{"name": "vector-profile", "algorithm": "hnsw", "vectorizer": "aoai"}],
                "vectorizers": [{"name": "aoai", "kind": "azureOpenAI", "azureOpenAIParameters": {
                    "resourceUri": embedding_endpoint, "deploymentId": deployment,
                    "modelName": "text-embedding-3-large"}}],
            },
        }
        audit = {
            "name": names["audit_index"], "description": description, "permissionFilterOption": "enabled",
            "similarity": {"@odata.type": "#Microsoft.Azure.Search.BM25Similarity"},
            "fields": [_field("parent_id", key=True, filterable=True, sortable=True),
                       _field("pages", "Collection(Edm.String)"),
                       _field("split_ordinals", "Collection(Edm.Int64)"),
                       *[_field(f"{kind}_{unit}", "Collection(Edm.Int64)")
                         for kind in ("offsets", "lengths") for unit in UNITS],
                       *copy.deepcopy(metadata), *_permission_fields()],
        }
        datasource = {
            "name": names["datasource"], "description": description, "type": "adlsgen2",
            "credentials": {"connectionString": f"ResourceId={storage};"},
            "container": {"name": container, "query": directory},
            "indexerPermissionOptions": ["userIds", "groupIds", "rbacScope"],
        }
        skillset = {
            "name": names["skillset"], "description": description,
            "skills": [
                {"@odata.type": "#Microsoft.Skills.Text.SplitSkill", "name": "split",
                 "context": "/document", "textSplitMode": "pages", "unit": "azureOpenAITokens",
                 "azureOpenAITokenizerParameters": {"encoderModelName": "cl100k_base"},
                 "maximumPageLength": 6000, "pageOverlapLength": 0, "maximumPagesToTake": 0,
                 "inputs": [{"name": "text", "source": "/document/content"}],
                 "outputs": [{"name": name, "targetName": target} for name, target in (
                     ("textItems", "pages"), ("offsets", "split_offsets"), ("lengths", "split_lengths"),
                     ("ordinalPositions", "split_ordinals"))]},
                {"@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill", "name": "embed",
                 "context": "/document/pages/*", "resourceUri": embedding_endpoint,
                 "deploymentId": deployment, "modelName": "text-embedding-3-large", "dimensions": 3072,
                 "inputs": [{"name": "text", "source": "/document/pages/*"}],
                 "outputs": [{"name": "embedding", "targetName": "chunk_vector"}]},
            ],
            "indexProjections": {
                "selectors": [{
                    "targetIndexName": names["index"], "parentKeyFieldName": "parent_id",
                    "sourceContext": "/document/pages/*",
                    "mappings": [
                        {"name": "chunk_text", "source": "/document/pages/*"},
                        {"name": "chunk_vector", "source": "/document/pages/*/chunk_vector"},
                        *[{"name": name, "source": "/document/metadata_storage_path" if name == "source_uri"
                           else f"/document/{name}"} for name in METADATA],
                        *[{"name": name, "source": f"/document/{source}"} for name, source in PERMISSIONS.items()],
                    ],
                }],
                # A different target index keeps real parent SplitSkill arrays without debug/caching.
                "parameters": {"projectionMode": "includeIndexingParentDocuments"},
            },
        }
        indexer = {
            "name": names["indexer"], "description": description, "dataSourceName": names["datasource"],
            "targetIndexName": names["audit_index"], "skillsetName": names["skillset"],
            "parameters": {"maxFailedItems": 0, "maxFailedItemsPerBatch": 0, "configuration": {
                "parsingMode": "text", "dataToExtract": "contentAndMetadata",
                "executionEnvironment": "private",
                "indexedFileNameExtensions": extension, "failOnUnsupportedContentType": True,
                "failOnUnprocessableDocument": True, "indexStorageMetadataOnlyForOversizedDocuments": False,
            }},
            "fieldMappings": [
                {"sourceFieldName": "metadata_storage_path", "targetFieldName": "parent_id",
                 "mappingFunction": {"name": "base64Encode"}},
                *[{"sourceFieldName": "metadata_storage_path" if name == "source_uri" else name,
                   "targetFieldName": name} for name in METADATA],
                *[{"sourceFieldName": source, "targetFieldName": name} for name, source in PERMISSIONS.items()],
            ],
            "outputFieldMappings": [
                {"sourceFieldName": "/document/pages/*", "targetFieldName": "pages"},
                {"sourceFieldName": "/document/split_ordinals/*", "targetFieldName": "split_ordinals"},
                *[{"sourceFieldName": f"/document/split_{kind}/*/{api_unit}", "targetFieldName": f"{kind}_{unit}"}
                  for kind in ("offsets", "lengths") for unit, api_unit in UNITS.items()],
            ],
        }
        result.append({"id": identifier, "names": names, "input_path": "/".join(filter(None, (prefix, relative))),
                       "resources": {"datasource": datasource, "index": index, "audit_index": audit,
                                     "skillset": skillset, "indexer": indexer}})
    return {"api_version": API_VERSION, "search_endpoint": search_endpoint, "mutations": False,
            "partitions": result}


def _compatible(actual, expected):
    if isinstance(expected, dict):
        return (isinstance(actual, dict)
                and all(key in actual and _compatible(actual[key], value) for key, value in expected.items())
                and all(key in expected or key.startswith("@odata.") or value is None or value == [] or value == {}
                        or value is False or key == "createdResources" or (key == "retrievable" and value is True)
                        for key, value in actual.items()))
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _compatible(a, e) for a, e in zip(actual, expected))
    return type(actual) is type(expected) and actual == expected


def _restore_redacted(actual, expected):
    result, redacted = copy.deepcopy(actual), False
    if isinstance(result, dict) and isinstance(expected, dict):
        for key in expected:
            if key == "connectionString" and result.get(key) in (None, "<REDACTED>") and key in result:
                result[key], redacted = expected[key], True
            elif key in result:
                result[key], nested = _restore_redacted(result[key], expected[key])
                redacted = redacted or nested
    return result, redacted


def ensure_resource(transport, url, body):
    """Create-only or exact reuse; reassert hidden MI credentials under an ETag."""
    created = False
    try:
        current = transport.request("GET", url, audience=SEARCH_AUDIENCE)
    except (RuntimeError, OSError) as exc:
        if getattr(exc, "status", getattr(exc, "code", None)) != 404:
            raise
        transport.request("PUT", url, body, audience=SEARCH_AUDIENCE, headers={"If-None-Match": "*"})
        created = True
        current = transport.request("GET", url, audience=SEARCH_AUDIENCE)
    visible, redacted = _restore_redacted(current, body)
    if current.get("description") != body["description"] or not _compatible(visible, body):
        raise ValueError(f"Existing Search resource {body['name']} is not this exact owned definition.")
    if redacted and not created:
        etag = current.get("@odata.etag")
        if not etag:
            raise ValueError("Cannot reassert redacted managed-identity credentials without an ETag.")
        transport.request("PUT", url, body, audience=SEARCH_AUDIENCE, headers={"If-Match": etag})
        verified = transport.request("GET", url, audience=SEARCH_AUDIENCE)
        if not _compatible(_restore_redacted(verified, body)[0], body):
            raise RuntimeError("Search definition changed while reasserting managed-identity credentials.")


def check_resource(transport, url, body):
    current = transport.request("GET", url, audience=SEARCH_AUDIENCE)
    visible, _ = _restore_redacted(current, body)
    if current.get("description") != body["description"] or not _compatible(visible, body):
        raise ValueError(f"Existing Search resource {body['name']} differs from the exact owned definition.")
    return current


def _user_headers(token):
    if (not isinstance(token, str) or not token or any(c.isspace() for c in token)
            or any(ord(c) < 33 or ord(c) > 126 for c in token)):
        raise ValueError("A raw end-user source authorization token is required; never use a backend fallback.")
    return {"x-ms-query-source-authorization": token}


def _verify_chunks(text, chunks, parent_id, source):
    from .chunks import verify_chunks
    return verify_chunks(text, chunks, parent_id, source)


class SearchClient:
    """Transport is AzureSession-compatible; construction and plan are offline."""

    def __init__(self, config, transport):
        self._plan = build_definitions(config)
        self._config = copy.deepcopy(config)
        self.transport = transport
        self._runs = {}

    def plan(self):
        return copy.deepcopy(self._plan)

    def _url(self, path):
        return f"{self._plan['search_endpoint']}/{path}?api-version={API_VERSION}"

    def _parts(self, partitions=None):
        available = {p["id"]: p for p in self._plan["partitions"]}
        selected = list(available) if partitions is None else partitions
        if (not isinstance(selected, (list, tuple)) or not selected or len(set(selected)) != len(selected)
                or any(p not in available for p in selected)):
            raise ValueError("Select distinct configured partitions only.")
        return [available[p] for p in selected]

    def configure(self, *, apply=False):
        if apply is not True:
            return self.plan()
        for partition in self._parts():
            for key, collection in (("index", "indexes"), ("audit_index", "indexes"),
                                    ("datasource", "datasources"), ("skillset", "skillsets"), ("indexer", "indexers")):
                resource = partition["resources"][key]
                ensure_resource(self.transport, self._url(f"{collection}/{resource['name']}"), resource)
        return {**self.plan(), "mutations": True}

    def _checked_pipelines(self, partitions):
        selected = self._parts(partitions)
        for partition in selected:
            for key, collection in (("index", "indexes"), ("audit_index", "indexes"),
                                    ("datasource", "datasources"), ("skillset", "skillsets"), ("indexer", "indexers")):
                resource = partition["resources"][key]
                check_resource(self.transport, self._url(f"{collection}/{resource['name']}"), resource)
        return selected

    def reset_indexers(self, partitions=None, *, apply=False):
        """Reset change tracking for an explicitly requested full reprocessing; does not run."""
        if apply is not True:
            raise ValueError("Resetting indexers requires apply=True.")
        selected, result = self._checked_pipelines(partitions), {}
        for partition in selected:
            name = partition["names"]["indexer"]
            status = self.transport.request("GET", self._url(f"indexers/{name}/status"), audience=SEARCH_AUDIENCE)
            if (status.get("lastResult") or {}).get("status") == "inProgress":
                raise RuntimeError("Cannot reset an indexer while it is running.")
        for partition in selected:
            result[partition["id"]] = self.transport.request(
                "POST", self._url(f"indexers/{partition['names']['indexer']}/reset"), audience=SEARCH_AUDIENCE)
            self._runs.pop(partition["id"], None)
        return result

    def resync_permissions(self, *, apply=False):
        if apply is not True:
            raise ValueError("Permission resync requires explicit apply=True.")
        selected = self._checked_pipelines(None)
        for partition in selected:
            name = partition["names"]["indexer"]
            status = self.transport.request("GET", self._url(f"indexers/{name}/status"), audience=SEARCH_AUDIENCE)
            if (status.get("lastResult") or {}).get("status") == "inProgress":
                raise RuntimeError("Cannot resync permissions while an indexer is running.")
        for partition in selected:
            name = partition["names"]["indexer"]
            self.transport.request(
                "POST", self._url(f"indexers/{name}/resync"),
                {"options": ["permissions"]}, audience=SEARCH_AUDIENCE,
            )
        return self.run_indexers(apply=True)

    def run_indexers(self, partitions=None, *, apply=False):
        if apply is not True:
            raise ValueError("Running indexers can incur charges and requires apply=True.")
        result = {}
        selected = self._checked_pipelines(partitions)
        for partition in selected:
            resource = partition["resources"]["indexer"]
            status = self.transport.request("GET", self._url(f"indexers/{resource['name']}/status"), audience=SEARCH_AUDIENCE)
            last = status.get("lastResult") or {}
            if last.get("status") == "inProgress":
                raise RuntimeError("Indexer is already running.")
            self._runs[partition["id"]] = last.get("startTime")
            result[partition["id"]] = self.transport.request(
                "POST", self._url(f"indexers/{resource['name']}/run"), audience=SEARCH_AUDIENCE)
        return result

    def wait(self, partitions=None, *, max_polls=60, poll_seconds=5):
        if type(max_polls) is not int or not 1 <= max_polls <= 120 or not 0 <= poll_seconds <= 30:
            raise ValueError("Polling must be bounded to 1..120 attempts and 0..30 seconds.")
        selected, complete = self._parts(partitions), {}
        for attempt in range(max_polls):
            for partition in selected:
                identifier = partition["id"]
                if identifier in complete:
                    continue
                status = self.transport.request(
                    "GET", self._url(f"indexers/{partition['names']['indexer']}/status"), audience=SEARCH_AUDIENCE)
                last = status.get("lastResult") or {}
                if identifier in self._runs and last.get("startTime") == self._runs[identifier]:
                    continue
                state = last.get("status")
                if status.get("status") == "error" or state not in (None, "inProgress", "success"):
                    raise RuntimeError(f"Indexer {identifier} did not succeed: {state or status.get('status')}.")
                if state == "success":
                    if last.get("itemsFailed", 0) or last.get("errors") or last.get("warnings"):
                        raise RuntimeError(f"Indexer {identifier} reported failures or warnings; evidence is incomplete.")
                    complete[identifier] = status
            if len(complete) == len(selected):
                return complete
            if attempt + 1 < max_polls:
                time.sleep(poll_seconds)
        raise TimeoutError("Indexer completion was not observed within the bounded polling budget.")

    def _documents(self, partition, user_token, *, audit=False, max_pages=100):
        headers = _user_headers(user_token)
        if type(max_pages) is not int or not 1 <= max_pages <= 100:
            raise ValueError("Document enumeration is bounded to at most 100 pages.")
        part = self._parts([partition])[0]
        index = part["names"]["audit_index" if audit else "index"]
        url = self._url(f"indexes/{index}/docs/search")
        body = {"search": "*", "top": 1000, "count": True,
                "orderby": ("parent_id" if audit else "chunk_id") + " asc"}
        if not audit:
            body["select"] = CHUNK_SELECT
        rows, seen, expected_count, skip = [], set(), None, 0
        for _ in range(max_pages):
            page = self.transport.request("POST", url, {**body, "skip": skip},
                                          audience=SEARCH_AUDIENCE, headers=headers)
            values = page.get("value")
            if not isinstance(values, list):
                raise ValueError("Search response is missing its document array.")
            count = page.get("@odata.count")
            if type(count) is not int or count < 0 or (expected_count is not None and count != expected_count):
                raise ValueError("Search count is missing, invalid, or changed during enumeration.")
            expected_count = count
            for row in values:
                key = row.get("parent_id" if audit else "chunk_id")
                if not isinstance(key, str) or not key or key in seen:
                    raise ValueError("Missing or repeated document key during enumeration.")
                seen.add(key)
                rows.append(row)
            link = page.get("@odata.nextLink")
            continuation = page.get("@search.nextPageParameters")
            link_skip = None
            if link:
                target = urlsplit(urljoin(url, link))
                original = urlsplit(url)
                query = parse_qs(target.query, keep_blank_values=True)
                paths = {original.path, f"/indexes('{index}')/docs/search.post.search"}
                if (target.scheme != original.scheme or target.netloc != original.netloc
                        or target.path not in paths or target.fragment
                        or query.get("api-version") != [API_VERSION]
                        or set(query) - {"api-version", "$skip", "skip"}):
                    raise ValueError("Untrusted Search continuation URL; credentials were not forwarded.")
                for key in ("$skip", "skip"):
                    if key in query:
                        if link_skip is not None or len(query[key]) != 1 or not query[key][0].isdigit():
                            raise ValueError("Invalid continuation offset.")
                        link_skip = int(query[key][0])
            next_skip = None
            if continuation is not None:
                if not isinstance(continuation, dict) or any(
                    key != "skip"
                    and not (key == "top" and type(value) is int and 1 <= value <= body["top"])
                    and (key not in body or value != body[key])
                    for key, value in continuation.items()
                ):
                    raise ValueError("Continuation cannot change the authorized search request.")
                next_skip = continuation.get("skip")
            if link_skip is not None:
                if next_skip is not None and next_skip != link_skip:
                    raise ValueError("Conflicting continuation offsets.")
                next_skip = link_skip
            if next_skip is None and (len(rows) < expected_count or len(values) == body["top"]):
                next_skip = len(rows)
            if next_skip is None:
                if link or continuation is not None:
                    raise ValueError("Continuation did not provide a progressing offset.")
                if expected_count is not None and len(rows) != expected_count:
                    raise ValueError("Incomplete document enumeration.")
                return rows
            if type(next_skip) is not int or next_skip != len(rows) or next_skip <= skip or next_skip > 100000:
                raise ValueError("Search continuation is noncontiguous, nonprogressing, or out of bounds.")
            skip = next_skip
        raise RuntimeError("Document enumeration exceeded its page budget; no partial result is returned.")

    def enumerate_chunks(self, partition, user_token, *, max_pages=100):
        return self._documents(partition, user_token, max_pages=max_pages)

    def service_evidence(self, partition, user_token):
        """Raw service evidence only; no local splitting and no synthetic offsets."""
        _user_headers(user_token)
        return {"partition": partition, "api_version": API_VERSION,
                "audit": self._documents(partition, user_token, audit=True),
                "chunks": self.enumerate_chunks(partition, user_token)}

    def _runtime_partition(self, partition):
        identifier = partition.get("id") if isinstance(partition, dict) else partition
        matches = [p for p in self._config["partitions"] if p["id"] == identifier]
        if not matches or (isinstance(partition, dict) and partition != matches[0]):
            raise ValueError("Runtime partitions must match the trusted configuration exactly.")
        return matches[0]

    def _identity_token(self, identity):
        token = getattr(identity, "search_token", None)
        _user_headers(token)
        tenant = self._config.get("tenant_id")
        if tenant is not None and getattr(identity, "tenant_id", None) != tenant:
            raise ValueError("User identity belongs to a different configured tenant.")
        return token

    def _check_metadata(self, document, partition):
        expected = {
            "dataset": self._config["dataset"], "version": self._config["version"],
            "aif48owner": self._config["owner"],
            "source": partition.get("source", partition["id"]), "input_sha256": partition["input_sha256"],
            "site": partition.get("site", "retail"), "library": partition.get("library", partition["id"]),
        }
        if any(document.get(key) != value for key, value in expected.items()):
            raise ValueError("Search document metadata differs from the immutable publication.")
        path = self._parts([partition["id"]])[0]["input_path"]
        urls = {f"https://{self._config['storage_account']}.{kind}.core.windows.net/"
                f"{self._config['container']}/{path}" for kind in ("blob", "dfs")}
        if document.get("source_uri") not in urls:
            raise ValueError("Search document source URI escapes the selected immutable input.")

    def verify_partition(self, partition, identity):
        """Runtime gate: live success, native-authorized full text, and pinned source integrity."""
        token = self._identity_token(identity)
        partition = self._runtime_partition(partition)
        identifier = partition["id"]
        if (partition.get("expected_chunks") != 3
                or not re.fullmatch(r"[0-9a-f]{64}", str(partition.get("input_sha256", "")))):
            raise ValueError("Runtime verification requires the pinned three-chunk publication.")
        before = self.wait([identifier], max_polls=1, poll_seconds=0)[identifier]
        evidence = self.service_evidence(identifier, token)
        if len(evidence["audit"]) != 1 or len(evidence["chunks"]) != partition["expected_chunks"]:
            raise ValueError("Search did not return the complete authorized partition.")
        for document in [*evidence["audit"], *evidence["chunks"]]:
            self._check_metadata(document, partition)
        correlated = correlate_evidence(evidence["audit"], evidence["chunks"])
        text = "".join(chunk["chunk_text"] for chunk in correlated)
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != partition["input_sha256"]:
            raise ValueError("Reconstructed service text differs from the pinned source SHA-256.")
        after = self.wait([identifier], max_polls=1, poll_seconds=0)[identifier]
        if before.get("lastResult") != after.get("lastResult"):
            raise ValueError("Indexer execution changed while verifying the partition.")
        parent_id = evidence["audit"][0]["parent_id"]
        verified = _verify_chunks(text, correlated, parent_id, partition.get("source", identifier))
        if (verified.get("verified") is not True or verified.get("chunk_count") != partition["expected_chunks"]
                or verified.get("input_sha256") != partition["input_sha256"]):
            raise ValueError("Chunk verification did not establish the full pinned partition.")
        names = self._parts([identifier])[0]["names"]
        return {**verified, "partition": identifier, "index": names["index"],
                "accessed_indexes": [names["index"], names["audit_index"]],
                "parent_id": parent_id, "ingestion_succeeded": True, "ingestion": after["lastResult"],
                "chunk_hashes": {chunk["chunk_id"]: hashlib.sha256(chunk["chunk_text"].encode("utf-8")).hexdigest()
                                 for chunk in correlated}}

    def retrieve(self, question, partitions, identity):
        """Identity-object adapter for the runtime; top-k remains supporting evidence only."""
        token = self._identity_token(identity)
        if not isinstance(partitions, (list, tuple)) or not partitions:
            raise ValueError("Select configured runtime partitions.")
        selected = [self._runtime_partition(partition) for partition in partitions]
        by_id = {partition["id"]: partition for partition in selected}
        results = self.hybrid(question, [p["id"] for p in selected], token, top=max(5, len(selected)))
        for document in results:
            self._check_metadata(document, by_id[document["partition"]])
            if not isinstance(document.get("chunk_text"), str) or not document["chunk_text"]:
                raise ValueError("Search returned an empty supporting chunk.")
        return [{**document, "index": document["citation"]["index"], "text": document["chunk_text"]}
                for document in results]

    def verify_native_denial(self, identity, *, allowed_partition):
        """Evaluator probe; combine with full-reader positive evidence, never a policy-only pass."""
        try:
            token = self._identity_token(identity)
            allowed = self._runtime_partition(allowed_partition)
            denied = [p for p in self._config["partitions"] if p["id"] != allowed["id"]]
            if not denied:
                return False
            self.verify_partition(allowed, identity)
            for partition in denied:
                self.wait([partition["id"]], max_polls=1, poll_seconds=0)
                for audit in (False, True):
                    try:
                        documents = self._documents(partition["id"], token, audit=audit)
                    except (RuntimeError, OSError) as exc:
                        if getattr(exc, "status", getattr(exc, "code", None)) != 403:
                            return False
                    else:
                        if documents:
                            return False
            return True
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            return False

    def hybrid(self, question, partitions, user_token, *, top=5):
        headers = _user_headers(user_token)
        if not isinstance(question, str) or not question.strip() or len(question) > 8000:
            raise ValueError("A nonempty question of at most 8000 characters is required.")
        selected = self._parts(partitions)
        if type(top) is not int or not len(selected) <= top <= 50:
            raise ValueError("top must cover each selected source and be at most 50.")
        sources = []
        for partition in selected:
            index = partition["names"]["index"]
            response = self.transport.request("POST", self._url(f"indexes/{index}/docs/search"), {
                "search": question, "queryType": "semantic", "semanticConfiguration": "sem",
                "vectorQueries": [{"kind": "text", "text": question, "fields": "chunk_vector",
                                   "k": 50, "exhaustive": False}],
                "select": CHUNK_SELECT, "top": top,
            }, audience=SEARCH_AUDIENCE, headers=headers)
            values = response.get("value")
            if not isinstance(values, list):
                raise ValueError("Search returned no result array.")
            sources.append([{**row, "partition": partition["id"], "citation": {
                "index": index, "chunk_id": row.get("chunk_id"), "parent_id": row.get("parent_id"),
                "source_uri": row.get("source_uri"), "source": row.get("source"),
            }} for row in values])
        # Scores from independent indexes are not comparable; preserve each source's local ranking.
        return [source[position] for position in range(top) for source in sources if position < len(source)][:top]


def correlate_evidence(audit_documents, chunks):
    """Join child text to actual TextSplit arrays; ambiguous repeated text fails closed."""
    results, used = [], set()
    parents = {}
    for audit in audit_documents:
        parent = audit.get("parent_id")
        if not parent or parent in parents:
            raise ValueError("Missing or repeated audit parent.")
        parents[parent] = audit
        pages = audit.get("pages")
        arrays = ["split_ordinals", *[f"{kind}_{unit}" for kind in ("offsets", "lengths") for unit in UNITS]]
        if (not isinstance(pages, list) or not pages or any(not isinstance(p, str) for p in pages)
                or any(not isinstance(audit.get(name), list) or len(audit[name]) != len(pages) for name in arrays)
                or len(set(pages)) != len(pages)):
            raise ValueError("Audit arrays are missing, misaligned, or text-to-ordinal correlation is ambiguous.")
        if (audit["split_ordinals"] != list(range(1, len(pages) + 1))
                or any(type(v) is not int or v < 0 for name in arrays for v in audit[name])):
            raise ValueError("Audit ordinals or offsets are invalid.")
    for chunk in chunks:
        parent = chunk.get("parent_id")
        audit = parents.get(parent)
        if audit is None or chunk.get("chunk_text") not in audit["pages"]:
            raise ValueError("A projected chunk has no exact authorized audit-page match.")
        index = audit["pages"].index(chunk["chunk_text"])
        if (parent, index) in used:
            raise ValueError("Multiple chunks claim the same audit page.")
        used.add((parent, index))
        results.append({**chunk, "ordinal": audit["split_ordinals"][index],
                        "offsets": {api_unit: audit[f"offsets_{unit}"][index] for unit, api_unit in UNITS.items()},
                        "lengths": {api_unit: audit[f"lengths_{unit}"][index] for unit, api_unit in UNITS.items()},
                        **{f"offset_{unit}": audit[f"offsets_{unit}"][index] for unit in UNITS},
                        **{f"length_{unit}": audit[f"lengths_{unit}"][index] for unit in UNITS}})
    if len(used) != sum(len(a["pages"]) for a in parents.values()):
        raise ValueError("Authorized projected chunks do not cover all authorized audit pages.")
    return sorted(results, key=lambda c: (c["parent_id"], c["ordinal"]))
