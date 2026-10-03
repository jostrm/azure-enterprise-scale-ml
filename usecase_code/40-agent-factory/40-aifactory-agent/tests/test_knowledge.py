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
        self.index = None
        self.created = 0

    def get_index(self, name):
        if self.index is None:
            raise ResourceNotFoundError()
        return self.index

    def create_index(self, index):
        assert self.index is None
        self.index = index
        self.index.e_tag = "index-1"
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
        self.search_options = options
        return self.rows

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
    return Knowledge(settings, cred=object(), index_client=FakeIndex(),
                     container_client=FakeContainer(), search_client=FakeSearch(),
                     embedding_client=FakeEmbeddings(settings.azure.embedding_dimensions))


def state(knowledge, name="repository-manifest.json"):
    return json.loads(knowledge.container.get_blob_client(name).body)


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


def test_initial_incremental_changed_deleted_and_foreign_id_not_deleted(knowledge, settings):
    write(settings, "first.md", "# First\nOne\n")
    second = write(settings, "second.md", "# Second\nTwo\n")
    first = knowledge.refresh()
    assert first["status"] == "ready"
    assert first["uploaded_count"] == 2 and first["deleted_count"] == 0
    old_ids = set(knowledge.search_client.docs)
    unchanged = knowledge.refresh()
    assert unchanged["uploaded_count"] == unchanged["deleted_count"] == 0
    foreign = "f" * 64
    knowledge.search_client.docs[foreign] = {"id": foreign}
    write(settings, "first.md", "# First\nChanged\n")
    second.unlink()
    updated = knowledge.refresh()
    assert updated["uploaded_count"] == 1 and updated["deleted_count"] == 2
    assert old_ids.isdisjoint(set(knowledge.search_client.docs))
    assert foreign in knowledge.search_client.docs
    assert foreign not in knowledge.search_client.deletes
    assert knowledge.container.blobs["repository-manifest.json"].lease.released
    assert state(knowledge)["summary"]["status"] == "ready"


@pytest.mark.parametrize("failure", ["embedding", "upload", "delete", "transport"])
def test_failure_does_not_advance_manifest_and_retry_reconciles(knowledge, settings, failure):
    write(settings, "guide.md", "# Initial\nOriginal\n")
    knowledge.refresh()
    committed = knowledge.container.blobs["repository-manifest.json"].body
    write(settings, "guide.md", "# Updated\nNew text\n")
    if failure == "embedding":
        knowledge.embedding_client.fail = True
    elif failure == "upload":
        knowledge.search_client.fail_upload = True
    elif failure == "delete":
        knowledge.search_client.fail_delete = True
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


def test_abandoned_partial_upload_is_cleaned_when_retry_source_changes(knowledge, settings):
    write(settings, "guide.md", "# Initial\nOriginal\n")
    knowledge.refresh()
    write(settings, "guide.md", "# Intermediate\n" + "paragraph\n" * 220)
    knowledge.search_client.fail_upload = True
    with pytest.raises(IndexingError):
        knowledge.refresh()
    intermediate = set(knowledge.search_client.docs) - set(state(knowledge)["entries"])
    assert intermediate
    write(settings, "guide.md", "# Final\nFinal text\n")
    knowledge.search_client.fail_upload = False
    knowledge.refresh()
    assert intermediate.isdisjoint(set(knowledge.search_client.docs))
    assert set(knowledge.search_client.docs) == set(state(knowledge)["entries"])


def test_blocked_refresh_persists_safe_status_without_manifest_change(knowledge, settings):
    write(settings, "guide.md", "# Initial\nOriginal\n")
    knowledge.refresh()
    committed = knowledge.container.blobs["repository-manifest.json"].body
    write(settings, "bad.py", "password = 'ActualPassword987654'")
    assert knowledge.refresh()["status"] == "blocked"
    assert knowledge.container.blobs["repository-manifest.json"].body == committed
    assert knowledge.status()["status"] == "blocked"
    assert "ActualPassword" not in knowledge.container.blobs["repository-status.json"].body.decode()


def test_status_is_cloud_persisted_across_instances_and_stale(knowledge, settings):
    assert knowledge.status()["status"] == "not_initialized"
    write(settings, "guide.md", "# Current\nFresh.\n")
    knowledge.refresh()
    replacement = Knowledge(settings, cred=object(), index_client=knowledge.index_client,
                            container_client=knowledge.container, search_client=knowledge.search_client,
                            embedding_client=knowledge.embedding_client)
    assert replacement.status()["status"] == "ready"
    assert not replacement.status()["stale"]
    manifest = state(knowledge)
    manifest["refreshed_at"] = "2001-01-01T00:00:00+00:00"
    knowledge.container.blobs["repository-manifest.json"].body = json.dumps(manifest).encode()
    assert replacement.status()["stale"]


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
    assert options["filter"] == "allowed_scope_keys/any(scope: scope eq 'project001-dev')"
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
