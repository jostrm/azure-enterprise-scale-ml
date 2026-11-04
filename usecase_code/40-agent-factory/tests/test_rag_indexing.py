import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from agent_factory.azure import AzureError
from agent_factory.config import FactoryConfig, Target
from agent_factory.data import index_schema, json_bytes, sha256
from agent_factory.rag_sources import RagSource, parse_source
from agent_factory import rag_indexing as rag


SUB = "22222222-2222-2222-2222-222222222222"
TENANT = "11111111-1111-1111-1111-111111111111"
PRINCIPAL = "44444444-4444-4444-4444-444444444444"
TARGET = Target(
    TENANT, SUB, "project-rg", "common-rg", "foundry", "project-001",
    "https://foundry.services.ai.azure.com/api/projects/project-001", "swedencentral",
    "chat", "", "project-search", "aifstorage2001",
    f"/subscriptions/{SUB}/resourceGroups/project-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/project-mi",
    "33333333-3333-3333-3333-333333333333",
)
CONFIG = FactoryConfig(TENANT, SUB, "dev", "001", "project-rg", "common-rg")


def fixture(shared=False):
    path = ("mlops/v1/projects/project001/environments/dev/usecases/helpdesk/rag/corpora/helpdesk/versions/1/documents.jsonl"
            if shared else "helpdesk-v1/knowledge/items.json")
    account, group = ("commonlake", "common-rg") if shared else ("aifstorage2001", "project-rg")
    content = "Use the approved VPN.\nPreserve exact UTF-8: Å."
    row = ({"document_id": "vpn", "text": content, "source_uri": "https://example.org/vpn",
            "source_sha256": sha256(content.encode()), "source_version": "1", "acl": ["project001"], "deleted": False}
           if shared else {"id": "source-id", "topic": "vpn", "content": content, "source_url": "https://example.org/vpn",
                           "source_version": "1", "license": "MIT", "attribution": "Publisher", "dataset_sha256": "d" * 64,
                           "document_url": f"https://{account}.blob.core.windows.net/lake3/{path}"})
    raw = json_bytes(row) + b"\n" if shared else json_bytes([row])
    binding = {
        "location": "common" if shared else "project",
        "storage_account_resource_id": f"/subscriptions/{SUB}/resourceGroups/{group}/providers/Microsoft.Storage/storageAccounts/{account}",
        "container": "lake3", "blob_path": path, "format": "shared-lake-jsonl" if shared else "knowledge-json-array",
        "sha256": sha256(raw), "approved_audience": "project001", "dataset": "helpdesk", "version": "1",
        "description": "Approved immutable knowledge",
    }
    manifest = None
    if shared:
        manifest = json_bytes({
            "schema": "ml-model-factory-publication/v1", "state": "committed", "kind": "rag_snapshot", "format": "jsonl",
            "project": "001", "environment": "dev", "use_case": "helpdesk", "key": path.rsplit("/", 1)[0],
            "aifactory": "factory", "files": {"documents.jsonl": binding["sha256"]},
            "index": {"deleted_document_ids": []}, "document_count": 1,
            "provenance": {"license": "CC0-1.0", "attribution": "Manifest publisher", "dataset_sha256": "e" * 64},
        })
        binding.update(manifest_path=path.rsplit("/", 1)[0] + "/_SUCCESS.json", manifest_sha256=sha256(manifest))
    source = RagSource.from_binding(binding, CONFIG, TARGET, source_key="common-helpdesk" if shared else "project-helpdesk")
    return source, parse_source(source, raw, manifest)


class FakeSession:
    def __init__(self, source):
        self.tenant_id, self.subscription_id = TENANT, SUB
        self.calls, self.resources = [], {}
        self.storage = {"properties": {"publicNetworkAccess": "Disabled", "allowBlobPublicAccess": False, "isHnsEnabled": True}}
        self.service = {"sku": {"name": "basic"}, "properties": {"publicNetworkAccess": "disabled", "semanticSearch": "free"},
                        "identity": {"type": "SystemAssigned", "principalId": PRINCIPAL}}
        self.links = []
        self.destination_checks = []
        self.source = source
        self.count, self.rows = 0, []
        self.execution = {"status": "running", "lastResult": {
            "status": "success", "startTime": "2026-09-16T18:00:00Z", "endTime": "2026-09-16T18:01:00Z",
            "itemsProcessed": 1, "itemsFailed": 0, "errors": [], "warnings": [],
        }}
        self.error = None

    def ready(self):
        name = "SearchBlobSPL"
        resource_id = rag._search_id(TARGET) + "/sharedPrivateLinkResources/" + name
        self.links = [{"id": resource_id, "name": name, "properties": {
            "privateLinkResourceId": TARGET.storage_id, "groupId": "blob", "status": "Approved",
            "provisioningState": "Succeeded",
        }}]

    def persisted(self, expected):
        self.rows = [{"id": "generated-base64-key", **copy.deepcopy(row)} for row in expected]
        if self.source.format == "shared-lake-jsonl":
            for row in self.rows:
                row.update(license=None, attribution=None, dataset_sha256=None,
                           document_url=rag.destination(self.source)["blob_url"])
        else:
            for row in self.rows:
                row["content_sha256"] = None
        self.count = len(self.rows)

    def request(self, method, url, body=None, **kwargs):
        self.calls.append((method, url, copy.deepcopy(body), kwargs))
        if self.error:
            raise AzureError(self.error, method, url, "failure")
        if "/docs/search?" in url:
            return {"@odata.count": self.count, "value": copy.deepcopy(self.rows)}
        if "/status?" in url:
            return copy.deepcopy(self.execution)
        if method == "POST" and "/run?" in url:
            self.execution["lastResult"] = {"status": "inProgress"}
            return {}
        if method == "GET":
            if url not in self.resources:
                raise AzureError(404, method, url, "missing")
            return copy.deepcopy(self.resources[url])
        if method == "PUT":
            self.resources[url] = copy.deepcopy(body)
            return copy.deepcopy(body)
        raise AssertionError((method, url, body))

    def arm(self, method, resource_id, body=None, api_version=None):
        self.calls.append((method, resource_id, copy.deepcopy(body), {"api_version": api_version}))
        if self.error:
            raise AzureError(self.error, method, resource_id, "failure")
        if method == "GET":
            if resource_id == TARGET.storage_id:
                return copy.deepcopy(self.storage)
            if resource_id == rag._search_id(TARGET):
                return copy.deepcopy(self.service)
            if resource_id.endswith("/sharedPrivateLinkResources"):
                return {"value": copy.deepcopy(self.links)}
            for row in self.links:
                if row["id"] == resource_id:
                    return copy.deepcopy(row)
            if resource_id in self.resources:
                return copy.deepcopy(self.resources[resource_id])
            raise AzureError(404, method, resource_id, "missing")
        raise AssertionError((method, resource_id, body))


class RagIndexingTests(unittest.TestCase):
    def test_shared_index_rejects_unmapped_metadata_injection(self):
        self.common()
        self.prepare()
        for field in ("license", "attribution", "dataset_sha256"):
            self.session.rows[0][field] = "unverified"
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "unmapped"):
                self.verify()
            self.session.rows[0][field] = None
    def test_success_with_zero_processed_documents_needs_explicit_retry(self):
        self.prepare()
        rag.start_indexing(self.session, TARGET, self.source)
        self.session.execution["lastResult"]["itemsProcessed"] = 0
        self.session.calls.clear()
        with self.assertRaisesRegex(RuntimeError, "processed no content"):
            rag.start_indexing(self.session, TARGET, self.source)
        self.assert_no_writes()
        self.assertEqual(rag.start_indexing(self.session, TARGET, self.source, retry_failed=True)["status"], "running")
        runs = [call for call in self.session.calls if call[0] == "POST" and "/run?" in call[1]]
        self.assertEqual(len(runs), 1)
        rag.start_indexing(self.session, TARGET, self.source, retry_failed=True)
        self.assertEqual(len([call for call in self.session.calls if call[0] == "POST" and "/run?" in call[1]]), 1)

    def test_retry_requires_boolean_and_positive_terminal_failure_evidence(self):
        self.prepare()
        for value in (1, 0, "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                rag.start_indexing(self.session, TARGET, self.source, retry_failed=value)
        self.destination_check.assert_not_called()
        self.assertFalse(self.session.calls)
        rag.start_indexing(self.session, TARGET, self.source)
        successful = copy.deepcopy(self.session.execution)
        self.session.calls.clear()
        self.assertEqual(rag.start_indexing(self.session, TARGET, self.source, retry_failed=True)["status"], "reused")
        self.assert_no_writes()
        for key, value in (("itemsProcessed", None), ("itemsProcessed", False),
                           ("itemsFailed", False), ("endTime", "invalid")):
            with self.subTest(key=key, value=value):
                self.session.execution = copy.deepcopy(successful)
                self.session.execution["lastResult"][key] = value
                with self.assertRaises(RuntimeError):
                    rag.start_indexing(self.session, TARGET, self.source, retry_failed=True)
                self.assert_no_writes()

    def test_explicit_retry_recovers_terminal_failure_without_retrying_active_or_successful_runs(self):
        self.prepare()
        rag.start_indexing(self.session, TARGET, self.source)
        self.session.execution["lastResult"] = {"status": "transientFailure"}
        with self.assertRaises(RuntimeError):
            rag.start_indexing(self.session, TARGET, self.source)
        result = rag.start_indexing(self.session, TARGET, self.source, retry_failed=True)
        self.assertEqual("running", result["status"])
        rag.start_indexing(self.session, TARGET, self.source, retry_failed=True)
        self.assertEqual(1, len([row for row in self.session.calls if row[0] == "POST" and "/run?" in row[1]]))

    def test_live_retrieval_chain_cannot_be_repointed_while_index_remains_valid(self):
        self.prepare()
        names = rag.artifact_names(self.source)
        source_url = rag.search_url(TARGET, f"knowledgesources/{names['knowledge_source_name']}")
        self.session.resources[source_url] = rag._source_definition(names["index_name"], names["knowledge_source_name"])
        self.session.resources[rag.search_url(TARGET, f"knowledgebases/{names['knowledge_base_name']}")] = rag._base_definition(
            names["knowledge_source_name"], names["knowledge_base_name"])
        self.session.resources[f"{TARGET.project_id}/connections/{names['connection_name']}"] = rag._connection_body(
            rag.search_url(TARGET, f"knowledgebases/{names['knowledge_base_name']}/mcp"))
        rag.verify_retrieval_binding(self.session, TARGET, self.source)
        self.session.resources[source_url]["searchIndexParameters"]["searchIndexName"] = "different-index"
        with self.assertRaisesRegex(RuntimeError, "binding differs"):
            rag.verify_retrieval_binding(self.session, TARGET, self.source)
        self.session.resources[source_url] = rag._source_definition(names["index_name"], names["knowledge_source_name"])
        base_url = rag.search_url(TARGET, f"knowledgebases/{names['knowledge_base_name']}")
        self.session.resources[base_url]["knowledgeSources"] = [{"name": "other-source"}]
        with self.assertRaisesRegex(RuntimeError, "binding differs"):
            rag.verify_retrieval_binding(self.session, TARGET, self.source)
        self.session.resources[base_url] = rag._base_definition(names["knowledge_source_name"], names["knowledge_base_name"])
        connection_id = f"{TARGET.project_id}/connections/{names['connection_name']}"
        connection = copy.deepcopy(self.session.resources[connection_id])
        for key, value in (("authType", "ApiKey"), ("target", "https://other.search.windows.net/mcp"),
                           ("credentials", {"key": "forbidden"}), ("sharedUserList", ["other"])):
            with self.subTest(key=key):
                self.session.resources[connection_id] = copy.deepcopy(connection)
                self.session.resources[connection_id]["properties"][key] = value
                with self.assertRaisesRegex(RuntimeError, "connection authentication or target"):
                    rag.verify_retrieval_binding(self.session, TARGET, self.source)

    def setUp(self):
        self.source, self.expected = fixture()
        self.session = FakeSession(self.source)
        private = patch.object(rag, "require_private_endpoint")
        self.private = private.start()
        self.addCleanup(private.stop)
        staged = patch.object(rag, "verify_destination", side_effect=self.staged)
        self.destination_check = staged.start()
        self.addCleanup(staged.stop)

    def staged(self, session, target, source):
        self.assertIs(session, self.session)
        self.assertEqual(target, TARGET)
        self.assertEqual(source, self.source)
        session.destination_checks.append(len(session.calls))
        return {"destination": rag.destination(source), "binding_fingerprint": source.binding_fingerprint,
                "bytes": 123, "sha256": source.sha256, "content_verified": True,
                "source": source.as_dict(), "target": target.to_dict()}

    def common(self):
        self.source, self.expected = fixture(True)
        self.session = FakeSession(self.source)

    def configure(self, **kwargs):
        return rag.configure_indexing(self.session, TARGET, self.source, **kwargs)

    def prepare(self):
        self.session.ready()
        self.configure(apply=True)
        self.session.persisted(self.expected)
        self.session.calls.clear()
        self.session.destination_checks.clear()
        self.destination_check.reset_mock()

    def verify(self):
        return rag.verify_indexed(self.session, TARGET, self.source, self.expected)

    def assert_no_writes(self):
        self.assertFalse([call for call in self.session.calls if call[0] in {"PUT", "PATCH", "DELETE"}
                          or (call[0] == "POST" and "/docs/search?" not in call[1])])

    def test_names_are_bounded_immutable_and_distinct(self):
        source = replace(self.source, source_key="Mixed.UPPER_" + "x" * 230)
        names = rag.artifact_names(source)
        self.assertEqual(names["indexing_contract"], "adf-materialized/v1")
        values = [value for key, value in names.items() if key.endswith("_name")]
        self.assertEqual(len(set(values)), 6)
        for name in values:
            self.assertRegex(name, r"^aif-rag-[a-z0-9-]{1,32}-[a-f0-9]{12}-[a-z]+$")
            self.assertNotIn("--", name)
            self.assertLess(len(name), 100)
        self.assertNotEqual(names, rag.artifact_names(replace(source, sha256="f" * 64)))
        self.assertEqual(names, rag.artifact_names(source))
        old_suffix = source.binding_fingerprint[:12]
        new_suffix = sha256((source.binding_fingerprint + "|adf-materialized/v1").encode())[:12]
        self.assertNotEqual(old_suffix, new_suffix)
        self.assertTrue(all(f"-{new_suffix}-" in name and f"-{old_suffix}-" not in name for name in values))

    def test_project_definitions_full_iq_schema_private_keyless_pinned_mapping(self):
        body = rag.definitions(self.source)
        names = rag.artifact_names(self.source)
        self.assertEqual(body["index"], index_schema(names["index_name"]))
        ds = body["data_source"]
        dest = rag.destination(self.source)
        self.assertEqual(ds["credentials"], {"connectionString": f"ResourceId={TARGET.storage_id};"})
        self.assertEqual(ds["container"], {"name": dest["container"], "query": dest["query"]})
        self.assertEqual(dest["query"], f"sources/{self.source.binding_fingerprint}/knowledge/")
        self.assertTrue(dest["blob_path"].endswith("/items.json"))
        indexer = body["indexer"]
        self.assertFalse(indexer["disabled"])
        self.assertEqual(indexer["parameters"]["configuration"]["parsingMode"], "jsonArray")
        self.assertEqual(indexer["parameters"]["configuration"]["executionEnvironment"], "private")
        self.assertEqual(indexer["parameters"]["maxFailedItems"], 0)
        self.assertEqual(indexer["parameters"]["maxFailedItemsPerBatch"], 0)
        self.assertEqual(indexer["fieldMappings"][0], {"sourceFieldName": "AzureSearch_DocumentKey", "targetFieldName": "id", "mappingFunction": {"name": "base64Encode"}})
        self.assertEqual({row["sourceFieldName"] for row in indexer["fieldMappings"][1:]}, {"/" + key for key in rag._FIELDS[:-1]})
        for item in (ds, indexer):
            self.assertIn("45-rag-agent", item["description"])
            self.assertIn(self.source.binding_fingerprint, item["description"])
            self.assertIn(rag.INDEXING_CONTRACT, item["description"])
        for forbidden in ("schedule", "skillset", "vector", "embedding", "sample_question", "sample_ground_truth", "AccountKey", "SharedAccessSignature"):
            self.assertNotIn(forbidden, json.dumps(body))

    def test_common_definitions_do_not_index_manifest_metadata_or_acl(self):
        self.common()
        indexer = rag.definitions(self.source)["indexer"]
        self.assertEqual(indexer["parameters"]["configuration"]["parsingMode"], "jsonLines")
        self.assertEqual({item["sourceFieldName"]: item["targetFieldName"] for item in indexer["fieldMappings"][1:]}, {
            "/document_id": "topic", "/text": "content", "/source_uri": "source_url",
            "/source_version": "source_version", "/source_sha256": "content_sha256", "metadata_storage_path": "document_url"})
        self.assertNotIn("acl", json.dumps(indexer))
        dest = rag.destination(self.source)
        ds = rag.definitions(self.source)["data_source"]
        self.assertEqual(ds["credentials"], {"connectionString": f"ResourceId={TARGET.storage_id};"})
        self.assertEqual(ds["container"], {"name": "agent-factory-rag", "query": dest["query"]})
        self.assertEqual(dest["query"], f"sources/{self.source.binding_fingerprint}/knowledge/")
        self.assertTrue(dest["blob_path"].endswith("/items.jsonl"))
        self.assertNotIn(self.source.storage_id, json.dumps(ds))
        self.assertNotIn(self.source.blob_path, json.dumps(ds))

    def test_plan_reports_exact_staging_metadata_without_reading_source_or_destination(self):
        self.common()
        result = self.configure()
        self.assertEqual(result["status"], "needs-setup")
        self.assertEqual(len(result["prerequisites"]), 1)
        self.assertEqual(result["destination"], rag.destination(self.source))
        self.assertEqual(result["original_source_blob"], self.source.blob_url)
        self.assertEqual(result["materialized_blob"], rag.destination(self.source)["blob_url"])
        self.assertIsNone(result["destination_verification"])
        self.destination_check.assert_not_called()
        self.assert_no_writes()
        self.assertEqual(result["index_name"], rag.artifact_names(self.source)["index_name"])
        self.assertTrue(any(url == rag._search_id(TARGET) for _, url, *_ in self.session.calls))
        self.assertFalse(any("/resourceGroups/common-rg/providers/Microsoft.Search/" in url for _, url, *_ in self.session.calls))
        self.assertFalse(any(self.source.storage_id in url for _, url, *_ in self.session.calls))

    def test_private_project_storage_search_semantic_and_identity_are_prerequisites(self):
        self.common()
        mutations = [("storage", "publicNetworkAccess", "Enabled"), ("storage", "allowBlobPublicAccess", True),
                     ("service", "publicNetworkAccess", "enabled"),
                     ("service", "semanticSearch", "disabled")]
        for kind, key, value in mutations:
            with self.subTest(kind=kind, key=key):
                self.session = FakeSession(self.source)
                getattr(self.session, kind)["properties"][key] = value
                with self.assertRaises(ValueError):
                    self.configure(apply=True)
                self.assert_no_writes()
        self.session = FakeSession(self.source)
        self.session.service["identity"]["type"] = "UserAssigned"
        with self.assertRaisesRegex(ValueError, "system-assigned"):
            self.configure(apply=True)
        self.assert_no_writes()

    def test_target_cannot_be_rebound_to_common_group(self):
        with self.assertRaisesRegex(ValueError, "original project"):
            rag.configure_indexing(self.session, replace(TARGET, resource_group="common-rg"), self.source, apply=True)
        self.assertFalse(self.session.calls)

    def test_missing_existing_project_network_is_reported_never_created(self):
        result = self.configure(apply=True)
        self.assert_no_writes()
        self.assertEqual(result["status"], "needs-setup")
        self.assertIn("Existing project Search Blob", result["prerequisites"][0])
        self.destination_check.assert_not_called()
        self.assertFalse(any("/indexers/" in call[1] for call in self.session.calls))
        with self.assertRaisesRegex(RuntimeError, "private-link prerequisites"):
            rag.start_indexing(self.session, TARGET, self.source)
        self.assert_no_writes()

    def test_unique_matching_shared_link_is_reused_without_new_link(self):
        self.common()
        self.session.ready()
        self.session.storage["properties"]["isHnsEnabled"] = False
        result = self.configure(apply=True)
        self.assertEqual(result["private_link"]["id"], rag._search_id(TARGET) + "/sharedPrivateLinkResources/SearchBlobSPL")
        self.assertEqual(result["status"], "configured")
        self.assertFalse(any(method == "PUT" and "/sharedPrivateLinkResources/" in url for method, url, *_ in self.session.calls))
        self.assertFalse(any("/roleAssignments/" in url for _, url, *_ in self.session.calls))
        self.assertFalse(any("/indexers/" in url for _, url, *_ in self.session.calls))
        self.assertFalse(any("/privateEndpointConnections" in url for _, url, *_ in self.session.calls))
        self.assertFalse(any(self.source.storage_id in url for _, url, *_ in self.session.calls))
        self.destination_check.assert_called_once_with(self.session, TARGET, self.source)

    def test_ambiguous_links_are_rejected_and_unrelated_links_are_not_overwritten(self):
        self.session.ready()
        self.session.links.append(copy.deepcopy(self.session.links[0]))
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.configure(apply=True)
        self.assert_no_writes()
        self.session.links.pop()
        self.session.links[0]["properties"]["privateLinkResourceId"] += "-other"
        self.assertEqual(self.configure(apply=True)["status"], "needs-setup")
        self.assert_no_writes()

    def test_common_source_link_cannot_satisfy_project_staging_prerequisite(self):
        self.common()
        self.session.ready()
        common = copy.deepcopy(self.session.links[0])
        common["id"] += "-common"
        common["properties"]["privateLinkResourceId"] = self.source.storage_id
        self.session.links = [common]
        self.assertEqual(self.configure(apply=True)["status"], "needs-setup")
        self.assert_no_writes()
        self.session.ready()
        self.session.links.append(common)
        self.assertEqual(self.configure(apply=True)["status"], "configured")
        self.assertFalse(any(self.source.storage_id in url for _, url, *_ in self.session.calls))

    def test_existing_link_group_ownership_and_approval_must_be_exact(self):
        for key, value in (("groupId", "dfs"), ("status", "Pending"), ("provisioningState", "Updating")):
            with self.subTest(key=key):
                self.session = FakeSession(self.source)
                self.session.ready()
                self.session.links[0]["properties"][key] = value
                self.assertEqual(self.configure(apply=True)["status"], "needs-setup")
                self.assert_no_writes()
        for resource_id in (
            rag._search_id(TARGET).replace("project-rg", "common-rg") + "/sharedPrivateLinkResources/SearchBlobSPL",
            rag._search_id(TARGET) + "/sharedPrivateLinkResources/SearchBlobSPL/child",
        ):
            self.session = FakeSession(self.source)
            self.session.ready()
            self.session.links[0]["id"] = resource_id
            with self.assertRaisesRegex(ValueError, "not bound"):
                self.configure(apply=True)
            self.assert_no_writes()

    def test_every_creation_and_restart_verifies_staged_destination_before_mutation(self):
        for shared in (False, True):
            with self.subTest(shared=shared):
                self.source, self.expected = fixture(shared)
                self.session = FakeSession(self.source)
                self.session.ready()
                for action in (
                    lambda: self.configure(apply=True),
                    lambda: rag.start_indexing(self.session, TARGET, self.source),
                    lambda: rag.start_indexing(self.session, TARGET, self.source, retry_failed=True),
                ):
                    self.session.calls.clear()
                    self.session.destination_checks.clear()
                    self.destination_check.reset_mock()
                    result = action()
                    self.destination_check.assert_called_once_with(self.session, TARGET, self.source)
                    mutation_positions = [i for i, call in enumerate(self.session.calls) if call[0] in {"PUT", "POST"}]
                    self.assertTrue(mutation_positions)
                    self.assertLessEqual(self.session.destination_checks[0], min(mutation_positions))
                    self.assertEqual(result["destination_verification"]["sha256"], self.source.sha256)
                    self.session.execution["lastResult"] = {"status": "persistentFailure"}

    def test_missing_or_wrong_staged_bytes_prevent_creation_restart_and_verification(self):
        self.session.ready()
        for error in (ValueError("Materialized SHA-256 differs"), AzureError(404, "GET", "staged", "missing")):
            self.destination_check.side_effect = error
            for action in (lambda: self.configure(apply=True),
                           lambda: rag.start_indexing(self.session, TARGET, self.source)):
                self.session.calls.clear()
                with self.assertRaises(type(error)):
                    action()
                self.assert_no_writes()
                self.assertFalse(self.session.resources)
        self.destination_check.side_effect = self.staged
        self.prepare()
        rag.start_indexing(self.session, TARGET, self.source)
        self.session.execution["lastResult"] = {"status": "persistentFailure"}
        self.session.calls.clear()
        self.destination_check.side_effect = ValueError("Materialized SHA-256 differs")
        for action in (lambda: rag.start_indexing(self.session, TARGET, self.source, retry_failed=True), self.verify):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                action()
            self.assert_no_writes()
        self.assertFalse(any("/docs/search?" in url for _, url, *_ in self.session.calls))

    def test_unverified_or_wrong_destination_evidence_prevents_all_search_creation(self):
        self.session.ready()
        evidence = self.staged(self.session, TARGET, self.source)
        wrong_dest = {**evidence["destination"], "blob_url": self.source.blob_url}
        for key, value in (("sha256", "f" * 64), ("binding_fingerprint", "other"), ("destination", wrong_dest),
                           ("content_verified", False), ("content_verified", 1),
                           ("bytes", 0), ("bytes", True), ("bytes", rag.MAX_BYTES + 1)):
            with self.subTest(key=key, value=value):
                self.destination_check.side_effect = None
                self.destination_check.return_value = {**evidence, key: value}
                for action in (lambda: self.configure(apply=True),
                               lambda: rag.start_indexing(self.session, TARGET, self.source)):
                    self.session.calls.clear()
                    with self.assertRaisesRegex(ValueError, "Materialized destination verification"):
                        action()
                    self.assert_no_writes()
                    self.assertFalse(self.session.resources)

    def test_real_destination_hash_check_is_the_precreation_boundary(self):
        from agent_factory import rag_materialization
        self.common()
        self.session.ready()
        self.destination_check.side_effect = rag_materialization.verify_destination
        with patch.object(rag_materialization.rag_sources, "read_blob", return_value=b"not the pinned source") as read:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                self.configure(apply=True)
        self.destination_check.assert_called_once_with(self.session, TARGET, self.source)
        pinned = read.call_args.args[1]
        self.assertEqual(pinned.storage_name, TARGET.storage_name)
        self.assertEqual(pinned.container, "agent-factory-rag")
        self.assertEqual(pinned.blob_path, rag.destination(self.source)["blob_path"])
        self.assertEqual(pinned.sha256, self.source.sha256)
        self.assert_no_writes()
        self.assertFalse(self.session.resources)

    def test_legacy_exact_filename_artifacts_are_never_updated_or_used(self):
        self.session.ready()
        old_prefix = f"aif-rag-{self.source.source_key}-{self.source.binding_fingerprint[:12]}"
        legacy = {
            rag.search_url(TARGET, f"indexes/{old_prefix}-index"): {"name": old_prefix + "-index"},
            rag.search_url(TARGET, f"datasources/{old_prefix}-blob"): {
                "name": old_prefix + "-blob", "container": {"name": self.source.container, "query": self.source.blob_path}},
        }
        self.session.resources.update(copy.deepcopy(legacy))
        self.configure(apply=True)
        rag.start_indexing(self.session, TARGET, self.source)
        self.assertEqual({key: self.session.resources[key] for key in legacy}, legacy)
        self.assertFalse(any(old_prefix in url for _, url, *_ in self.session.calls))

    def test_configuration_and_start_refuse_schema_datasource_and_indexer_collisions(self):
        self.prepare()
        names = rag.artifact_names(self.source)
        index_url = rag.search_url(TARGET, f"indexes/{names['index_name']}")
        self.session.resources[index_url]["fields"].append({"name": "sample_ground_truth"})
        with self.assertRaisesRegex(ValueError, "evaluation"):
            self.configure(apply=True)
        self.assert_no_writes()
        self.session.resources[index_url] = index_schema(names["index_name"])
        ds_url = rag.search_url(TARGET, f"datasources/{names['data_source_name']}")
        self.session.resources[ds_url]["credentials"] = {"connectionString": "AccountKey=forbidden"}
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.configure(apply=True)
        self.assert_no_writes()
        self.session.resources[ds_url] = rag.definitions(self.source)["data_source"]
        indexer_url = rag.search_url(TARGET, f"indexers/{names['indexer_name']}")
        self.session.resources[indexer_url] = {**rag.definitions(self.source)["indexer"], "schedule": {"interval": "PT5M"}}
        with self.assertRaisesRegex(ValueError, "incompatible"):
            rag.start_indexing(self.session, TARGET, self.source)
        self.assert_no_writes()

    def test_redacted_datasource_credential_reasserted_as_mi_with_etag(self):
        self.common()
        self.prepare()
        name = rag.artifact_names(self.source)["data_source_name"]
        url = rag.search_url(TARGET, f"datasources/{name}")
        self.session.resources[url]["@odata.etag"] = '"version-one"'
        request = self.session.request

        def redacted(method, requested_url, body=None, **kwargs):
            result = request(method, requested_url, body, **kwargs)
            if method == "GET" and requested_url == url:
                result["credentials"] = {"connectionString": None}
            return result

        with patch.object(self.session, "request", side_effect=redacted):
            self.configure(apply=True)
        put = next(call for call in self.session.calls if call[0] == "PUT")
        self.assertEqual(put[1], url)
        self.assertEqual(put[2]["credentials"], {"connectionString": f"ResourceId={TARGET.storage_id};"})
        self.assertEqual(put[3]["headers"]["If-Match"], '"version-one"')
        self.destination_check.assert_called_once_with(self.session, TARGET, self.source)
        self.assertLessEqual(self.session.destination_checks[0], self.session.calls.index(put))

    def test_redacted_datasource_is_not_reasserted_when_materialized_pin_is_wrong(self):
        self.prepare()
        name = rag.artifact_names(self.source)["data_source_name"]
        url = rag.search_url(TARGET, f"datasources/{name}")
        self.session.resources[url].update(credentials={"connectionString": None}, **{"@odata.etag": '"one"'})
        self.destination_check.side_effect = ValueError("Materialized SHA-256 differs")
        for action in (lambda: self.configure(apply=True),
                       lambda: rag.start_indexing(self.session, TARGET, self.source)):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                action()
        self.assert_no_writes()

    def test_create_is_the_single_initial_start_success_reuse_requires_verification(self):
        self.prepare()
        result = rag.start_indexing(self.session, TARGET, self.source)
        self.assertEqual(result["status"], "running")
        self.assertFalse(result["content_verified"])
        self.assertEqual(len([url for method, url, *_ in self.session.calls if method == "PUT" and "/indexers/" in url]), 1)
        self.assertFalse(any(method == "POST" for method, *_ in self.session.calls))
        self.session.calls.clear()
        result = rag.start_indexing(self.session, TARGET, self.source)
        self.assertEqual(result["status"], "reused")
        self.assertFalse(result["content_verified"])
        self.assert_no_writes()
        self.assertEqual(rag.poll_indexing(self.session, TARGET, self.source)["status"], "success")
        verified = self.verify()
        self.assertTrue(verified["content_verified"])
        self.assertEqual(verified["document_count"], 1)
        self.assertNotIn(self.expected[0]["content"], json.dumps(verified))

    def test_live_in_progress_tracking_never_restarts(self):
        self.prepare()
        rag.start_indexing(self.session, TARGET, self.source)
        self.session.execution["lastResult"] = {"status": "inProgress"}
        self.session.calls.clear()
        self.assertEqual(rag.start_indexing(self.session, TARGET, self.source)["status"], "running")
        self.assert_no_writes()
        self.assertFalse(any(method == "POST" for method, *_ in self.session.calls))
        with patch.object(rag.time, "monotonic", side_effect=[0, 2]), self.assertRaises(TimeoutError):
            rag.poll_indexing(self.session, TARGET, self.source, timeout=1, interval=1)
        self.assert_no_writes()

    def test_failed_warned_empty_and_invalid_execution_never_report_success(self):
        self.prepare()
        rag.start_indexing(self.session, TARGET, self.source)
        original = copy.deepcopy(self.session.execution)
        for key, value in (("status", "transientFailure"), ("itemsFailed", 1), ("itemsFailed", False),
                           ("itemsProcessed", 0), ("warnings", [{"message": "secret content"}]),
                           ("errors", [{"message": "secret content"}]), ("endTime", "invalid"),
                           ("startTime", "2026-09-16T19:00:00Z")):
            with self.subTest(key=key, value=value):
                self.session.execution = copy.deepcopy(original)
                self.session.execution["lastResult"][key] = value
                self.session.calls.clear()
                with self.assertRaises(RuntimeError) as exc:
                    rag.start_indexing(self.session, TARGET, self.source)
                self.assertNotIn("secret content", str(exc.exception))
                self.assert_no_writes()
                with self.assertRaises(RuntimeError):
                    rag.poll_indexing(self.session, TARGET, self.source)

    def test_poll_limit_validation_and_no_creation(self):
        for kwargs in ({"timeout": 901}, {"timeout": 0}, {"timeout": True}, {"interval": 0}, {"timeout": 1, "interval": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                rag.poll_indexing(self.session, TARGET, self.source, **kwargs)
        self.assertFalse(self.session.calls)
        with self.assertRaisesRegex(RuntimeError, "does not exist"):
            rag.poll_indexing(self.session, TARGET, self.source)
        self.assert_no_writes()

    def test_poll_rejects_changed_version_and_missing_service_status(self):
        self.prepare()
        rag.start_indexing(self.session, TARGET, self.source)
        request = self.session.request

        def changed(method, url, body=None, **kwargs):
            result = request(method, url, body, **kwargs)
            if "/status?" in url:
                indexer = rag.artifact_names(self.source)["indexer_name"]
                self.session.resources[rag.search_url(TARGET, f"indexers/{indexer}")]["@odata.etag"] = "changed"
            return result

        with patch.object(self.session, "request", side_effect=changed), self.assertRaisesRegex(RuntimeError, "version changed"):
            rag.poll_indexing(self.session, TARGET, self.source)
        del self.session.execution["status"]
        with self.assertRaisesRegex(RuntimeError, "not healthy"):
            rag.poll_indexing(self.session, TARGET, self.source)

    def test_common_verification_hashes_exact_text_and_ignores_unmapped_manifest_metadata(self):
        self.common()
        self.prepare()
        self.assertEqual(self.expected[0]["license"], "CC0-1.0")
        self.assertIsNone(self.session.rows[0]["license"])
        result = self.verify()
        self.assertEqual(result["documents"][0]["content_sha256"], sha256(self.expected[0]["content"].encode()))
        self.assertEqual(result["binding_fingerprint"], self.source.binding_fingerprint)
        query = next(body for method, url, body, _ in self.session.calls if "/docs/search?" in url)
        self.assertEqual(query["top"], 1000)
        self.assertTrue(query["count"])
        self.destination_check.assert_called_once_with(self.session, TARGET, self.source)

    def test_verification_preserves_original_and_materialized_lineage_for_both_formats(self):
        for shared in (False, True):
            with self.subTest(shared=shared):
                self.source, self.expected = fixture(shared)
                self.session = FakeSession(self.source)
                self.prepare()
                original = copy.deepcopy(self.expected)
                result = self.verify()
                dest = rag.destination(self.source)
                self.assertEqual(result["original_source_blob"], self.source.blob_url)
                self.assertEqual(result["materialized_blob"], dest["blob_url"])
                self.assertNotEqual(result["original_source_blob"], result["materialized_blob"])
                self.assertEqual(result["source_sha256"], self.source.sha256)
                self.assertEqual(result["materialized_sha256"], self.source.sha256)
                self.assertEqual(result["document_count"], len(original))
                self.assertEqual(result["destination"], dest)
                self.assertEqual(self.expected, original)
                self.assertNotIn(original[0]["content"], json.dumps(result))
                self.destination_check.assert_called_once_with(self.session, TARGET, self.source)
                wrong_url = self.source.blob_url if shared else dest["blob_url"]
                self.session.rows[0]["document_url"] = wrong_url
                with self.assertRaisesRegex(RuntimeError, "provenance"):
                    self.verify()

    def test_extra_staged_documents_and_paged_counts_cannot_be_verified(self):
        self.prepare()
        self.session.rows.append({**self.session.rows[0], "id": "unexpected-key", "topic": "unexpected"})
        self.session.count = 2
        with self.assertRaisesRegex(RuntimeError, "exact pinned corpus"):
            self.verify()
        self.session.persisted(self.expected)
        request = self.session.request
        for continuation in ("@odata.nextLink", "@search.nextPageParameters"):
            def paged(method, url, body=None, **kwargs):
                response = request(method, url, body, **kwargs)
                if "/docs/search?" in url:
                    response[continuation] = "more"
                return response
            with self.subTest(continuation=continuation), patch.object(self.session, "request", side_effect=paged):
                with self.assertRaisesRegex(RuntimeError, "exact pinned corpus"):
                    self.verify()

    def test_exact_count_unique_topics_keys_and_content_are_required(self):
        self.prepare()
        original = copy.deepcopy(self.session.rows)
        mutations = [
            lambda: setattr(self.session, "count", 0),
            lambda: setattr(self.session, "count", True),
            lambda: setattr(self.session, "rows", []),
            lambda: self.session.rows[0].update(content=""),
            lambda: self.session.rows[0].update(content=self.expected[0]["content"] + "\n"),
            lambda: self.session.rows[0].update(topic="unrelated"),
            lambda: self.session.rows[0].update(id=""),
            lambda: self.session.rows[0].update(source_url="https://example.org/other"),
            lambda: self.session.rows[0].update(source_version="2"),
            lambda: self.session.rows[0].update(document_url=self.source.blob_url + "-other"),
            lambda: self.session.rows[0].update(license=None),
            lambda: self.session.rows[0].update(dataset_sha256="f" * 64),
        ]
        for number, mutate in enumerate(mutations):
            with self.subTest(number=number):
                self.session.rows, self.session.count = copy.deepcopy(original), 1
                mutate()
                with self.assertRaises(RuntimeError):
                    self.verify()
        self.expected.append({**self.expected[0], "topic": "other"})
        self.session.rows = [copy.deepcopy(original[0]), copy.deepcopy(original[0])]
        self.session.count = 2
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            self.verify()
        self.session.rows[1]["topic"] = "other"
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            self.verify()

    def test_content_hash_is_independent_of_index_claim_and_expected_claim(self):
        self.common()
        self.prepare()
        self.session.rows[0]["content"] += " changed"
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            self.verify()
        self.session.persisted(self.expected)
        self.session.rows[0]["content_sha256"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "provenance"):
            self.verify()
        self.expected[0]["content_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "content hashes"):
            self.verify()

    def test_expected_empty_duplicate_extra_eval_and_wrong_pin_documents_rejected(self):
        self.prepare()
        original = copy.deepcopy(self.expected)
        for rows in ([], original * 2, [{**original[0], "sample_question": "never"}],
                     [{**original[0], "document_url": "https://example.org/other"}], original * 1001):
            with self.subTest(count=len(rows)), self.assertRaises(ValueError):
                rag.verify_indexed(self.session, TARGET, self.source, rows)

    def test_invalid_expected_provenance_is_rejected_even_if_the_index_agrees(self):
        self.prepare()
        original = copy.deepcopy(self.expected)
        for key, value in (("source_url", None), ("source_url", "https://example.org/doc?sig=secret"),
                           ("source_version", ""), ("source_version", "2"), ("license", None),
                           ("attribution", ""), ("dataset_sha256", None)):
            with self.subTest(key=key):
                self.expected = [{**original[0], key: value}]
                self.session.persisted(self.expected)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_non_404_errors_propagate_without_fallback_or_paid_upgrades(self):
        self.prepare()
        for status in (401, 403, 409, 429, 500):
            with self.subTest(status=status):
                self.session.calls.clear()
                self.session.error = status
                with self.assertRaises(AzureError):
                    self.configure(apply=True)
                self.assert_no_writes()
        self.assertFalse(any("regenerate" in url or "listKeys" in url or "upgrade" in url for _, url, *_ in self.session.calls))

    def test_no_operator_data_writes_environment_credentials_or_new_compute(self):
        self.common()
        self.prepare()
        with patch.dict("os.environ", {"AZURE_STORAGE_CONNECTION_STRING": "AccountKey=never", "AZURE_STORAGE_KEY": "never",
                                      "AZURE_CLIENT_SECRET": "never", "AZURE_SEARCH_ADMIN_KEY": "never"}):
            rag.start_indexing(self.session, TARGET, self.source)
            rag.poll_indexing(self.session, TARGET, self.source)
            self.verify()
        for method, url, body, kwargs in self.session.calls:
            self.assertNotIn("never", json.dumps(body))
            self.assertNotIn("/docs/index", url)
            self.assertNotIn("/providers/Microsoft.Compute/", url)
            if url.startswith("https://"):
                self.assertTrue(url.startswith(TARGET.search_endpoint))
                self.assertEqual(kwargs["audience"], "https://search.azure.com")
            self.assertNotIn(method, {"DELETE", "PATCH"})


if __name__ == "__main__":
    unittest.main()
