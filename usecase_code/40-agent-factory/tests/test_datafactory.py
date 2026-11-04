import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from agent_factory.azure import AzureError
from agent_factory.config import Target
from agent_factory import data, datafactory as adf
from agent_factory import knowledge


def target():
    return Target(
        tenant_id="11111111-1111-1111-1111-111111111111",
        subscription_id="22222222-2222-2222-2222-222222222222",
        resource_group="project-rg", common_resource_group="common-rg",
        account_name="foundry-account", project_name="project-001",
        project_endpoint="https://foundry-account.services.ai.azure.com/api/projects/project-001",
        location="swedencentral", model_deployment="chat", embedding_deployment="",
        search_name="project-search", storage_name="aifstorage2001",
        identity_id="/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/project-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/project-mi",
        identity_client_id="33333333-3333-3333-3333-333333333333",
    )


FACTORY = "project-factory"
RUN_ID = "44444444-4444-4444-4444-444444444444"
SEARCH_PRINCIPAL = "55555555-5555-5555-5555-555555555555"


def fixture():
    rows = [
        {"topic": "VPN", "content": "# Connect\n\nUse the approved client."},
        {"topic": "Printer", "content": "# Paper jam\n\nTurn off before removing paper."},
    ]
    pin = {"bytes": 43111, "raw_sha256": "a" * 64, "raw_md5_base64": "IFNWpmC6OiCSv0l31Akzuw==",
           "row_count": len(rows), "documents": []}
    for row in rows:
        pin["documents"].append({
            "id": data.sha256(data.json_bytes([row["topic"], row["content"]])),
            "topic": row["topic"], "content_sha256": data.sha256(row["content"].encode("utf-8")),
        })
    return rows, pin


class FakeAzure:
    def __init__(self, rows, pin, approved=True):
        self.calls = []
        self.pin = pin
        self.approved = approved
        self.factory_id = adf._factory_id(target(), FACTORY)
        self.arm_resources = {
            self.factory_id: {
                "properties": {"publicNetworkAccess": "Disabled"},
                "identity": {"userAssignedIdentities": {target().identity_id: {}}},
            },
            f"{self.factory_id}/credentials/{adf.CREDENTIAL}": {
                "properties": {"type": "ManagedIdentity", "typeProperties": {"resourceId": target().identity_id}},
            },
            f"{self.factory_id}/integrationRuntimes/{adf.INTEGRATION_RUNTIME}": {
                "properties": {"type": "Managed", "managedVirtualNetwork": {"referenceName": "default"}},
            },
            f"{self.factory_id}/linkedservices/ls_storage_lake": {"properties": {
                "type": "AzureBlobFS", "typeProperties": {
                    "url": f"https://{target().storage_name}.dfs.core.windows.net",
                    "credential": {"referenceName": adf.CREDENTIAL, "type": "CredentialReference"},
                },
            }},
            target().storage_id: {"properties": {"publicNetworkAccess": "Disabled", "allowBlobPublicAccess": False}},
            adf._search_id(target()): {
                "sku": {"name": "basic"}, "properties": {"publicNetworkAccess": "disabled", "semanticSearch": "free"},
                "identity": {"type": "SystemAssigned", "principalId": SEARCH_PRINCIPAL},
            },
        }
        self.search_resources = {}
        self.docs = []
        self.corpus = [{
            **row, "id": f"indexer-generated-{i}", "source_url": data.DATASET_URL,
            "source_version": data.DATASET_VERSION, "license": "MIT", "attribution": data.ATTRIBUTION,
            "dataset_sha256": pin["raw_sha256"],
            "document_url": f"https://{target().storage_name}.blob.core.windows.net/{adf.CONTAINER}/{adf.PREFIX}/knowledge/items.json",
        } for i, row in enumerate(rows)]
        self.pipeline_status = "Succeeded"
        self.pipeline_name = adf.PIPELINE_NAME
        self.bad_activity = None
        self.bad_md5 = False
        self.indexer_failure = False
        self.indexer_warning = False
        self.indexer_generation = 0
        self.semantic = True
        self.started = 0

    def arm(self, method, resource_id, body=None, api_version=None):
        self.calls.append((method, resource_id, copy.deepcopy(body), {"api_version": api_version}))
        if resource_id.endswith("/createRun"):
            self.started += 1
            return {"runId": RUN_ID}
        if resource_id.endswith(f"/pipelineruns/{RUN_ID}"):
            return {"runId": RUN_ID, "pipelineName": self.pipeline_name,
                    "status": self.pipeline_status, "runStart": "2026-09-11T09:00:00Z",
                    "message": "DO-NOT-LOG-RAW-CSV-OR-SIGNED-URL"}
        if resource_id.endswith("/queryActivityruns"):
            definitions = adf.build_datafactory_definitions(target(), factory_name=FACTORY)
            activities = [{
                "activityName": activity["name"], "status": "Succeeded", "output": {},
            } for activity in definitions["pipeline"]["properties"]["activities"]]
            for activity in activities:
                if activity["activityName"] == self.bad_activity:
                    activity["status"] = "Failed"
                if activity["activityName"] == "InspectRaw":
                    activity["output"] = {
                        "size": self.pin["bytes"],
                        "contentMD5": "wrong" if self.bad_md5 else self.pin["raw_md5_base64"],
                    }
                if activity["activityName"] in {"InspectPublished", "InspectEvaluation"}:
                    activity["output"] = {"size": 1000, "contentMD5": "sealed-blob-checksum"}
            return {"value": activities}
        if resource_id.endswith(("/managedPrivateEndpoints", "/sharedPrivateLinkResources")):
            return {"value": [copy.deepcopy(value) for key, value in self.arm_resources.items()
                              if key.startswith(f"{resource_id}/")]}
        if method == "GET":
            if resource_id not in self.arm_resources:
                raise AzureError(404, method, resource_id, "missing")
            return copy.deepcopy(self.arm_resources[resource_id])
        if method == "PUT":
            value = copy.deepcopy(body)
            value["id"] = resource_id
            value["name"] = resource_id.rsplit("/", 1)[1]
            if "/managedPrivateEndpoints/" in resource_id or "/sharedPrivateLinkResources/" in resource_id:
                value["properties"]["provisioningState"] = "Succeeded"
                status = "Approved" if self.approved else "Pending"
                if "/sharedPrivateLinkResources/" in resource_id:
                    value["properties"]["status"] = status
                else:
                    value["properties"]["connectionState"] = {"status": status}
            self.arm_resources[resource_id] = value
            return copy.deepcopy(value)
        raise AssertionError((method, resource_id, body))

    def request(self, method, url, body=None, **kwargs):
        self.calls.append((method, url, copy.deepcopy(body), kwargs))
        if "/docs/search?" in url:
            if body.get("queryType") == "semantic":
                return {"value": [{"id": "indexer-generated-0", "@search.rerankerScore": 3.2}]} if self.semantic else {"value": []}
            return {"@odata.count": len(self.docs), "value": copy.deepcopy(self.docs)}
        if "/indexers/" in url and "/status?" in url:
            if not self.indexer_generation:
                return {"lastResult": None}
            result = {
                "status": "transientFailure" if self.indexer_failure else "success",
                "startTime": f"2026-09-11T10:0{self.indexer_generation}:00Z",
                "endTime": f"2026-09-11T10:0{self.indexer_generation}:01Z",
                "itemsProcessed": len(self.docs), "itemsFailed": 0,
                "warnings": [{"message": "warning"}] if self.indexer_warning else [], "errors": [],
            }
            return {"status": "running", "lastResult": result}
        if "/indexers/" in url and "/run?" in url:
            self.indexer_generation += 1
            self.docs = copy.deepcopy(self.corpus)
            return {}
        if method == "GET":
            if url not in self.search_resources:
                raise AzureError(404, method, url, "missing")
            return copy.deepcopy(self.search_resources[url])
        if method == "PUT":
            self.search_resources[url] = copy.deepcopy(body)
            if "/indexers/" in url:
                self.indexer_generation += 1
                self.docs = copy.deepcopy(self.corpus)
            return copy.deepcopy(body)
        raise AssertionError((method, url, body))


class DefinitionTests(unittest.TestCase):
    def test_pinned_reference_contains_no_raw_or_evaluation_content(self):
        pin = adf.integrity_reference()
        self.assertEqual(pin["bytes"], 43111)
        self.assertEqual(pin["row_count"], 10)
        self.assertEqual(len(pin["documents"]), 10)
        self.assertEqual(pin["raw_sha256"], "c48e1db2f7d1da20f7c66935f707d4b7caddbc9e898a0d0838f68aaff0f85ce7")
        self.assertNotIn("sample_ground_truth", json.dumps(pin))
        self.assertNotIn('"content":', json.dumps(pin))

    def test_copy_authentication_projection_and_multiline_csv_schema(self):
        definitions = adf.build_datafactory_definitions(target(), factory_name=FACTORY)
        services = definitions["linked_services"]
        http = services["aif_kaggle_http"]["properties"]
        self.assertEqual(http["typeProperties"]["url"], data.DOWNLOAD_URL)
        self.assertEqual(http["typeProperties"]["authenticationType"], "Anonymous")
        self.assertTrue(http["typeProperties"]["enableServerCertificateValidation"])
        blob = services["aif_kaggle_blob"]["properties"]
        self.assertEqual(blob["typeProperties"]["credential"],
                         {"referenceName": "ls_cred_project_uami", "type": "CredentialReference"})
        self.assertEqual(blob["connectVia"]["referenceName"], adf.INTEGRATION_RUNTIME)
        self.assertIn("2001.blob.core.windows.net", blob["typeProperties"]["serviceEndpoint"])
        for banned in ("accountKey", "sasToken", "connectionString", "DefaultAzureCredential", "AzureCliCredential"):
            self.assertNotIn(banned, json.dumps(services))
        csv = definitions["datasets"]["aif_kaggle_raw_csv"]["properties"]["typeProperties"]
        self.assertEqual(csv["quoteChar"], '"')
        self.assertEqual(csv["escapeChar"], '"')
        self.assertTrue(csv["firstRowAsHeader"])
        self.assertNotIn("multiLine", csv)
        activities = {activity["name"]: activity for activity in definitions["pipeline"]["properties"]["activities"]}
        projection = activities["CopyKnowledge"]["typeProperties"]["translator"]["mappings"]
        sources = {mapping["source"]["name"] for mapping in projection}
        self.assertTrue({"ki_topic", "ki_text"} <= sources)
        self.assertNotIn("sample_question", sources)
        self.assertNotIn("sample_ground_truth", sources)
        sinks = {mapping["sink"]["path"] for mapping in projection}
        self.assertIn("$['topic']", sinks)
        self.assertIn("$['content']", sinks)
        self.assertNotIn("$['content_sha256']", sinks)
        evaluation = activities["CopyEvaluation"]["typeProperties"]["translator"]["mappings"]
        self.assertIn("sample_ground_truth", {mapping["source"]["name"] for mapping in evaluation})
        self.assertTrue(activities["ReadKnowledge"]["policy"]["secureOutput"])
        self.assertTrue(activities["CopyEvaluation"]["policy"]["secureOutput"])

    def test_integrity_gates_and_publication_order(self):
        definitions = adf.build_datafactory_definitions(target(), factory_name=FACTORY)
        pipeline = definitions["pipeline"]["properties"]
        self.assertEqual(pipeline["concurrency"], 1)
        self.assertNotIn("parameters", pipeline)
        activities = {activity["name"]: activity for activity in pipeline["activities"]}
        self.assertNotIn("validateDataConsistency", activities["DownloadRaw"]["typeProperties"])
        for name in ("SealRaw", "PublishKnowledge", "SealEvaluation"):
            self.assertTrue(activities[name]["typeProperties"]["validateDataConsistency"])
        integrity = activities["ValidateRawIntegrity"]["typeProperties"]["expression"]["value"]
        self.assertIn("contentMD5", integrity)
        self.assertIn(adf.integrity_reference()["raw_md5_base64"], integrity)
        self.assertIn("union(", activities["ValidateKnowledge"]["typeProperties"]["expression"]["value"])
        self.assertEqual(activities["PublishKnowledge"]["dependsOn"], adf._depends("ValidateKnowledge"))
        self.assertEqual(activities["InspectCSV"]["dependsOn"], adf._depends("ValidateRawIntegrity"))
        self.assertEqual(activities["CopyKnowledge"]["dependsOn"], adf._depends("ValidateCSVHeader"))
        self.assertNotIn("ExecuteDataFlow", json.dumps(pipeline))
        self.assertNotIn("sha2(", json.dumps(pipeline))

    def test_basic_indexer_scope_and_document_key(self):
        definitions = adf.build_datafactory_definitions(target(), factory_name=FACTORY)
        datasource = definitions["data_source"]
        self.assertEqual(datasource["type"], "azureblob")
        self.assertEqual(datasource["container"]["query"], f"{adf.PREFIX}/knowledge/")
        self.assertEqual(datasource["credentials"]["connectionString"], f"ResourceId={target().storage_id};")
        self.assertNotIn("identity", datasource)
        indexer = definitions["indexer"]
        self.assertEqual(indexer["parameters"]["configuration"]["executionEnvironment"], "private")
        self.assertEqual(indexer["parameters"]["configuration"]["parsingMode"], "jsonArray")
        self.assertNotIn("skillsetName", indexer)
        self.assertNotIn("schedule", indexer)
        self.assertEqual(indexer["fieldMappings"][0], {
            "sourceFieldName": "AzureSearch_DocumentKey", "targetFieldName": "id",
            "mappingFunction": {"name": "base64Encode"},
        })
        self.assertNotIn("sample_ground_truth", json.dumps(indexer))
        self.assertNotIn("metadata_storage_path", json.dumps(indexer))
        self.assertNotIn("raw/", json.dumps(datasource))
        self.assertNotIn("evaluation/", json.dumps(datasource))

    def test_wrong_storage_and_factory_names_rejected_without_io(self):
        for storage in ("aifstorage1001", "aifstorage10012001", "aifstorage3001"):
            with self.assertRaises(ValueError):
                adf.build_datafactory_definitions(replace(target(), storage_name=storage), factory_name=FACTORY)
        for name in ("../factory", "x", "x" * 64, "factory?query=bad"):
            with self.assertRaises(ValueError):
                adf.build_datafactory_definitions(target(), factory_name=name)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.pin = fixture()
        patcher = patch.object(adf, "integrity_reference", return_value=self.pin)
        patcher.start()
        self.addCleanup(patcher.stop)
        private = patch.object(adf, "require_private_endpoint")
        private.start()
        self.addCleanup(private.stop)
        self.session = FakeAzure(self.rows, self.pin)

    def configure(self):
        return adf.configure_datafactory_ingestion(self.session, target(), factory_name=FACTORY)

    def test_configure_creates_only_owned_control_plane_and_empty_index(self):
        result = self.configure()
        self.assertEqual(result["status"], "configured")
        self.assertEqual(result["search_identity_principal_id"], SEARCH_PRINCIPAL)
        self.assertTrue(result["indexer_deferred_until_pipeline_success"])
        self.assertEqual(result["index_name"], adf.INDEX_NAME)
        self.assertTrue(all(link["approved"] for link in result["private_endpoints"]))
        self.assertEqual(self.session.docs, [])
        self.assertEqual(self.session.started, 0)
        for method, url, body, *_ in self.session.calls:
            if method == "PUT":
                self.assertNotIn("/indexers/", url)
                self.assertNotIn(".blob.core.windows.net", url)
                self.assertNotIn(".dfs.core.windows.net", url)
                self.assertNotEqual(url, self.session.factory_id)
                self.assertNotEqual(url, adf._search_id(target()))
                self.assertNotEqual(url, target().storage_id)
        self.assertFalse(any(method in {"PATCH", "DELETE"} for method, *_ in self.session.calls))

    def test_rerun_is_idempotent_no_puts(self):
        self.configure()
        pipeline = f"{self.session.factory_id}/pipelines/{adf.PIPELINE_NAME}"
        self.session.arm_resources[pipeline]["properties"]["lastPublishTime"] = "2026-09-11T10:19:25Z"
        self.session.calls.clear()
        self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_redacted_datasource_credentials_are_reasserted_with_etag(self):
        self.configure()
        self.session.calls.clear()
        original_request = self.session.request

        def request(method, url, body=None, **kwargs):
            result = original_request(method, url, body, **kwargs)
            if method == "GET" and "/datasources/" in url:
                result["credentials"] = {"connectionString": None}
                result["@odata.etag"] = '"version-1"'
            return result

        with patch.object(self.session, "request", side_effect=request):
            self.assertEqual("configured", self.configure()["status"])
        updates = [call for call in self.session.calls if call[0] == "PUT"]
        self.assertEqual(1, len(updates))
        self.assertIn("/datasources/", updates[0][1])
        self.assertEqual('"version-1"', updates[0][3]["headers"]["If-Match"])
        self.assertEqual(f"ResourceId={target().storage_id};", updates[0][2]["credentials"]["connectionString"])

    def test_pending_endpoint_returns_prerequisites_and_blocks_start(self):
        self.session.approved = False
        result = self.configure()
        self.assertEqual(result["status"], "awaiting-private-endpoint-approval")
        self.assertTrue(result["prerequisites"])
        self.assertFalse(self.session.search_resources)
        with self.assertRaisesRegex(RuntimeError, "not Approved"):
            adf.start_datafactory_ingestion(self.session, target(), factory_name=FACTORY)
        self.assertEqual(self.session.started, 0)

    def test_existing_shared_private_link_is_reused_without_rename(self):
        collection = f"{adf._search_id(target())}/sharedPrivateLinkResources"
        existing_id = f"{collection}/existing-approved-blob"
        self.session.arm_resources[existing_id] = {
            "id": existing_id, "name": "existing-approved-blob", "properties": {
                "groupId": "blob", "privateLinkResourceId": target().storage_id,
                "status": "Approved", "provisioningState": "Succeeded",
            },
        }
        result = self.configure()
        self.assertEqual(result["private_endpoints"][1]["resource_id"], existing_id)
        self.assertFalse(any(method == "PUT" and "/sharedPrivateLinkResources/" in url for method, url, *_ in self.session.calls))

    def test_dfs_endpoint_does_not_substitute_for_blob_endpoint(self):
        resource_id = f"{self.session.factory_id}/managedVirtualNetworks/default/managedPrivateEndpoints/mpe_storage_lake"
        self.session.arm_resources[resource_id] = {
            "id": resource_id, "name": "mpe_storage_lake", "properties": {
                "groupId": "dfs", "privateLinkResourceId": target().storage_id,
                "connectionState": {"status": "Approved"}, "provisioningState": "Succeeded",
            },
        }
        self.configure()
        puts = [(url, body) for method, url, body, _ in self.session.calls
                if method == "PUT" and "/managedPrivateEndpoints/" in url]
        self.assertEqual(len(puts), 1)
        self.assertEqual(puts[0][1]["properties"]["groupId"], "blob")
        self.assertNotEqual(puts[0][0], resource_id)

    def test_missing_factory_requires_existing_deployment(self):
        del self.session.arm_resources[self.session.factory_id]
        with self.assertRaisesRegex(RuntimeError, "existing project pipeline"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_no_project_uami_or_managed_vnet_fallback(self):
        self.session.arm_resources[self.session.factory_id]["identity"] = {"type": "SystemAssigned"}
        with self.assertRaisesRegex(ValueError, "project UAMI"):
            self.configure()
        self.session.arm_resources[self.session.factory_id]["identity"] = {"userAssignedIdentities": {target().identity_id: {}}}
        runtime = f"{self.session.factory_id}/integrationRuntimes/{adf.INTEGRATION_RUNTIME}"
        self.session.arm_resources[runtime]["properties"]["managedVirtualNetwork"] = None
        with self.assertRaisesRegex(ValueError, "managed VNet"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_bad_credential_or_lake_1001_refused(self):
        credential = f"{self.session.factory_id}/credentials/{adf.CREDENTIAL}"
        original = copy.deepcopy(self.session.arm_resources[credential])
        self.session.arm_resources[credential]["properties"]["typeProperties"]["resourceId"] = "another-uami"
        with self.assertRaisesRegex(ValueError, "required project UAMI"):
            self.configure()
        self.session.arm_resources[credential] = original
        lake = f"{self.session.factory_id}/linkedservices/ls_storage_lake"
        self.session.arm_resources[lake]["properties"]["typeProperties"]["url"] = "https://aifstorage1001.dfs.core.windows.net"
        with self.assertRaisesRegex(ValueError, "2001"):
            self.configure()

    def test_project_identity_resource_id_is_case_insensitive(self):
        credential = f"{self.session.factory_id}/credentials/{adf.CREDENTIAL}"
        self.session.arm_resources[credential]["properties"]["typeProperties"]["resourceId"] = target().identity_id.upper()
        self.assertEqual("configured", self.configure()["status"])

    def test_approval_is_bound_to_one_storage_connection_and_requester(self):
        connection_id = target().storage_id + "/privateEndpointConnections/selected"
        endpoint_id = "/subscriptions/managed/resourceGroups/managed/providers/Microsoft.Network/privateEndpoints/selected"
        self.session.arm_resources[connection_id] = {"properties": {
            "privateEndpoint": {"id": endpoint_id},
            "privateLinkServiceConnectionState": {"status": "Pending"},
        }}
        with self.assertRaisesRegex(ValueError, "does not match"):
            adf.approve_storage_connection(self.session, target(), connection_id=connection_id,
                                           expected_private_endpoint_id=endpoint_id + "-other")
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))
        result = adf.approve_storage_connection(
            self.session, target(), connection_id=connection_id, expected_private_endpoint_id=endpoint_id,
        )
        self.assertEqual("Approved", result["status"])
        self.assertEqual([connection_id], [url for method, url, *_ in self.session.calls if method == "PUT"])

    def test_public_storage_and_missing_search_mi_refused(self):
        self.session.arm_resources[target().storage_id]["properties"]["allowBlobPublicAccess"] = True
        with self.assertRaisesRegex(ValueError, "anonymous Blob"):
            self.configure()
        self.session.arm_resources[target().storage_id]["properties"]["allowBlobPublicAccess"] = False
        self.session.arm_resources[adf._search_id(target())]["identity"] = {"type": "None"}
        with self.assertRaisesRegex(ValueError, "Search system-assigned"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_unowned_container_or_pipeline_not_overwritten(self):
        container_id = f"{target().storage_id}/blobServices/default/containers/{adf.CONTAINER}"
        self.session.arm_resources[container_id] = {"properties": {"publicAccess": "None", "metadata": {"owner": "unrelated"}}}
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))
        del self.session.arm_resources[container_id]
        self.configure()
        pipeline_id = f"{self.session.factory_id}/pipelines/{adf.PIPELINE_NAME}"
        self.session.arm_resources[pipeline_id]["properties"]["activities"].append({"name": "unrelated", "type": "Wait"})
        self.session.calls.clear()
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_extra_active_linked_service_credentials_are_refused(self):
        self.configure()
        service_id = f"{self.session.factory_id}/linkedservices/aif_kaggle_blob"
        self.session.arm_resources[service_id]["properties"]["typeProperties"]["servicePrincipalKey"] = "unapproved"
        self.session.calls.clear()
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            self.configure()
        self.assertFalse(any(method == "PUT" for method, *_ in self.session.calls))

    def test_other_index_documents_refused(self):
        self.configure()
        self.session.docs = [{"id": "other", "document_url": "https://private/other"}]
        with self.assertRaisesRegex(ValueError, "unrelated"):
            self.configure()

    def test_403_not_treated_as_missing(self):
        with patch.object(self.session, "arm", side_effect=AzureError(403, "GET", "resource", "denied")):
            with self.assertRaises(AzureError) as error:
                self.configure()
        self.assertEqual(error.exception.status, 403)

    def test_run_waits_for_adf_before_creating_indexer_and_verifies_corpus(self):
        result = adf.run_datafactory_ingestion(self.session, target(), factory_name=FACTORY, poll_interval=1)
        self.assertEqual(result["status"], "ingested")
        self.assertEqual(result["document_count"], 2)
        self.assertTrue(result["corpus_sha256_verified"])
        self.assertFalse(result["raw_sha256_computed_by_adf"])
        self.assertEqual(result["blob_integrity"]["raw"]["md5_base64"], self.pin["raw_md5_base64"])
        self.assertEqual(result["knowledge_kwargs"], {"index_name": adf.INDEX_NAME})
        self.assertEqual(result["run_id"], RUN_ID)
        self.assertEqual(len(result["documents"]), 2)
        self.assertNotIn("# Connect", json.dumps(result))
        order = [(method, url) for method, url, *_ in self.session.calls]
        evidence = next(i for i, (_, url) in enumerate(order) if url.endswith("/queryActivityruns"))
        indexer = next(i for i, (method, url) in enumerate(order) if method == "PUT" and "/indexers/" in url)
        self.assertLess(evidence, indexer)
        self.assertFalse(any(method == "POST" and "/docs/index?" in url for method, url in order))
        self.assertFalse(any(method == "POST" and "/run?" in url for method, url in order))

    def test_existing_indexer_reruns_without_reset_or_duplicate_documents(self):
        first = adf.run_datafactory_ingestion(self.session, target(), factory_name=FACTORY, poll_interval=1)
        self.session.calls.clear()
        second = adf.run_datafactory_ingestion(self.session, target(), factory_name=FACTORY, poll_interval=1)
        self.assertEqual(first["documents"], second["documents"])
        self.assertTrue(any(method == "POST" and "/indexers/" in url and "/run?" in url
                            for method, url, *_ in self.session.calls))
        self.assertFalse(any("/reset?" in url or method == "DELETE" for method, url, *_ in self.session.calls))

    def test_poll_resumes_running_indexer_without_starting_another(self):
        adf.run_datafactory_ingestion(self.session, target(), factory_name=FACTORY, poll_interval=1)
        self.session.calls.clear()
        original_request = self.session.request
        status_reads = 0

        def request(method, url, body=None, **kwargs):
            nonlocal status_reads
            result = original_request(method, url, body, **kwargs)
            if "/indexers/" in url and "/status?" in url:
                status_reads += 1
                if status_reads == 1:
                    result["lastResult"]["status"] = "inProgress"
            return result

        with patch.object(self.session, "request", side_effect=request):
            result = adf.poll_datafactory_ingestion(
                self.session, target(), factory_name=FACTORY, run_id=RUN_ID, poll_interval=1,
            )
        self.assertEqual("ingested", result["status"])
        self.assertFalse(any(method == "POST" and "/indexers/" in url and "/run?" in url
                             for method, url, *_ in self.session.calls))

    def test_published_adf_index_integrates_with_existing_foundry_iq(self):
        result = adf.run_datafactory_ingestion(self.session, target(), factory_name=FACTORY, poll_interval=1)
        with patch.object(knowledge, "require_private_endpoint"):
            iq = knowledge.configure_knowledge(self.session, target(), **result["knowledge_kwargs"])
        self.assertEqual(iq["document_count"], len(self.rows))
        self.assertEqual(iq["tool"]["allowed_tools"], ["knowledge_base_retrieve"])
        source = self.session.search_resources[data.search_url(target(), "knowledgesources/aif-kaggle-source")]
        self.assertEqual(source["searchIndexParameters"]["searchIndexName"], adf.INDEX_NAME)

    def test_failed_adf_does_not_create_indexer_or_expose_runtime_detail(self):
        self.session.pipeline_status = "Failed"
        with self.assertRaisesRegex(RuntimeError, "Failed") as error:
            adf.run_datafactory_ingestion(self.session, target(), factory_name=FACTORY, poll_interval=1)
        self.assertNotIn("DO-NOT-LOG", str(error.exception))
        self.assertFalse(any(method == "PUT" and "/indexers/" in url for method, url, *_ in self.session.calls))

    def test_missing_activity_evidence_or_checksum_blocks_indexing(self):
        self.configure()
        self.session.bad_md5 = True
        with self.assertRaisesRegex(RuntimeError, "pinned raw CSV"):
            adf.poll_datafactory_ingestion(self.session, target(), factory_name=FACTORY, run_id=RUN_ID)
        self.session.bad_md5 = False
        self.session.bad_activity = "ValidateKnowledge"
        with self.assertRaisesRegex(RuntimeError, "missing successful"):
            adf.poll_datafactory_ingestion(self.session, target(), factory_name=FACTORY, run_id=RUN_ID)
        self.assertEqual(self.session.indexer_generation, 0)

    def test_indexer_errors_and_warnings_are_not_success(self):
        self.configure()
        self.session.indexer_warning = True
        with self.assertRaisesRegex(RuntimeError, "errors/warnings"):
            adf.poll_datafactory_ingestion(self.session, target(), factory_name=FACTORY, run_id=RUN_ID)
        self.session.indexer_warning = False
        self.session.indexer_failure = True
        with self.assertRaisesRegex(RuntimeError, "errors/warnings"):
            adf.poll_datafactory_ingestion(self.session, target(), factory_name=FACTORY, run_id=RUN_ID)

    def test_unrelated_run_id_and_changed_pipeline_refused(self):
        self.configure()
        self.session.pipeline_name = "other-pipeline"
        with self.assertRaisesRegex(ValueError, "pinned factory"):
            adf.poll_datafactory_ingestion(self.session, target(), factory_name=FACTORY, run_id=RUN_ID)
        self.session.pipeline_name = adf.PIPELINE_NAME
        pipeline_id = f"{self.session.factory_id}/pipelines/{adf.PIPELINE_NAME}"
        self.session.arm_resources[pipeline_id]["properties"]["description"] = "another owner"
        with self.assertRaisesRegex(ValueError, "definition changed"):
            adf.poll_datafactory_ingestion(self.session, target(), factory_name=FACTORY, run_id=RUN_ID)

    def test_corrupt_or_duplicate_corpus_and_semantic_failure_refused(self):
        adf.run_datafactory_ingestion(self.session, target(), factory_name=FACTORY, poll_interval=1)
        original = copy.deepcopy(self.session.docs)
        self.session.docs[0]["content"] += "tampered"
        with self.assertRaisesRegex(RuntimeError, "pinned corpus"):
            adf.verify_datafactory_index(self.session, target())
        self.session.docs = copy.deepcopy(original)
        self.session.docs[1] = {**self.session.docs[0], "id": "different-key"}
        with self.assertRaisesRegex(RuntimeError, "duplicates"):
            adf.verify_datafactory_index(self.session, target())
        self.session.docs = original
        self.session.semantic = False
        with self.assertRaisesRegex(RuntimeError, "Semantic ranking"):
            adf.verify_datafactory_index(self.session, target())

    def test_paging_and_timeouts_are_bounded(self):
        self.configure()
        self.session.pipeline_status = "InProgress"
        with patch.object(adf.time, "monotonic", side_effect=[0, 2]), self.assertRaisesRegex(TimeoutError, "resume polling"):
            adf.poll_datafactory_ingestion(
                self.session, target(), factory_name=FACTORY, run_id=RUN_ID, timeout_seconds=1, poll_interval=1,
            )
        with self.assertRaises(ValueError):
            adf.poll_datafactory_ingestion(self.session, target(), factory_name=FACTORY, run_id=RUN_ID, poll_interval=0)


if __name__ == "__main__":
    unittest.main()
