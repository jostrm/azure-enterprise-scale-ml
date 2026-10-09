"""Owned repository ingestion, durable reconciliation, and scope-filtered retrieval.

Search indexes do not support ARM ownership tags. A deployment-specific, hidden
schema field is their ownership marker; Blob containers and state blobs also
carry ownership metadata. Existing resources without these markers are refused.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.identity import get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery
from azure.storage.blob import BlobServiceClient, ContentSettings
from openai import OpenAI, OpenAIError

from .config import Settings, credential

_LOG = logging.getLogger(__name__)
_SCHEMA = 1
_MANIFEST = "repository-manifest.json"
_PENDING = "repository-pending.json"
_STATUS = "repository-status.json"
_BATCH = 32
_ID = re.compile(r"^[a-f0-9]{64}$")
_HARD_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", "__pycache__", "node_modules", "site-packages", "vendor",
    "deps", "dependencies", "generated", "dist", "build", "output", "outputs",
    "artifacts", ".local", "_legacy", "tests", "test", "unit-tests", "evals",
    "evaluations",
}
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)\b(?:[a-z0-9_]*(?:api_key|apikey|client_secret|access_token|
    refresh_token|password|account_key|accountkey|sas_token|subscription_key)|
    token|secret|connection_string)\b["']?\s*[:=]\s*
    (["'])([^"'\r\n]{1,})\1"""
)
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"(?i)\bAccountKey=[A-Za-z0-9+/]{30,}={0,2}"),
    re.compile(r"(?i)[?&]sig=[A-Za-z0-9%+/]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"),
    re.compile(r"(?i)\bBearer [A-Za-z0-9._~+/-]{24,}={0,2}"),
)


class OwnershipError(RuntimeError):
    """An existing resource or state object is not owned by this deployment."""


class IndexingError(RuntimeError):
    """At least one document operation failed or was not acknowledged."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _matches(path: str, pattern: str) -> bool:
    # fnmatch's **/ is not zero-directory matching; include direct README files.
    patterns = {pattern.replace("\\", "/").casefold()}
    for candidate in tuple(patterns):
        while "/**/" in candidate:
            candidate = candidate.replace("/**/", "/", 1)
            patterns.add(candidate)
    patterns.update(p[3:] for p in tuple(patterns) if p.startswith("**/"))
    return any(fnmatch.fnmatchcase(path.casefold(), p) for p in patterns)


def _excluded(path: str, settings: Settings) -> bool:
    parts = path.casefold().split("/")
    return (
        ("meta" in parts and "graphify" in parts)
        or any(p in {"test", "tests", "testdata", "test_data", "fixtures", "__tests__"} for p in parts)
        or any(p in _HARD_DIRS or "secret" in p or "credential" in p or "generated" in p
            or "eval" in p or p.startswith(".env") for p in parts)
        or parts[-1].startswith("test_")
        or any(_matches(path, p) for p in settings.knowledge.excludes)
    )


def _placeholder(value: str) -> bool:
    return bool(re.match(
        r"(?i)^(?:\$|\{|<|your(?:[_ -]|$)|replace|example|placeholder|dummy|"
        r"changeme|none$|null$|test(?:[_ -]|$)|fake(?:[_ -]|$)|x{4,}|\*{4,}|\.{3,})",
        value.strip(),
    ))


def _credential_line(text: str) -> int | None:
    for number, line in enumerate(text.splitlines(), 1):
        if any(pattern.search(line) for pattern in _SECRET_PATTERNS):
            return number
        for match in _SECRET_ASSIGNMENT.finditer(line):
            value = match.group(2)
            if not _placeholder(value):
                return number
    return None


def _embedding_limit(settings: Settings) -> int:
    # A UTF-8 byte upper bound also bounds byte-BPE tokens without another SDK.
    return min(8191, int(getattr(settings.knowledge, "max_embedding_tokens", 8000)))


def _bounded(text: str, chars: int, byte_limit: int) -> bool:
    return len(text) <= chars and len(text.encode("utf-8")) <= byte_limit


def _split_text(text: str, line: int, chars: int, byte_limit: int):
    if chars < 1 or byte_limit < 4:
        raise ValueError("Embedding/chunk limit is too small.")
    while text:
        end = min(len(text), chars)
        if len(text[:end].encode("utf-8")) > byte_limit:
            low, high = 1, end
            while low < high:
                middle = (low + high + 1) // 2
                if len(text[:middle].encode("utf-8")) <= byte_limit:
                    low = middle
                else:
                    high = middle - 1
            end = low
        if end < len(text):
            newline = text.rfind("\n", 0, end)
            if newline >= 0:
                end = newline + 1
        part, text = text[:end], text[end:]
        yield line, line + part.rstrip("\n").count("\n"), part
        line += part.count("\n")


def _chunk_source(text: str, source_path: str, settings: Settings) -> list[dict]:
    """Keep fitting fences intact; repeat delimiters when a large fence splits."""
    lines = text.splitlines(keepends=True)
    chars = settings.knowledge.chunk_chars
    max_bytes = _embedding_limit(settings)
    heading_stack: list[tuple[int, str]] = []
    heading = source_path
    units = []
    offset = 0
    while offset < len(lines):
        line = lines[offset]
        start = offset + 1
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", line) if source_path.lower().endswith(".md") else None
        title = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line) if not fence and source_path.lower().endswith(".md") else None
        if title:
            level, name = len(title.group(1)), title.group(2).strip()
            heading_stack = [(n, h) for n, h in heading_stack if n < level]
            heading_stack.append((level, name))
            heading = " > ".join(h for _, h in heading_stack)
        heading = heading.encode("utf-8")[:min(512, max_bytes // 4)].decode("utf-8", errors="ignore")
        byte_limit = max_bytes - len(heading.encode("utf-8")) - 2
        if fence:
            marker = fence.group(1)
            end = offset + 1
            closing = re.compile(r"^ {0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$")
            while end < len(lines) and not closing.match(lines[end]):
                end += 1
            closed = end < len(lines)
            block = "".join(lines[offset:end + 1] if closed else lines[offset:end])
            if _bounded(block, chars, byte_limit):
                units.append((start, end + 1 if closed else end, block, heading, bool(title)))
            else:
                opener = line if line.endswith("\n") else line + "\n"
                closer = marker + "\n"
                reserve_chars = len(opener) + len(closer) + 1
                reserve_bytes = len((opener + closer).encode("utf-8")) + 1
                body = "".join(lines[offset + 1:end])
                for first, last, part in _split_text(body, start + 1, chars - reserve_chars, byte_limit - reserve_bytes):
                    wrapped = opener + part + ("" if part.endswith("\n") else "\n") + closer
                    units.append((first, last, wrapped, heading, False))
            offset = end + 1 if closed else end
        else:
            for first, last, part in _split_text(line, start, chars, byte_limit):
                units.append((first, last, part, heading, bool(title)))
            offset += 1
    result = []
    content = ""
    first = last = 0
    active_heading = ""

    def flush():
        if content.strip():
            result.append({"heading": active_heading, "line_start": first,
                           "line_end": last, "content": content})

    for start, end, part, section, new_heading in units:
        limit = max_bytes - len(section.encode("utf-8")) - 2
        if content and (new_heading or section != active_heading or not _bounded(content + part, chars, limit)):
            flush()
            content = ""
        if not content:
            first, active_heading = start, section
        content += part
        last = end
    flush()
    return result


def _revision(root: Path) -> tuple[str | None, set[str], dict[str, str], bool]:
    def git(*args):
        return subprocess.run(
            ["git", "--no-pager", "-C", str(root), *args], capture_output=True,
            timeout=20, check=False,
        )
    try:
        head = git("rev-parse", "HEAD")
        if head.returncode:
            return None, set(), {}, False
        revision = head.stdout.decode("ascii").strip()
        changes = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".")
        prefix_result = git("rev-parse", "--show-prefix")
        tree = git("ls-tree", "-r", "-z", "--full-tree", revision)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None, set(), {}, False
    if (changes.returncode or tree.returncode or prefix_result.returncode
            or not re.fullmatch(r"[a-f0-9]{40,64}", revision)):
        return None, set(), {}, False
    # A root may be a repository subdirectory; git status emits repository paths.
    prefix = prefix_result.stdout.decode("utf-8", errors="replace").strip()
    tracked = {}
    for record in tree.stdout.decode("utf-8", errors="replace").split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, kind, blob_hash = metadata.split()
        if kind == "blob" and mode != "120000" and (not prefix or path.startswith(prefix)):
            tracked[path[len(prefix):]] = blob_hash
    changed = set()
    records = changes.stdout.decode("utf-8", errors="replace").split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        paths = [record[3:]]
        if "R" in record[:2] or "C" in record[:2]:
            if index < len(records):
                paths.append(records[index])
                index += 1
        for path in paths:
            if not prefix or path.startswith(prefix):
                changed.add(path[len(prefix):])
    return revision, changed, tracked, True


def _matches_committed(raw: bytes, blob_hash: str | None) -> bool:
    if not blob_hash:
        return False
    # CRLF checkout conversion is text-equivalent and does not change line citations.
    for body in (raw, raw.replace(b"\r\n", b"\n")):
        value = b"blob " + str(len(body)).encode("ascii") + b"\0" + body
        actual = hashlib.sha256(value).hexdigest() if len(blob_hash) == 64 else hashlib.sha1(value).hexdigest()
        if actual == blob_hash:
            return True
    return False


def _citation(base: str, relative: str, revision: str | None, verified: bool, dirty: bool, path: Path) -> str:
    if not verified or dirty or not revision:
        return path.as_uri()
    parsed = urlsplit(base)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return path.as_uri()
    # Pin GitHub/Azure DevOps-compatible /blob/<ref> citations, not moving main.
    match = re.search(r"/blob/[^/]+(/.*)?$", parsed.path)
    if not match:
        return path.as_uri()
    pinned = parsed.path[:match.start()] + "/blob/" + revision + (match.group(1) or "")
    return urlunsplit((parsed.scheme, parsed.netloc, pinned + "/" + quote(relative, safe="/"), "", ""))


def scan_sources(settings: Settings) -> dict:
    """Offline scan report. A credential/containment violation returns no content."""
    root = settings.knowledge.repository_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository_root must be a directory.")
    revision, changed, tracked, verified = _revision(root)
    documents, blocked, gaps = [], [], []
    paths = []
    excluded_count = 0
    ml_readme = root / "usecase_code" / "30-machine-learning" / "readme.md"
    if (not ml_readme.exists() or ml_readme.is_symlink()
            or not ml_readme.resolve().is_relative_to(root) or not ml_readme.read_bytes().strip()):
        gaps.append({"source_path": "usecase_code/30-machine-learning/readme.md",
                     "reason": "missing_or_blank_initial_machine_learning_readme"})
    for folder, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        parent = Path(folder)
        retained = []
        for name in directories:
            directory = parent / name
            relative = directory.relative_to(root).as_posix()
            if _excluded(relative + "/_", settings):
                excluded_count += 1
            elif directory.is_symlink() or not directory.resolve().is_relative_to(root):
                # Do not traverse junctions/symlinks, even when they target the root.
                blocked.append({"source_path": relative, "reason": "linked_directory"})
            else:
                retained.append(name)
        directories[:] = retained
        for name in files:
            path = parent / name
            relative = path.relative_to(root).as_posix()
            if _excluded(relative, settings) or path.suffix.casefold() not in {".md", ".py"}:
                excluded_count += 1
                continue
            if not any(_matches(relative, pattern) for pattern in settings.knowledge.includes):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                blocked.append({"source_path": relative, "reason": "linked_file"})
                continue
            if path.stat().st_size > settings.knowledge.max_file_bytes:
                gaps.append({"source_path": relative, "reason": "max_file_bytes_exceeded"})
                continue
            raw = path.read_bytes()
            if len(raw) > settings.knowledge.max_file_bytes:
                raise RuntimeError("Source changed size while scanning; retry refresh.")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                gaps.append({"source_path": relative, "reason": "not_utf8_text"})
                continue
            if "\0" in text:
                gaps.append({"source_path": relative, "reason": "binary_content"})
                continue
            secret_line = _credential_line(text)
            if secret_line is not None:
                blocked.append({"source_path": relative, "line": secret_line, "reason": "credential_literal"})
                continue
            if not text.strip():
                gaps.append({"source_path": relative, "reason": "blank_source"})
                continue
            paths.append(relative)
            release = re.fullmatch(r"RELEASE_(.+)\.md", name, flags=re.IGNORECASE)
            source_dirty = not verified or relative in changed or not _matches_committed(raw, tracked.get(relative))
            source_url = _citation(settings.knowledge.source_base_url, relative, revision, verified, source_dirty, path)
            source_hash = _digest(raw)
            for chunk in _chunk_source(text, relative, settings):
                identity = {"source_path": relative, **chunk}
                documents.append({
                    "id": _digest(_canonical(identity)), **identity,
                    "source_hash": source_hash, "content_hash": _digest(chunk["content"]),
                    "source_type": "release" if release else ("markdown" if path.suffix.casefold() == ".md" else "python"),
                    "is_current": release is None, "is_history": release is not None,
                    "release": release.group(1) if release else None,
                    "version": release.group(1) if release else None,
                    "source_revision": revision, "working_tree": source_dirty,
                    "source_url": source_url,
                    "allowed_scope_keys": sorted(settings.scopes),
                })
    return {
        "status": "blocked" if blocked else "scanned",
        "documents": [] if blocked else documents,
        "source_count": len(paths), "document_count": 0 if blocked else len(documents),
        "source_paths": paths, "coverage_gaps": gaps, "blocked": blocked,
        "excluded_count": excluded_count, "repository_revision": revision,
        "revision_verified": verified, "working_tree": bool(changed) or not verified,
    }


class _RenewingLease:
    def __init__(self, blob):
        self.lease = blob.acquire_lease(lease_duration=60)
        self.stop = threading.Event()
        self.error: AzureError | OSError | None = None
        self.renewed_at = time.monotonic()
        self.thread = threading.Thread(target=self._renew, name="knowledge-lease", daemon=True)

    def _renew(self):
        while not self.stop.wait(15):
            try:
                self.lease.renew()
                self.renewed_at = time.monotonic()
            except (AzureError, OSError) as exc:
                self.error = exc
                return

    def check(self):
        if self.error is not None:
            raise RuntimeError("Repository refresh lease renewal failed.") from self.error
        if time.monotonic() - self.renewed_at > 50:
            raise RuntimeError("Repository refresh lease may have expired; refusing further writes.")

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, kind, value, traceback):
        self.stop.set()
        self.thread.join(timeout=35)
        if self.thread.is_alive():
            raise RuntimeError("Repository refresh lease renewal did not finish.")
        try:
            self.lease.release()
        except AzureError:
            if kind is None:
                raise
            _LOG.warning("Lease release failed while refresh was already failing.")


class Knowledge:
    def __init__(self, settings: Settings, cred=None, *, index_client=None,
                 search_client=None, blob_service_client=None, container_client=None,
                 embedding_client=None):
        self.settings = settings
        # Use only the explicit deployment credential policy, never DefaultAzureCredential.
        self.cred = cred if cred is not None else credential(settings)
        azure = settings.azure
        owner_material = {
            "tenant": settings.tenant_id, "agent": settings.agent_name,
            "search": azure.search_endpoint, "index": azure.search_index,
            "storage": azure.storage_endpoint, "container": azure.storage_container,
        }
        self.owner = _digest(_canonical(owner_material))
        self.owner_field = "aifactory_owner_" + self.owner[:32]
        self.index_client = index_client if index_client is not None else SearchIndexClient(
            azure.search_endpoint, self.cred,
        )
        self.search_client = search_client if search_client is not None else SearchClient(
            azure.search_endpoint, azure.search_index, self.cred,
        )
        if container_client is not None:
            self.container = container_client
        else:
            service = blob_service_client if blob_service_client is not None else BlobServiceClient(
                azure.storage_endpoint, credential=self.cred,
                connection_timeout=5, read_timeout=15, retry_total=0,
            )
            self.container = service.get_container_client(azure.storage_container)
        self.embedding_client = embedding_client if embedding_client is not None else OpenAI(
            base_url=azure.openai_endpoint.rstrip("/") + "/",
            api_key=get_bearer_token_provider(self.cred, "https://cognitiveservices.azure.com/.default"),
            timeout=60, max_retries=2,
        )

    def _index_definition(self) -> SearchIndex:
        azure = self.settings.azure
        scalar = SearchFieldDataType
        fields = [
            SimpleField(name="id", type=scalar.String, key=True),
            SearchableField(name="heading", type=scalar.String),
            SearchableField(name="content", type=scalar.String),
            SearchField(name="contentVector", type=scalar.Collection(scalar.Single),
                        searchable=True, hidden=True,
                        vector_search_dimensions=azure.embedding_dimensions,
                        vector_search_profile_name="repository-hnsw"),
        ]
        for name in ("source_path", "source_hash", "content_hash", "source_type", "release",
                     "version", "source_revision", "source_url"):
            fields.append(SimpleField(name=name, type=scalar.String, filterable=name != "source_url"))
        for name in ("is_current", "is_history", "working_tree"):
            fields.append(SimpleField(name=name, type=scalar.Boolean, filterable=True))
        for name in ("line_start", "line_end"):
            fields.append(SimpleField(name=name, type=scalar.Int32))
        fields.extend([
            SimpleField(name="ingested_at", type=scalar.DateTimeOffset, filterable=True, sortable=True),
            SimpleField(name="allowed_scope_keys", type=scalar.Collection(scalar.String), filterable=True),
            SimpleField(name=self.owner_field, type=scalar.String, hidden=True),
        ])
        return SearchIndex(
            name=azure.search_index, fields=fields,
            vector_search=VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(
                    name="repository-hnsw-algorithm",
                    parameters=HnswParameters(metric="cosine", m=4, ef_construction=400, ef_search=500),
                )],
                profiles=[VectorSearchProfile(name="repository-hnsw", algorithm_configuration_name="repository-hnsw-algorithm")],
            ),
            semantic_search=SemanticSearch(configurations=[
                SemanticConfiguration(
                    name=azure.semantic_configuration,
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="heading"),
                        content_fields=[SemanticField(field_name="content")],
                    ),
                ),
            ]),
        )

    def _verify_index(self, actual):
        expected = self._index_definition()
        fields = {field.name: field for field in actual.fields}
        if self.owner_field not in fields:
            raise OwnershipError("Search index name collision: ownership marker is missing.")
        if set(fields) != {field.name for field in expected.fields}:
            raise OwnershipError("Owned Search index has an incompatible field set; no overwrite attempted.")
        properties = (
            "type", "key", "searchable", "filterable", "sortable", "hidden",
            "vector_search_dimensions", "vector_search_profile_name",
        )
        for field in expected.fields:
            for name in properties:
                wanted, found = getattr(field, name, None), getattr(fields[field.name], name, None)
                if isinstance(wanted, bool) or name in {"key", "searchable", "filterable", "sortable", "hidden"}:
                    wanted, found = bool(wanted), bool(found)
                if found != wanted:
                    raise OwnershipError(f"Owned Search index field {field.name} is incompatible.")
        if not actual.vector_search or not actual.semantic_search:
            raise OwnershipError("Owned Search index is missing vector or semantic configuration.")
        profiles = {p.name: p.algorithm_configuration_name for p in actual.vector_search.profiles or []}
        algorithms = {a.name: a.kind for a in actual.vector_search.algorithms or []}
        if (profiles.get("repository-hnsw") != "repository-hnsw-algorithm"
                or algorithms.get("repository-hnsw-algorithm") != "hnsw"):
            raise OwnershipError("Owned Search index vector configuration is incompatible.")
        hnsw = next(a for a in actual.vector_search.algorithms if a.name == "repository-hnsw-algorithm")
        if not hnsw.parameters or hnsw.parameters.metric != "cosine":
            raise OwnershipError("Owned Search index vector metric is incompatible.")
        configurations = {c.name: c for c in actual.semantic_search.configurations or []}
        semantic = configurations.get(self.settings.azure.semantic_configuration)
        if (not semantic or not semantic.prioritized_fields
                or not semantic.prioritized_fields.title_field
                or semantic.prioritized_fields.title_field.field_name != "heading"
                or [f.field_name for f in semantic.prioritized_fields.content_fields or []] != ["content"]):
            raise OwnershipError("Owned Search index semantic configuration is incompatible.")
        return actual

    def _verify_container(self, properties):
        if properties.metadata.get("aifactory_owner") != self.owner:
            raise OwnershipError("Blob container name collision: ownership metadata is missing.")
        if properties.metadata.get("repository_schema") != str(_SCHEMA):
            raise OwnershipError("Owned Blob container schema is incompatible.")
        if getattr(properties, "public_access", None):
            raise OwnershipError("Owned repository state container must not have public access.")

    def ensure_resources(self) -> dict:
        """Create only this index/container; never modify service tiers or collisions."""
        azure = self.settings.azure
        # Inspect both resources before creating either, so a known collision is read-only.
        try:
            index = self._verify_index(self.index_client.get_index(azure.search_index))
        except ResourceNotFoundError:
            index = None
        try:
            self._verify_container(self.container.get_container_properties())
            container_exists = True
        except ResourceNotFoundError:
            container_exists = False
        index_created = container_created = False
        if index is None:
            try:
                self.index_client.create_index(self._index_definition())
                index_created = True
            except ResourceExistsError:
                pass
            index = self._verify_index(self.index_client.get_index(azure.search_index))
        if not container_exists:
            try:
                self.container.create_container(metadata={
                    "aifactory_owner": self.owner, "repository_schema": str(_SCHEMA),
                })
                container_created = True
            except ResourceExistsError:
                pass
            self._verify_container(self.container.get_container_properties())
        return {"index": azure.search_index, "container": azure.storage_container,
                "index_created": index_created, "container_created": container_created,
                "index_etag": getattr(index, "e_tag", None), "owner": self.owner}

    def _empty_manifest(self) -> dict:
        return {"schema": _SCHEMA, "owner": self.owner, "entries": {}, "refreshed_at": None}

    def _read_state(self, name: str) -> dict | None:
        blob = self.container.get_blob_client(name)
        try:
            properties = blob.get_blob_properties()
            if properties.metadata.get("aifactory_owner") != self.owner:
                raise OwnershipError(f"Repository state blob {name} has an ownership collision.")
            payload = json.loads(blob.download_blob().readall())
        except ResourceNotFoundError:
            return None
        if not isinstance(payload, dict) or payload.get("owner") != self.owner or payload.get("schema") != _SCHEMA:
            raise OwnershipError(f"Repository state blob {name} has an incompatible owner/schema.")
        return payload

    def _write_state(self, name: str, payload: dict, *, lease=None, overwrite=True):
        self.container.get_blob_client(name).upload_blob(
            _canonical({**payload, "owner": self.owner, "schema": _SCHEMA}).encode("utf-8"),
            overwrite=overwrite, lease=lease,
            metadata={"aifactory_owner": self.owner},
            content_settings=ContentSettings(content_type="application/json"),
        )

    def _manifest_blob(self):
        if self._read_state(_MANIFEST) is None:
            try:
                self._write_state(_MANIFEST, self._empty_manifest(), overwrite=False)
            except ResourceExistsError:
                pass
            self._read_state(_MANIFEST)
        return self.container.get_blob_client(_MANIFEST)

    def _embeddings(self, texts: list[str]) -> list[list[float]]:
        if any(not text.strip() or len(text.encode("utf-8")) > _embedding_limit(self.settings) for text in texts):
            raise ValueError("Embedding input exceeds the configured safe token cap or is empty.")
        response = self.embedding_client.embeddings.create(
            model=self.settings.azure.embedding_deployment, input=texts,
            dimensions=self.settings.azure.embedding_dimensions, encoding_format="float",
        )
        rows = sorted(response.data, key=lambda item: item.index)
        if [row.index for row in rows] != list(range(len(texts))):
            raise IndexingError("Embedding response did not acknowledge every input.")
        vectors = [row.embedding for row in rows]
        if any(len(vector) != self.settings.azure.embedding_dimensions
               or not all(isinstance(value, (float, int)) and math.isfinite(value) for value in vector)
               for vector in vectors):
            raise IndexingError("Embedding response contains invalid dimensions or values.")
        return vectors

    @staticmethod
    def _check_actions(results, ids: list[str], action: str):
        results = list(results)
        if (len(results) != len(ids) or {r.key for r in results} != set(ids)
                or any(not r.succeeded for r in results)):
            # Do not echo backend error messages, which may contain source content.
            raise IndexingError(f"Search {action} did not successfully acknowledge every document.")

    def _reuse_snapshot_provenance(self, report: dict, manifest: dict) -> int:
        if report["revision_verified"]:
            return 0
        reused = 0
        for doc in report["documents"]:
            entry = manifest["entries"].get(doc["id"], {})
            revision = entry.get("source_revision") or manifest.get("summary", {}).get("repository_revision")
            if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40,64}", revision):
                continue
            url = _citation(
                self.settings.knowledge.source_base_url, doc["source_path"], revision,
                True, False, self.settings.knowledge.repository_root / doc["source_path"],
            )
            if not url.startswith("https://"):
                continue
            candidate = {**doc, "source_revision": revision, "working_tree": False, "source_url": url}
            recorded = (
                entry.get("source_hash") == doc["source_hash"]
                and entry.get("working_tree") is False and entry.get("source_url") == url
            )
            # The complete fingerprint also proves byte-identical provenance for
            # manifests written before per-source provenance fields were stored.
            if recorded or entry.get("fingerprint") == _digest(_canonical(candidate)):
                doc.update(source_revision=revision, working_tree=False, source_url=url)
                reused += 1
        return reused

    def refresh(self) -> dict:
        resources = self.ensure_resources()
        with _RenewingLease(self._manifest_blob()) as guard:
            manifest = self._read_state(_MANIFEST)
            pending = self._read_state(_PENDING)
            self._read_state(_STATUS)  # Refuse state-name collisions before any overwrite.
            if manifest is None or not isinstance(manifest.get("entries"), dict):
                raise OwnershipError("Repository manifest is missing or invalid.")
            previous = manifest["entries"]
            if any(not isinstance(entry, dict) or not isinstance(entry.get("fingerprint"), str)
                   or not _ID.fullmatch(entry["fingerprint"])
                   or not isinstance(entry.get("source_path"), str) for entry in previous.values()):
                raise OwnershipError("Repository manifest contains invalid document entries.")
            if pending and (not isinstance(pending.get("managed_ids"), list)
                            or any(not isinstance(key, str) for key in pending["managed_ids"])):
                raise OwnershipError("Repository pending journal contains invalid identifiers.")
            previous_ids = set(previous)
            pending_ids = set(pending.get("managed_ids", [])) if pending else set()
            if any(not _ID.fullmatch(key) for key in previous_ids | pending_ids):
                raise OwnershipError("Repository manifest contains invalid document identifiers.")
            try:
                report = scan_sources(self.settings)
                guard.check()
                report["manifest_provenance_reused_count"] = self._reuse_snapshot_provenance(report, manifest)
                summary = {key: value for key, value in report.items() if key != "documents"}
                summary["attempted_at"] = _now()
                if report["status"] == "blocked":
                    summary["refreshed_at"] = manifest.get("refreshed_at")
                    summary["indexed_document_count"] = len(previous)
                    self._write_state(_STATUS, summary)
                    return summary
                desired = {doc["id"]: doc for doc in report["documents"]}
                fingerprints = {key: _digest(_canonical(doc)) for key, doc in desired.items()}
                reindex = resources["index_created"] or resources["index_etag"] != manifest.get("index_etag")
                changed = [
                    doc for key, doc in desired.items()
                    if reindex or previous.get(key, {}).get("fingerprint") != fingerprints[key]
                ]
                deleted = sorted((previous_ids | pending_ids) - set(desired))
                # Journal all possible partial writes BEFORE modifying the index. A retry
                # can clean an abandoned attempt even when sources changed in between.
                self._write_state(_PENDING, {
                    "managed_ids": sorted(previous_ids | pending_ids | set(desired)),
                    "attempted_at": summary["attempted_at"],
                })
                for offset in range(0, len(changed), _BATCH):
                    guard.check()
                    batch = changed[offset:offset + _BATCH]
                    vectors = self._embeddings([doc["heading"] + "\n\n" + doc["content"] for doc in batch])
                    guard.check()
                    uploads = [
                        {**doc, "contentVector": vector, "ingested_at": summary["attempted_at"],
                         self.owner_field: self.owner}
                        for doc, vector in zip(batch, vectors)
                    ]
                    self._check_actions(self.search_client.upload_documents(documents=uploads),
                                        [doc["id"] for doc in batch], "upload")
                for offset in range(0, len(deleted), _BATCH):
                    guard.check()
                    keys = deleted[offset:offset + _BATCH]
                    self._check_actions(self.search_client.delete_documents(
                        documents=[{"id": key} for key in keys],
                    ), keys, "delete")
                guard.check()
                completed = _now()
                summary.update({
                    "status": "ready" if desired else "empty", "refreshed_at": completed,
                    "indexed_document_count": len(desired), "uploaded_count": len(changed),
                    "deleted_count": len(deleted),
                })
                committed = {
                    "entries": {key: {
                        "fingerprint": fingerprints[key], "source_path": doc["source_path"],
                        "source_hash": doc["source_hash"], "source_revision": doc["source_revision"],
                        "source_url": doc["source_url"], "working_tree": doc["working_tree"],
                    }
                                for key, doc in desired.items()},
                    "refreshed_at": completed, "index_etag": resources["index_etag"],
                    "summary": summary,
                }
                # The manifest is the authoritative commit; status is observational.
                self._write_state(_MANIFEST, committed, lease=guard.lease)
                guard.check()
                self._write_state(_PENDING, {"managed_ids": []})
                self._write_state(_STATUS, summary)
                return summary
            except (AzureError, OpenAIError, OSError, ValueError, RuntimeError) as exc:
                guard.check()
                failed = {
                    "status": "failed", "attempted_at": _now(),
                    "error_type": type(exc).__name__, "refreshed_at": manifest.get("refreshed_at"),
                    "indexed_document_count": len(previous),
                }
                try:
                    self._write_state(_STATUS, failed)
                except AzureError:
                    _LOG.warning("Could not persist failed knowledge refresh status.")
                raise

    def status(self) -> dict:
        try:
            self._verify_container(self.container.get_container_properties())
            index = self._verify_index(self.index_client.get_index(self.settings.azure.search_index))
        except ResourceNotFoundError:
            return {"status": "not_initialized", "index": self.settings.azure.search_index,
                    "indexed_document_count": 0, "stale": True}
        manifest = self._read_state(_MANIFEST)
        if manifest is None:
            return {"status": "not_initialized", "index": self.settings.azure.search_index,
                    "indexed_document_count": 0, "stale": True}
        latest = self._read_state(_STATUS)
        summary = manifest.get("summary", {})
        # Recover status if a crash occurred after committing but before updating it.
        if latest and (latest.get("attempted_at") or "") > (summary.get("attempted_at") or ""):
            summary = latest
        result = {**summary, "index": self.settings.azure.search_index,
                  "refreshed_at": manifest.get("refreshed_at"),
                  "indexed_document_count": len(manifest["entries"])}
        result["search_document_count"] = self.search_client.get_document_count()
        refreshed = manifest.get("refreshed_at")
        result["stale"] = not refreshed or (
            datetime.now(timezone.utc) - datetime.fromisoformat(refreshed)
        ).total_seconds() > self.settings.knowledge.stale_after_hours * 3600
        result.setdefault("status", "not_initialized")
        pending = self._read_state(_PENDING)
        result["reconciliation_pending"] = bool(pending and pending.get("managed_ids"))
        if result["reconciliation_pending"] and result["status"] == "ready":
            result["status"] = "refresh_incomplete"
        if getattr(index, "e_tag", None) != manifest.get("index_etag"):
            result["status"] = "reindex_required"
            result["stale"] = True
        elif result["search_document_count"] != result["indexed_document_count"]:
            result["stale"] = True
            if result["status"] == "ready":
                result["status"] = "index_out_of_sync"
        return result

    def search(self, query: str, scope_key: str) -> list[dict]:
        if scope_key not in self.settings.scopes:
            raise ValueError("Unknown configured knowledge scope.")
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("Provide a nonempty knowledge query of at most 4000 characters.")
        self._verify_index(self.index_client.get_index(self.settings.azure.search_index))
        vector = self._embeddings([query.strip()])[0]
        fields = [
            "id", "source_path", "heading", "source_type", "is_current", "is_history",
            "release", "version", "source_url", "source_revision", "working_tree",
            "line_start", "line_end", "content", "content_hash", "source_hash",
            "ingested_at", "allowed_scope_keys",
        ]
        options = {
            "search_text": query.strip(), "search_fields": ["content", "heading"],
            "filter": f"allowed_scope_keys/any(scope: scope eq '{scope_key}')",
            "vector_queries": [VectorizedQuery(vector=vector, k_nearest_neighbors=50, fields="contentVector")],
            "vector_filter_mode": "preFilter", "select": fields,
            "top": self.settings.knowledge.top_k,
        }
        if self.settings.azure.semantic_ranking:
            options.update(query_type="semantic",
                           semantic_configuration_name=self.settings.azure.semantic_configuration,
                           semantic_error_mode="fail")
        results = []
        for row in self.search_client.search(**options):
            if scope_key not in row.get("allowed_scope_keys", []):
                raise RuntimeError("Search returned a document outside the requested knowledge scope.")
            if self.settings.azure.semantic_ranking and row.get("@search.reranker_score") is None:
                raise RuntimeError("Semantic ranking was requested but not returned; no fallback is allowed.")
            result = {field: row.get(field) for field in fields if field != "allowed_scope_keys"}
            result["score"] = row.get("@search.reranker_score") if self.settings.azure.semantic_ranking else row.get("@search.score")
            result["search_score"] = row.get("@search.score")
            result["current_history"] = "current" if row.get("is_current") else "history"
            results.append(result)
        return results
