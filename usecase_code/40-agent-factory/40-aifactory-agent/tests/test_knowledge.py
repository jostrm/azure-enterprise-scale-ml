import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError

from aifactory_agent.config import Settings
from aifactory_agent.knowledge import IndexingError, Knowledge, OwnershipError, _RenewingLease, scan_sources


@pytest.fixture
def settings(tmp_path):
    config = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    config["azure"]["credential"] = "managed_identity"
    config["knowledge"].update(repository_root=str(tmp_path), includes=["**/*.md", "**/*.py"],
                               excludes=[], chunk_chars=1000)
    config["scopes"]["project002-dev"] = {**config["scopes"]["project001-dev"], "project": "002"}
    return Settings.model_validate(config)


def write(settings, path, text):
    target = settings.knowledge.repository_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


class FakeLease:
    def __init__(self):
        self.renewed = 0
        self.released = False

    def renew(self):
        self.renewed += 1

    def release(self):
        self.released = True


class FakeBlob:
    def __init__(self):
        self.body = None
        self.metadata = {}
        self.lease = None

    def get_blob_properties(self):
        if self.body is None:
            raise ResourceNotFoundError()
        return SimpleNamespace(metadata=self.metadata)

    def download_blob(self):
        self.get_blob_properties()
        return SimpleNamespace(readall=lambda: self.body)

    def upload_blob(self, data, **kwargs):
        if self.body is not None and not kwargs["overwrite"]:
            raise ResourceExistsError()
        if self.lease and not self.lease.released:
            assert kwargs["lease"] is self.lease
        self.body = data
        self.metadata = kwargs["metadata"]

    def acquire_lease(self, lease_duration):
        assert lease_duration == 60
        self.lease = FakeLease()
        return self.lease


class FakeContainer:
    def __init__(self):
        self.metadata = None
        self.blobs = {}
        self.created = 0
        self.public_access = None

    def get_container_properties(self):
        if self.metadata is None:
            raise ResourceNotFoundError()
        return SimpleNamespace(metadata=self.metadata, public_access=self.public_access)

    def create_container(self, metadata):
        if self.metadata is not None:
            raise ResourceExistsError()
        self.created += 1
        self.metadata = metadata

    def get_blob_client(self, name):
        return self.blobs.setdefault(name, FakeBlob())


class FakeIndex:
    def __init__(self):
        self.indexes = {}
        self.name = None
        self.created = 0
        self.fail_create = False

    @property
    def index(self):
        return self.indexes.get(self.name)

    @index.setter
    def index(self, value):
        self.indexes[self.name] = value

    def get_index(self, name):
        if name not in self.indexes:
            raise ResourceNotFoundError()
        self.name = name
        return self.indexes[name]

    def create_index(self, index):
        if self.fail_create:
            raise HttpResponseError("quota exceeded")
        assert index.name not in self.indexes
        self.name = index.name
        self.indexes[index.name] = index
        index.e_tag = "index-" + index.name
        self.created += 1
        return index


class FakeSearch:
    def __init__(self):
        self.docs = {}
        self.uploads = []
        self.deletes = []
        self.fail_upload = False
        self.fail_delete = False
        self.raise_upload = False
        self.rows = []
        self.search_options = None
        self.clients = {}

    def for_index(self, name):
        if name not in self.clients:
            child = FakeSearch()
            child.fail_upload = self.fail_upload
            child.raise_upload = self.raise_upload
            child.upload_documents = (self.upload_documents if isinstance(self.upload_documents, Mock)
                                      else child.upload_documents)
            self.clients[name] = child
        return self.clients[name]

    def upload_documents(self, documents):
        self.uploads.append(copy.deepcopy(documents))
        if self.raise_upload:
            raise HttpResponseError("simulated")
        actions = []
        for number, doc in enumerate(documents):
            succeeded = not self.fail_upload or number > 0
            if succeeded:
                self.docs[doc["id"]] = copy.deepcopy(doc)
            actions.append(SimpleNamespace(key=doc["id"], succeeded=succeeded))
        return actions

    def delete_documents(self, documents):
        self.deletes.extend(doc["id"] for doc in documents)
        actions = []
        for number, doc in enumerate(documents):
            succeeded = not self.fail_delete or number > 0
            if succeeded:
                self.docs.pop(doc["id"], None)
            actions.append(SimpleNamespace(key=doc["id"], succeeded=succeeded))
        return actions

    def search(self, **options):
        if options.get("search_text") != "*":
            self.search_options = options
        return list(self.docs.values()) if options.get("search_text") == "*" else self.rows

    def get_document_count(self):
        return len(self.docs)


class FakeEmbeddings:
    def __init__(self, dimensions):
        self.calls = []
        self.dimensions = dimensions
        self.fail = False
        self.embeddings = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("Embedding unavailable")
        return SimpleNamespace(data=[
            SimpleNamespace(index=i, embedding=[0.25] * self.dimensions)
            for i in range(len(kwargs["input"]))
        ])


@pytest.fixture
def knowledge(settings):
    search = FakeSearch()
    search.clients[settings.azure.search_index] = search
    def client(name):
        selected = search.for_index(name)
        selected.fail_upload = instance.search_client.fail_upload
        selected.raise_upload = instance.search_client.raise_upload
        if isinstance(instance.search_client.upload_documents, Mock):
            selected.upload_documents = instance.search_client.upload_documents
        return selected
    instance = Knowledge(settings, cred=object(), index_client=FakeIndex(),
                         container_client=FakeContainer(), search_client=search,
                         search_client_factory=client,
                         embedding_client=FakeEmbeddings(settings.azure.embedding_dimensions))
    return instance


def state(knowledge, name="repository-manifest.json"):
    return json.loads(knowledge.container.get_blob_client(name).body)


@pytest.mark.parametrize("failure", ["blocked", "embedding", "upload", "transport", "quota", "promotion", "empty"])
def test_safe_last_successful_snapshot_survives_failed_refresh(knowledge, settings, failure):
    original = write(settings, "guide.md", "# Original\nCommitted safe knowledge.\n")
    knowledge.refresh()
    snapshot = knowledge.snapshot()
    manifest = knowledge.container.blobs["repository-manifest.json"].body
    original_docs = copy.deepcopy(snapshot.client.docs)
    write(settings, "guide.md", "# Replacement\n" + "new paragraph\n" * 220)
    if failure == "blocked":
        write(settings, "bad.py", "password = 'ActualPassword987654'")
    elif failure == "empty":
        original.unlink()
    elif failure == "embedding":
        knowledge.embedding_client.fail = True
    elif failure in {"upload", "transport"}:
        knowledge.search_client.fail_upload = failure == "upload"
        knowledge.search_client.raise_upload = failure == "transport"
    elif failure == "quota":
        knowledge.index_client.fail_create = True
    else:
        blob = knowledge.container.blobs["repository-manifest.json"]
        blob.upload_blob = Mock(side_effect=HttpResponseError("promotion failed"))
    if failure in {"blocked", "empty"}:
        assert knowledge.refresh()["status"] == failure
    else:
        with pytest.raises((RuntimeError, HttpResponseError)):
            knowledge.refresh()
    assert knowledge.container.blobs["repository-manifest.json"].body == manifest
    current = knowledge.snapshot()
    assert current.status()["availability"] == "last_successful"
    assert current.status()["snapshot_id"] == snapshot.status()["snapshot_id"]
    assert current.status()["warning"]
    assert current.client.docs == original_docs
    knowledge.embedding_client.fail = False  # A refresh failure does not remove query service requirements.
    current.client.rows = [{**next(iter(original_docs.values())), "@search.reranker_score": 3.8}]
    assert "Committed safe" in current.search("question", "project001-dev")[0]["content"]


def test_snapshot_pins_generation_across_promotion_and_in_progress_read(knowledge, settings):
    write(settings, "guide.md", "# Original\nOld committed text.\n")
    knowledge.refresh()
    pinned = knowledge.snapshot()
    original_create = knowledge.embedding_client.create

    def during_refresh(**kwargs):
        assert knowledge.status()["availability"] == "last_successful"
        assert knowledge.snapshot().status()["snapshot_id"] == pinned.status()["snapshot_id"]
        return original_create(**kwargs)

    knowledge.embedding_client.create = during_refresh
    write(settings, "guide.md", "# New\nNew committed text.\n")
    knowledge.refresh()
    assert knowledge.snapshot().status()["snapshot_id"] != pinned.status()["snapshot_id"]
    knowledge.embedding_client.create = original_create
    pinned.client.rows = [{**next(iter(pinned.client.docs.values())), "@search.reranker_score": 3.8}]
    assert "Old committed" in pinned.search("question", "project001-dev")[0]["content"]


@pytest.mark.parametrize("delay", ["count", "rows", "timeout", "corruption"])
def test_refresh_waits_for_stage_visibility_without_retrying_corruption(knowledge, settings, monkeypatch, delay):
    from aifactory_agent import knowledge as module

    write(settings, "guide.md", "# Original\nOld committed text.\n")
    knowledge.refresh()
    manifest = knowledge.container.blobs["repository-manifest.json"].body
    created = knowledge.index_client.created
    original_factory = knowledge._search_client_factory
    clock = [module.time.monotonic()]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
        assert knowledge.container.blobs["repository-manifest.json"].body == manifest

    monkeypatch.setattr(module.time, "sleep", sleep)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "_INDEX_READY_TIMEOUT", 2, raising=False)

    def factory(name):
        client = original_factory(name)
        count, search = client.get_document_count, client.search
        observed = [False]

        def delayed_count():
            if delay == "timeout":
                return 0
            if delay == "count" and not observed[0]:
                observed[0] = True
                return 0
            return count()

        def delayed_search(**options):
            if options.get("search_text") == "*" and not observed[0]:
                observed[0] = True
                if delay == "rows":
                    return []
                if delay == "corruption":
                    next(iter(client.docs.values()))["content"] = "Uncommitted corruption."
            return search(**options)

        client.get_document_count = delayed_count
        client.search = delayed_search
        return client

    knowledge._search_client_factory = factory
    write(settings, "guide.md", "# Replacement\nNew committed text.\n")
    if delay in {"timeout", "corruption"}:
        with pytest.raises(IndexingError, match="visible|snapshot"):
            knowledge.refresh()
        assert knowledge.container.blobs["repository-manifest.json"].body == manifest
        assert knowledge.status()["availability"] == "last_successful"
    else:
        assert knowledge.refresh()["status"] == "ready"
        assert knowledge.status()["availability"] == "current"
    assert knowledge.index_client.created == created + 1
    assert bool(sleeps) is (delay != "corruption")


@pytest.mark.parametrize("corruption", ["count", "content", "acl", "owner", "pointer", "pending",
                                      "row_owner", "row_generation"])
def test_unverified_snapshot_never_enables_fallback(knowledge, settings, corruption):
    write(settings, "guide.md", "# Original\nSafe text.\n")
    knowledge.refresh()
    manifest = state(knowledge)
    if corruption == "count":
        knowledge.search_client.docs.clear()
    elif corruption in {"content", "acl"}:
        doc = next(iter(knowledge.search_client.docs.values()))
        doc["content" if corruption == "content" else "allowed_scope_keys"] = (
            "Other content" if corruption == "content" else ["project002-dev"])
    elif corruption == "owner":
        knowledge.index_client.index.fields = []
    elif corruption == "pointer":
        manifest["active_index"] = "another-tenant-index"
        knowledge.container.blobs["repository-manifest.json"].body = json.dumps(manifest).encode()
    elif corruption in {"row_owner", "row_generation"}:
        next(iter(knowledge.search_client.docs.values()))[
            knowledge.owner_field if corruption == "row_owner" else "snapshot_id"] = "another-tenant"
    else:
        knowledge.container.blobs["repository-manifest.json"].metadata = {}
    with pytest.raises((IndexingError, OwnershipError)):
        knowledge.snapshot()


def legacy_snapshot(knowledge):
    manifest = state(knowledge)
    base = knowledge.settings.azure.search_index
    client = knowledge._client(base)
    client.docs = copy.deepcopy(knowledge.search_client.docs)
    manifest.pop("active_index")
    manifest.pop("snapshot_id")
    for key in ("active_index", "snapshot_id"):
        manifest["summary"].pop(key)
    manifest["index_etag"] = knowledge.index_client.get_index(base).e_tag
    knowledge.container.blobs["repository-manifest.json"].body = json.dumps(manifest).encode()
    knowledge.search_client = client
    return client


@pytest.mark.parametrize("pending", [False, True])
def test_legacy_complete_manifest_migrates_without_mutating_963_documents(knowledge, settings, pending):
    from aifactory_agent.knowledge import _canonical, _digest

    write(settings, "guide.md", "# Legacy\nLegacy knowledge.\n")
    knowledge.refresh()
    client = legacy_snapshot(knowledge)
    manifest = state(knowledge)
    template = next(iter(client.docs.values()))
    template_entry = next(iter(manifest["entries"].values()))
    client.docs.clear()
    manifest["entries"].clear()
    for number in range(963):
        doc = {**template, "id": _digest(str(number))}
        client.docs[doc["id"]] = doc
        fingerprint = _digest(_canonical({field: doc[field] for field in (
            "id", "source_path", "heading", "source_type", "is_current", "is_history",
            "release", "version", "source_url", "source_revision", "working_tree",
            "line_start", "line_end", "content", "content_hash", "source_hash", "allowed_scope_keys",
        )}))
        manifest["entries"][doc["id"]] = {**template_entry, "fingerprint": fingerprint}
    manifest["summary"]["indexed_document_count"] = 963
    knowledge.container.blobs["repository-manifest.json"].body = json.dumps(manifest).encode()
    knowledge._write_state("repository-pending.json", {"managed_ids": list(client.docs) if pending else []})
    write(settings, "bad.py", "password = 'ActualPassword987654'")
    assert knowledge.refresh()["status"] == "blocked"
    if pending:
        assert knowledge.status()["availability"] == "unavailable"
        with pytest.raises(IndexingError):
            knowledge.snapshot()
    else:
        pinned = knowledge.snapshot()
        assert pinned.status()["availability"] == "last_successful"
        assert pinned.status()["indexed_document_count"] == 963
        assert pinned.status()["search_document_count"] == 963
    old = copy.deepcopy(client.docs)
    (settings.knowledge.repository_root / "bad.py").unlink()
    client.delete_documents = Mock(side_effect=HttpResponseError("partial delete failure"))
    knowledge.refresh()
    assert state(knowledge)["active_index"] != settings.azure.search_index
    assert client.docs == old
    client.delete_documents.assert_not_called()
    assert knowledge.status()["availability"] == "current"


@pytest.mark.parametrize("failure", ["blocked", "empty", "embedding"])
def test_failed_initialization_has_no_fallback(knowledge, settings, failure):
    if failure == "blocked":
        write(settings, "bad.py", "password = 'ActualPassword987654'")
    elif failure == "embedding":
        write(settings, "guide.md", "# Safe\nText.\n")
        knowledge.embedding_client.fail = True
    if failure == "embedding":
        with pytest.raises(RuntimeError):
            knowledge.refresh()
    else:
        assert knowledge.refresh()["status"] == failure
    assert knowledge.status()["availability"] == "unavailable"
    with pytest.raises(IndexingError):
        knowledge.snapshot()


def test_failed_shadow_retry_cannot_clear_unreconciled_legacy_writes(knowledge, settings):
    write(settings, "guide.md", "# Legacy\nSafe text.\n")
    knowledge.refresh()
    client = legacy_snapshot(knowledge)
    knowledge._write_state("repository-pending.json", {"managed_ids": list(client.docs)})
    manifest = knowledge.container.blobs["repository-manifest.json"].body
    assert knowledge.status()["reconciliation_pending"] is True
    write(settings, "guide.md", "# Replacement\nNew text.\n")
    knowledge.embedding_client.fail = True
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Embedding unavailable"):
            knowledge.refresh()
        assert knowledge.container.blobs["repository-manifest.json"].body == manifest
        assert knowledge.status()["reconciliation_pending"] is True
        assert knowledge.status()["availability"] == "unavailable"
        with pytest.raises(IndexingError):
            knowledge.snapshot()
    knowledge.embedding_client.fail = False
    assert knowledge.refresh()["status"] == "ready"
    assert knowledge.status()["availability"] == "current"
    assert knowledge.status()["reconciliation_pending"] is False


def test_reader_cannot_pair_legacy_manifest_with_new_generation_cleared_journal(knowledge, settings, monkeypatch):
    write(settings, "guide.md", "# Legacy\nSafe text.\n")
    knowledge.refresh()
    promoted = state(knowledge)
    client = legacy_snapshot(knowledge)
    knowledge._write_state("repository-pending.json", {"managed_ids": list(client.docs)})
    read_state = knowledge._read_state
    switched = [False]

    def racing_read(name):
        result = read_state(name)
        if name == "repository-manifest.json" and not switched[0]:
            switched[0] = True
            knowledge._write_state("repository-manifest.json", promoted)
            knowledge._write_state("repository-pending.json", {"managed_ids": []})
        return result

    monkeypatch.setattr(knowledge, "_read_state", racing_read)
    with pytest.raises(IndexingError):
        knowledge.snapshot()
    assert switched[0]
    assert knowledge.snapshot().status()["availability"] == "current"


@pytest.mark.parametrize("patch", [
    {"managed_ids": ["invalid-id"]},
    {"managed_ids": [], "legacy_reconciliation_pending": "false"},
    {"managed_ids": [], "staging_index": "another-tenant-index"},
])
def test_invalid_pending_state_blocks_snapshot_and_refresh(knowledge, settings, patch):
    write(settings, "guide.md", "# Safe\nText.\n")
    knowledge.refresh()
    knowledge._write_state("repository-pending.json", patch)
    with pytest.raises(OwnershipError):
        knowledge.snapshot()
    with pytest.raises(OwnershipError):
        knowledge.refresh()


def test_scan_includes_direct_recursive_files_and_future_releases(settings):
    write(settings, "documentation/readme.md", "# Current\nUse managed identity.\n")
    write(settings, "RELEASE_999.md", "# Future release\nHistorical release instructions.\n")
    write(settings, "code.py", "print('safe')\n")
    write(settings, "not-text.json", '{"content":"never"}')
    report = scan_sources(settings)
    assert report["status"] == "scanned"
    assert report["source_count"] == 3
    release = next(doc for doc in report["documents"] if doc["source_type"] == "release")
    assert release["version"] == release["release"] == "999"
    assert release["is_history"] and not release["is_current"]
    assert report["coverage_gaps"][0]["reason"] == "missing_or_blank_initial_machine_learning_readme"
    assert release["source_url"].startswith("file:")
    assert release["working_tree"]
    assert all(doc["allowed_scope_keys"] == sorted(settings.scopes) for doc in report["documents"])


def test_scan_preserves_fitting_fence_heading_and_line_context(settings):
    write(settings, "guide.md", "# Deploy\n" + "intro " * 140 + "\n"
          "```powershell\naz deployment group create `\n  --resource-group demo\n```\n"
          "## Verify\nUse status.\n")
    docs = scan_sources(settings)["documents"]
    code = next(doc for doc in docs if "az deployment" in doc["content"])
    assert "```powershell\naz deployment group create `\n  --resource-group demo\n```" in code["content"]
    assert code["line_start"] <= 3 and code["line_end"] >= 6
    assert code["heading"] == "Deploy"
    assert docs[-1]["heading"] == "Deploy > Verify"
    assert all(len(doc["content"]) <= 1000 for doc in docs)


def test_large_fences_are_balanced_and_embedding_input_bounded(settings):
    source = "# Commands\n```python\n" + "print('🚀')\n" * 240 + "```\n"
    write(settings, "guide.md", source)
    docs = scan_sources(settings)["documents"]
    fences = [doc for doc in docs if "print(" in doc["content"]]
    assert len(fences) > 1
    assert all(doc["content"].count("```") == 2 for doc in fences)
    assert sum(doc["content"].count("print('🚀')") for doc in fences) == 240
    assert all(len((doc["heading"] + "\n\n" + doc["content"]).encode()) <= 8000 for doc in docs)


def test_hard_exclusions_cannot_be_overridden(settings):
    for path in (".env.md", "secret.md", "credentials.py", "tests/guide.md",
                 "node_modules/guide.md", "generated/guide.py", "guide_generated.py",
                 ".venv/readme.md", "eval.md"):
        write(settings, path, "password = 'ActualProductionPassword12'\n")
    write(settings, "safe.md", "# Safe\nOnly approved text.\n")
    report = scan_sources(settings)
    assert report["status"] == "scanned"
    assert report["source_paths"] == ["safe.md"]


@pytest.mark.parametrize("literal", [
    "client_secret = 'ProductionValue987654321'",
    "AccountKey=" + "A" * 44,
    "-----BEGIN PRIVATE KEY-----",
    "token = 'ghp_" + "a" * 36 + "'",
])
def test_credential_detection_blocks_all_content(settings, literal):
    write(settings, "safe.md", "# Safe\nFine\n")
    write(settings, "bad.py", literal)
    report = scan_sources(settings)
    assert report["status"] == "blocked"
    assert report["documents"] == []
    assert report["blocked"] == [{"source_path": "bad.py", "line": 1, "reason": "credential_literal"}]
    assert literal not in json.dumps(report)


def test_placeholders_are_not_real_credentials(settings):
    write(settings, "guide.md", 'api_key = "YOUR_API_KEY"\nclient_secret = "<client-secret>"\n')
    assert scan_sources(settings)["status"] == "scanned"


def test_symlink_escape_is_blocked(settings, tmp_path):
    source = write(settings, "safe.md", "# Safe\n")
    link = tmp_path / "linked.md"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    assert scan_sources(settings)["status"] == "blocked"


def test_full_generation_refresh_excludes_removed_and_never_deletes_foreign_ids(knowledge, settings):
    write(settings, "first.md", "# First\nOne\n")
    second = write(settings, "second.md", "# Second\nTwo\n")
    first = knowledge.refresh()
    assert first["status"] == "ready"
    assert first["uploaded_count"] == 2 and first["deleted_count"] == 0
    old_ids = set(knowledge.search_client.docs)
    unchanged = knowledge.refresh()
    assert unchanged["uploaded_count"] == unchanged["deleted_count"] == 0
    old_client = knowledge.search_client
    foreign = "f" * 64
    knowledge.search_client.docs[foreign] = {"id": foreign}
    write(settings, "first.md", "# First\nChanged\n")
    second.unlink()
    updated = knowledge.refresh()
    assert updated["uploaded_count"] == 1 and updated["deleted_count"] == 2
    assert old_ids.isdisjoint(set(knowledge.search_client.docs))
    assert foreign in old_client.docs
    assert not old_client.deletes and not knowledge.search_client.deletes
    assert knowledge.container.blobs["repository-manifest.json"].lease.released
    assert state(knowledge)["summary"]["status"] == "ready"


@pytest.mark.parametrize("failure", ["embedding", "upload", "transport"])
def test_failure_does_not_advance_manifest_and_retry_reconciles(knowledge, settings, failure):
    write(settings, "guide.md", "# Initial\nOriginal\n")
    knowledge.refresh()
    committed = knowledge.container.blobs["repository-manifest.json"].body
    write(settings, "guide.md", "# Updated\nNew text\n")
    if failure == "embedding":
        knowledge.embedding_client.fail = True
    elif failure == "upload":
        knowledge.search_client.fail_upload = True
    else:
        knowledge.search_client.raise_upload = True
    with pytest.raises((RuntimeError, HttpResponseError)):
        knowledge.refresh()
    assert knowledge.container.blobs["repository-manifest.json"].body == committed
    assert knowledge.status()["status"] == "failed"
    assert state(knowledge, "repository-pending.json")["managed_ids"]
    knowledge.embedding_client.fail = False
    knowledge.search_client.fail_upload = False
    knowledge.search_client.fail_delete = False
    knowledge.search_client.raise_upload = False
    assert knowledge.refresh()["status"] == "ready"
    assert set(knowledge.search_client.docs) == set(state(knowledge)["entries"])
    assert not knowledge.status()["reconciliation_pending"]


def test_abandoned_partial_upload_is_isolated_and_not_deleted_when_retry_source_changes(knowledge, settings):
    write(settings, "guide.md", "# Initial\nOriginal\n")
    knowledge.refresh()
    write(settings, "guide.md", "# Intermediate\n" + "paragraph\n" * 220)
    knowledge.search_client.fail_upload = True
    with pytest.raises(IndexingError):
        knowledge.refresh()
    staging = knowledge._client(state(knowledge, "repository-pending.json")["staging_index"])
    intermediate = set(staging.docs)
    assert intermediate
    write(settings, "guide.md", "# Final\nFinal text\n")
    knowledge.search_client.fail_upload = False
    knowledge.refresh()
    assert intermediate.isdisjoint(set(knowledge.search_client.docs))
    assert set(knowledge.search_client.docs) == set(state(knowledge)["entries"])
    assert set(staging.docs) == intermediate and not staging.deletes


def test_blocked_refresh_persists_safe_status_without_manifest_change(knowledge, settings):
    write(settings, "guide.md", "# Initial\nOriginal\n")
    knowledge.refresh()
    committed = knowledge.container.blobs["repository-manifest.json"].body
    write(settings, "bad.py", "password = 'ActualPassword987654'")
    assert knowledge.refresh()["status"] == "blocked"
    assert knowledge.container.blobs["repository-manifest.json"].body == committed
    assert knowledge.status()["status"] == "blocked"
    assert "ActualPassword" not in knowledge.container.blobs["repository-status.json"].body.decode()


def test_default_local_demo_tutorial_does_not_block_knowledge_ingestion():
    from aifactory_agent.knowledge import _credential_line

    tutorial = Path(__file__).resolve().parents[4] / "documentation" / "v2" / "10-19" / "18-cli-and-api-and-usage.md"
    assert _credential_line(tutorial.read_text("utf-8")) is None
    assert _credential_line("password = 'ActualPassword987654'") == 1


def test_status_is_cloud_persisted_across_instances_and_stale(knowledge, settings):
    assert knowledge.status()["status"] == "not_initialized"
    write(settings, "guide.md", "# Current\nFresh.\n")
    knowledge.refresh()
    replacement = Knowledge(settings, cred=object(), index_client=knowledge.index_client,
                            container_client=knowledge.container, search_client=knowledge.search_client,
                            search_client_factory=knowledge._client,
                            embedding_client=knowledge.embedding_client)
    assert replacement.status()["status"] == "ready"
    assert not replacement.status()["stale"]
    manifest = state(knowledge)
    manifest["refreshed_at"] = "2001-01-01T00:00:00+00:00"
    knowledge.container.blobs["repository-manifest.json"].body = json.dumps(manifest).encode()
    assert replacement.status()["stale"]
    assert replacement.snapshot().status()["availability"] == "last_successful"


def test_owned_resource_creation_rerun_and_collision_do_not_overwrite(knowledge):
    result = knowledge.ensure_resources()
    assert result["index_created"] and result["container_created"]
    rerun = knowledge.ensure_resources()
    assert not rerun["index_created"] and not rerun["container_created"]
    assert knowledge.index_client.created == knowledge.container.created == 1
    knowledge.container.metadata = {"aifactory_owner": "somebody-else"}
    with pytest.raises(OwnershipError):
        knowledge.ensure_resources()
    assert knowledge.index_client.created == knowledge.container.created == 1


def test_index_collision_and_schema_mismatch_are_refused(knowledge):
    knowledge.ensure_resources()
    knowledge.index_client.index.fields = [field for field in knowledge.index_client.index.fields
                                           if field.name != knowledge.owner_field]
    with pytest.raises(OwnershipError, match="ownership"):
        knowledge.ensure_resources()
    knowledge.index_client.index = knowledge._index_definition()
    vector = next(field for field in knowledge.index_client.index.fields if field.name == "contentVector")
    vector.vector_search_dimensions = 256
    with pytest.raises(OwnershipError, match="incompatible"):
        knowledge.ensure_resources()


def test_manifest_blob_collision_refused(knowledge):
    knowledge.ensure_resources()
    blob = knowledge.container.get_blob_client("repository-manifest.json")
    blob.body = b"{}"
    blob.metadata = {}
    with pytest.raises(OwnershipError):
        knowledge.refresh()
    assert not knowledge.search_client.uploads


def test_unknown_scope_rejected_before_network_or_embedding(knowledge):
    with pytest.raises(ValueError, match="Unknown"):
        knowledge.search("deployment", "project001-dev' or true")
    assert not knowledge.embedding_client.calls
    assert knowledge.search_client.search_options is None


def test_hybrid_semantic_query_has_exact_scope_prefilter_and_citations(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.refresh()
    doc = next(iter(knowledge.search_client.docs.values()))
    knowledge.search_client.rows = [{**doc, "@search.score": 0.02, "@search.reranker_score": 3.8}]
    rows = knowledge.search("deployment", "project001-dev")
    options = knowledge.search_client.search_options
    assert options["filter"] == (
        "allowed_scope_keys/any(scope: scope eq 'project001-dev')"
        f" and {knowledge.owner_field} eq '{knowledge.owner}'"
        f" and snapshot_id eq '{state(knowledge)['snapshot_id']}'")
    assert options["vector_filter_mode"] == "preFilter"
    assert options["query_type"] == "semantic" and options["semantic_error_mode"] == "fail"
    assert options["vector_queries"][0].fields == "contentVector"
    assert rows[0]["score"] == 3.8
    assert rows[0]["current_history"] == "current"
    assert "contentVector" not in rows[0] and "allowed_scope_keys" not in rows[0]
    knowledge.search_client.rows[0]["allowed_scope_keys"] = ["project002-dev"]
    with pytest.raises(RuntimeError, match="outside"):
        knowledge.search("deployment", "project001-dev")


def test_semantic_failure_is_not_silently_downgraded(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.refresh()
    doc = next(iter(knowledge.search_client.docs.values()))
    knowledge.search_client.rows = [{**doc, "@search.score": 0.02}]
    with pytest.raises(RuntimeError, match="no fallback"):
        knowledge.search("deployment", "project001-dev")


def test_invalid_embedding_and_missing_action_acknowledgments(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.embedding_client.dimensions = 10
    with pytest.raises(IndexingError, match="dimensions"):
        knowledge.refresh()
    assert state(knowledge)["entries"] == {}
    knowledge.embedding_client.dimensions = settings.azure.embedding_dimensions
    knowledge.search_client.upload_documents = Mock(return_value=[])
    with pytest.raises(IndexingError, match="acknowledge"):
        knowledge.refresh()
    assert state(knowledge)["entries"] == {}


def test_revision_citation_pins_commit_and_marks_uncommitted_source(settings):
    root = settings.knowledge.repository_root
    write(settings, "guide.md", "# Committed\nOld text.\n")
    for args in (("init",), ("add", "guide.md"),
                 ("-c", "user.name=Knowledge Test", "-c", "user.email=test@example.invalid",
                  "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    committed = scan_sources(settings)
    doc = committed["documents"][0]
    assert "/blob/" + committed["repository_revision"] + "/guide.md" in doc["source_url"]
    assert not doc["working_tree"]
    write(settings, "guide.md", "# Uncommitted\nChanged locally.\n")
    dirty = scan_sources(settings)["documents"][0]
    assert dirty["working_tree"]
    assert dirty["source_url"].startswith("file:")
    assert dirty["source_revision"] == committed["repository_revision"]


def test_ignored_uncommitted_file_never_gets_commit_citation(settings):
    root = settings.knowledge.repository_root
    write(settings, ".gitignore", "ignored.md\n")
    write(settings, "tracked.md", "# Tracked\n")
    for args in (("init",), ("add", ".gitignore", "tracked.md"),
                 ("-c", "user.name=Knowledge Test", "-c", "user.email=test@example.invalid",
                  "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    write(settings, "ignored.md", "# Not in the commit\n")
    ignored = next(doc for doc in scan_sources(settings)["documents"] if doc["source_path"] == "ignored.md")
    assert ignored["working_tree"] and ignored["source_url"].startswith("file:")


def test_configured_byte_token_cap_and_embedding_batching(knowledge, settings):
    knowledge.settings = settings.model_copy(update={
        "knowledge": settings.knowledge.model_copy(update={"max_embedding_tokens": 1000, "chunk_chars": 12000}),
    })
    write(settings, "large.py", "print('🚀')\n" * 2600)
    result = knowledge.refresh()
    calls = knowledge.embedding_client.calls
    assert result["uploaded_count"] > 32 and len(calls) > 1
    assert all(len(call["input"]) <= 32 for call in calls)
    assert all(len(text.encode("utf-8")) <= 1000 for call in calls for text in call["input"])


def test_recreated_index_replays_committed_sources(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.refresh()
    count = len(knowledge.search_client.docs)
    knowledge.index_client.index.e_tag = "replacement-index-generation"
    knowledge.search_client.docs.clear()
    assert knowledge.status()["status"] == "reindex_required"
    assert knowledge.refresh()["uploaded_count"] == count
    assert knowledge.status()["status"] == "ready"


def test_lease_checks_loss_and_renews_without_cloud(knowledge, monkeypatch):
    knowledge.ensure_resources()
    blob = knowledge._manifest_blob()
    guard = _RenewingLease(blob)
    guard.error = HttpResponseError("lease lost")
    with pytest.raises(RuntimeError, match="renewal failed"):
        guard.check()
    guard.error = None
    guard.renewed_at -= 55
    with pytest.raises(RuntimeError, match="expired"):
        guard.check()
    polls = iter([False, True])
    monkeypatch.setattr(guard.stop, "wait", lambda _: next(polls))
    guard._renew()
    assert guard.lease.renewed == 1
    guard.check()
    guard.lease.release()


def test_actual_sdk_schema_serialization(knowledge):
    schema = knowledge._index_definition()._to_generated().serialize()
    fields = {field["name"]: field for field in schema["fields"]}
    assert fields["content"]["searchable"] and fields["heading"]["searchable"]
    assert fields["allowed_scope_keys"]["filterable"]
    assert fields["contentVector"]["dimensions"] == knowledge.settings.azure.embedding_dimensions
    assert schema["vectorSearch"]["algorithms"][0]["hnswParameters"]["metric"] == "cosine"
    assert fields[knowledge.owner_field]["retrievable"] is False


def test_status_recovers_if_observational_status_write_was_not_completed(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.refresh()
    knowledge.container.blobs["repository-status.json"].body = None
    assert knowledge.status()["status"] == "ready"


def test_corrupt_pending_and_nontransient_resource_errors_are_not_missing(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.refresh()
    pending = state(knowledge, "repository-pending.json")
    pending["managed_ids"] = ["not-an-owned-id"]
    knowledge.container.blobs["repository-pending.json"].body = json.dumps(pending).encode()
    with pytest.raises(OwnershipError, match="invalid"):
        knowledge.refresh()
    knowledge.index_client.get_index = Mock(side_effect=HttpResponseError("forbidden"))
    with pytest.raises(HttpResponseError):
        knowledge.ensure_resources()


def test_status_exposes_live_index_count_without_deleting_unmanaged_documents(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.refresh()
    knowledge.search_client.docs["unmanaged"] = {"id": "unmanaged"}
    status = knowledge.status()
    assert status["search_document_count"] == status["indexed_document_count"] + 1
    assert status["status"] == "index_out_of_sync" and status["stale"]
    assert "unmanaged" not in knowledge.search_client.deletes


def test_empty_corpus_is_not_reported_as_ready(knowledge):
    result = knowledge.refresh()
    assert result["status"] == "empty" and result["indexed_document_count"] == 0
    assert result["coverage_gaps"]
    assert knowledge.status()["status"] == "empty"


def test_public_state_container_is_refused_without_overwrite(knowledge):
    knowledge.ensure_resources()
    knowledge.container.public_access = "blob"
    with pytest.raises(OwnershipError, match="public"):
        knowledge.ensure_resources()


def test_explicit_semantic_disabled_still_performs_hybrid_scoped_search(knowledge, settings):
    write(settings, "guide.md", "# Current\nText.\n")
    knowledge.refresh()
    knowledge.settings = settings.model_copy(update={
        "azure": settings.azure.model_copy(update={"semantic_ranking": False}),
    })
    doc = next(iter(knowledge.search_client.docs.values()))
    knowledge.search_client.rows = [{**doc, "@search.score": 0.12}]
    assert knowledge.search("deployment", "project001-dev")[0]["score"] == 0.12
    assert "query_type" not in knowledge.search_client.search_options
    assert knowledge.search_client.search_options["vector_queries"]


@pytest.mark.parametrize("legacy_manifest", [False, True])
def test_gitless_snapshot_reuses_only_proven_byte_identical_commit_citations(
        knowledge, settings, monkeypatch, legacy_manifest):
    from aifactory_agent import knowledge as module

    root = settings.knowledge.repository_root
    source = write(settings, "guide.md", "# Committed\nOriginal text.\n")
    for args in (("init",), ("add", "guide.md"),
                 ("-c", "user.name=Knowledge Test", "-c", "user.email=test@example.invalid",
                  "commit", "-m", "fixture")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    knowledge.refresh()
    original = next(iter(knowledge.search_client.docs.values()))
    assert not original["working_tree"] and original["source_url"].startswith("https://")
    if legacy_manifest:
        manifest = state(knowledge)
        manifest["entries"] = {
            key: {name: entry[name] for name in ("fingerprint", "source_path")}
            for key, entry in manifest["entries"].items()
        }
        knowledge.container.blobs["repository-manifest.json"].body = json.dumps(manifest).encode()
    snapshot = root / "cloud-snapshot"
    snapshot.mkdir()
    (snapshot / "guide.md").write_bytes(source.read_bytes())
    knowledge.settings = settings.model_copy(update={
        "knowledge": settings.knowledge.model_copy(update={"repository_root": snapshot}),
    })
    monkeypatch.setattr(module, "_revision", lambda _: (None, set(), {}, False))
    refreshed = knowledge.refresh()
    assert refreshed["manifest_provenance_reused_count"] == 1
    assert refreshed["uploaded_count"] == refreshed["deleted_count"] == 0
    assert knowledge.refresh()["manifest_provenance_reused_count"] == 1
    retained = next(iter(knowledge.search_client.docs.values()))
    assert retained["source_url"] == original["source_url"]
    assert retained["source_revision"] == original["source_revision"]
    (snapshot / "guide.md").write_text("# Locally changed\nNew text.\n", encoding="utf-8", newline="\n")
    changed = knowledge.refresh()
    assert changed["manifest_provenance_reused_count"] == 0
    assert changed["uploaded_count"] == changed["deleted_count"] == 1
    current = next(iter(knowledge.search_client.docs.values()))
    assert current["working_tree"] and current["source_url"].startswith("file:")
    assert current["source_revision"] is None
