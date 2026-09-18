import copy
from dataclasses import replace
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from agent_factory import rag_materialization as rag
from agent_factory.azure import AzureError
from agent_factory import datafactory as adf, rag_sources
from tests.test_datafactory import FACTORY, RUN_ID, FakeAzure, fixture, target
from tests.test_rag_sources import knowledge, snapshot, Response

PRINCIPAL = "66666666-6666-6666-6666-666666666666"


def source_fixture(common=False):
    values = snapshot() if common else knowledge()
    return replace(values[0], target=target()), values[1]


class FakeSession(FakeAzure):
    def __init__(self, source, raw):
        super().__init__(*fixture())
        self.subscription_id, self.tenant_id = target().subscription_id, target().tenant_id
        self.source, self.raw = source, raw
        self.pipeline_name = rag.definitions(source, FACTORY)["pipeline_name"]
        self.arm_resources[target().identity_id] = {"properties": {
            "principalId": PRINCIPAL, "clientId": target().identity_client_id,
        }}
        self.arm_resources[source.storage_id] = {"properties": {
            "publicNetworkAccess": "Disabled", "allowBlobPublicAccess": False, "isHnsEnabled": True,
        }}
        self.project_link_id = self.factory_id + "/managedVirtualNetworks/default/managedPrivateEndpoints/existing-project-blob"
        self.arm_resources[self.project_link_id] = {"id": self.project_link_id, "properties": {
            "privateLinkResourceId": target().storage_id, "groupId": "blob",
            "connectionState": {"status": "Approved"}, "provisioningState": "Succeeded",
        }}
        self.activities = [
            {"activityName": "InspectPinnedSource", "status": "Succeeded", "output": {"size": len(raw)}},
            {"activityName": "CopyPinnedDocuments", "status": "Succeeded", "output": {
                "dataRead": len(raw), "dataWritten": len(raw), "filesSkipped": 0,
            }},
            {"activityName": "InspectMaterialized", "status": "Succeeded", "output": {"size": len(raw)}},
        ]

    def arm(self, method, resource_id, body=None, api_version=None):
        if resource_id.endswith("/queryActivityruns"):
            self.calls.append((method, resource_id, copy.deepcopy(body), {"api_version": api_version}))
            return {"value": copy.deepcopy(self.activities)}
        if resource_id.endswith("/privateEndpointConnections"):
            self.calls.append((method, resource_id, copy.deepcopy(body), {"api_version": api_version}))
            return {"value": [copy.deepcopy(value) for key, value in self.arm_resources.items()
                              if key.startswith(resource_id + "/")]}
        if method == "PUT" and "/roleAssignments/" in resource_id:
            body = copy.deepcopy(body)
            body["properties"]["scope"] = resource_id.split("/providers/Microsoft.Authorization")[0]
        if method == "PUT" and "/privateEndpointConnections/" in resource_id:
            body = {"properties": {**self.arm_resources[resource_id]["properties"], **body["properties"]}}
        return super().arm(method, resource_id, body, api_version)


class DefinitionTests(unittest.TestCase):
    def test_exact_binary_source_and_separate_destination_for_both_formats(self):
        for common in (False, True):
            source, _ = source_fixture(common)
            definitions = rag.definitions(source, FACTORY)
            dest = definitions["destination"]
            self.assertEqual(dest["container"], "agent-factory-rag")
            self.assertEqual(dest["storage_id"], target().storage_id)
            self.assertEqual(dest["blob_path"], f"sources/{source.binding_fingerprint}/knowledge/items.{'jsonl' if common else 'json'}")
            self.assertEqual(dest["query"], dest["blob_path"].rsplit("/", 1)[0] + "/")
            locations = [dataset["properties"]["typeProperties"]["location"] for dataset in definitions["datasets"].values()]
            self.assertEqual(locations[0]["container"], source.container)
            self.assertEqual(locations[0]["folderPath"] + "/" + locations[0]["fileName"], source.blob_path)
            self.assertEqual(locations[1]["container"], dest["container"])
            for dataset in definitions["datasets"].values():
                self.assertEqual(dataset["properties"]["type"], "Binary")
            for service in definitions["linked_services"].values():
                properties = service["properties"]
                self.assertEqual(properties["type"], "AzureBlobStorage")
                self.assertEqual(properties["typeProperties"]["credential"]["referenceName"], adf.CREDENTIAL)
                self.assertEqual(properties["connectVia"]["referenceName"], adf.INTEGRATION_RUNTIME)
            serialized = json.dumps(definitions)
            for forbidden in ("evaluation", "raw/", "wildcard", "accountKey", "sasToken", "Lookup", "HttpServer"):
                self.assertNotIn(forbidden, serialized)

    def test_copy_logs_secure_and_execution_bounded(self):
        source, _ = source_fixture()
        pipeline = rag.definitions(source, FACTORY)["pipeline"]["properties"]
        self.assertEqual(pipeline["concurrency"], 1)
        self.assertNotIn("parameters", pipeline)
        activity = pipeline["activities"][1]
        self.assertEqual(activity["name"], "CopyPinnedDocuments")
        self.assertEqual(activity["policy"]["timeout"], "0.00:10:00")
        self.assertEqual(activity["policy"]["retry"], 0)
        self.assertTrue(activity["policy"]["secureInput"])
        self.assertTrue(activity["policy"]["secureOutput"])
        self.assertTrue(activity["typeProperties"]["validateDataConsistency"])
        self.assertFalse(activity["typeProperties"]["source"]["storeSettings"]["recursive"])
        self.assertFalse(activity["typeProperties"]["enableStaging"])
        for activity in (pipeline["activities"][0], pipeline["activities"][2]):
            self.assertEqual(activity["typeProperties"]["fieldList"], ["size"])
            self.assertTrue(activity["policy"]["secureInput"])

    def test_full_binding_changes_names_and_destination(self):
        source, _ = source_fixture()
        other = replace(source, sha256="c" * 64)
        self.assertNotEqual(rag.destination(source), rag.destination(other))
        self.assertNotEqual(rag.definitions(source, FACTORY)["pipeline_name"], rag.definitions(other, FACTORY)["pipeline_name"])

    def test_common_role_is_exact_content_reader_with_bounded_listing(self):
        source, _ = source_fixture(True)
        scope, _, body = rag.reader_assignment(target(), source, PRINCIPAL)
        props = body["properties"]
        self.assertEqual(scope, source.storage_id + "/blobServices/default/containers/" + source.container)
        self.assertEqual(props["principalId"], PRINCIPAL)
        self.assertTrue(props["roleDefinitionId"].endswith(rag.READER_ROLE))
        self.assertEqual(props["conditionVersion"], "2.0")
        self.assertIn("blobs:path] StringEquals '" + source.blob_path + "'", props["condition"])
        self.assertIn("blobs:prefix] StringEquals '" + source.blob_path.rsplit("/", 1)[0] + "/'", props["condition"])
        self.assertNotIn("StringLike", props["condition"])
        self.assertNotIn("*", props["condition"])
        self.assertNotIn("write", json.dumps(body))
        with self.assertRaises(ValueError):
            rag.reader_assignment(target(), source_fixture()[0], PRINCIPAL)


class ConfigurationTests(unittest.TestCase):
    def test_plan_performs_no_writes_even_when_grant_requested(self):
        source, raw = source_fixture(True)
        session = FakeSession(source, raw)
        result = rag.configure_materialization(session, target(), source, FACTORY, grant_read=True)
        self.assertEqual(result["status"], "needs-setup")
        self.assertTrue(all(call[0] == "GET" for call in session.calls))

    def test_project_reuses_existing_endpoint_and_role_no_source_writes(self):
        source, raw = source_fixture()
        session = FakeSession(source, raw)
        result = rag.configure_materialization(session, target(), source, FACTORY, apply=True, grant_read=True)
        self.assertEqual(result["status"], "configured")
        writes = [call for call in session.calls if call[0] != "GET"]
        self.assertTrue(writes)
        self.assertFalse(any("/roleAssignments/" in call[1] or "/managedPrivateEndpoints/" in call[1] for call in writes))
        self.assertFalse(any(source.container in call[1] for call in writes))
        self.assertFalse(any(call[0] == "POST" for call in writes))
        self.assertEqual(result["private_endpoints"][0]["id"], session.project_link_id)
        self.assertEqual(result["project_identity_principal_id"], PRINCIPAL)
        session.calls.clear()
        rag.configure_materialization(session, target(), source, FACTORY, apply=True)
        self.assertTrue(all(call[0] == "GET" for call in session.calls))

    def test_common_uses_project_uami_conditional_role_and_blob_endpoint(self):
        source, raw = source_fixture(True)
        session = FakeSession(source, raw)
        result = rag.configure_materialization(session, target(), source, FACTORY, apply=True, grant_read=True)
        self.assertEqual(result["status"], "configured")
        writes = [call for call in session.calls if call[0] == "PUT"]
        assignments = [call for call in writes if "/roleAssignments/" in call[1]]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0][2]["properties"]["principalId"], PRINCIPAL)
        links = [call for call in writes if "/managedPrivateEndpoints/" in call[1]]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][2]["properties"], {"privateLinkResourceId": source.storage_id, "groupId": "blob"})
        self.assertFalse(any("/Microsoft.Search/" in call[1] for call in writes))
        self.assertFalse(any(call[1].startswith(source.storage_id) and "/roleAssignments/" not in call[1] for call in writes))

    def test_drift_never_overwrites_owned_artifacts_or_role_condition(self):
        source, raw = source_fixture(True)
        session = FakeSession(source, raw)
        configured = rag.configure_materialization(session, target(), source, FACTORY, apply=True, grant_read=True)
        assignment = session.arm_resources[configured["reader_permission"]["role_assignment_id"]]
        assignment["properties"]["condition"] = ""
        session.calls.clear()
        with self.assertRaisesRegex(ValueError, "condition"):
            rag.configure_materialization(session, target(), source, FACTORY, apply=True, grant_read=True)
        self.assertTrue(all(call[0] == "GET" for call in session.calls))
        assignment["properties"]["condition"] = rag.reader_assignment(target(), source, PRINCIPAL)[2]["properties"]["condition"]
        pipeline = session.arm_resources[configured["factory_id"] + "/pipelines/" + configured["pipeline_name"]]
        pipeline["properties"]["activities"][1]["typeProperties"]["source"]["storeSettings"]["recursive"] = True
        with self.assertRaises(ValueError):
            rag.start_materialization(session, target(), source, FACTORY)
        self.assertEqual(session.started, 0)

    def test_preflight_rejects_wrong_identity_runtime_and_public_factory(self):
        source, raw = source_fixture()
        for resource_suffix, mutate in (
            ("", lambda props: props.update(publicNetworkAccess="Enabled")),
            ("/credentials/" + adf.CREDENTIAL, lambda props: props["typeProperties"].update(resourceId="wrong")),
            ("/integrationRuntimes/" + adf.INTEGRATION_RUNTIME, lambda props: props.update(managedVirtualNetwork={})),
        ):
            session = FakeSession(source, raw)
            mutate(session.arm_resources[session.factory_id + resource_suffix]["properties"])
            with self.assertRaises(ValueError):
                rag.configure_materialization(session, target(), source, FACTORY, apply=True)
            self.assertTrue(all(call[0] == "GET" for call in session.calls))

    def test_missing_destination_private_endpoint_never_falls_back(self):
        source, raw = source_fixture()
        session = FakeSession(source, raw)
        del session.arm_resources[session.project_link_id]
        result = rag.configure_materialization(session, target(), source, FACTORY, apply=True)
        self.assertEqual(result["status"], "needs-setup")
        with self.assertRaises(RuntimeError):
            rag.start_materialization(session, target(), source, FACTORY)
        self.assertEqual(session.started, 0)

    def test_approval_correlates_factory_endpoint_and_preserves_other_requests(self):
        source, raw = source_fixture(True)
        session = FakeSession(source, raw)
        result = rag.configure_materialization(session, target(), source, FACTORY, apply=True, grant_read=True)
        name = result["private_endpoints"][0]["id"].rsplit("/", 1)[1]
        endpoint = f"/subscriptions/{target().subscription_id}/resourceGroups/managed-rg/providers/Microsoft.Network/privateEndpoints/{FACTORY}.{name}.{RUN_ID}"
        connection_id = source.storage_id + "/privateEndpointConnections/selected"
        unrelated_id = source.storage_id + "/privateEndpointConnections/unrelated"
        for key, selected_endpoint in ((connection_id, endpoint), (unrelated_id, endpoint.replace(FACTORY, "other-factory"))):
            session.arm_resources[key] = {"id": key, "properties": {
                "privateEndpoint": {"id": selected_endpoint}, "privateLinkServiceConnectionState": {"status": "Pending"},
            }}
        planned = rag.configure_materialization(session, target(), source, FACTORY)
        self.assertEqual(planned["pending_storage_connections"], [{"connection_id": connection_id, "private_endpoint_id": endpoint}])
        session.calls.clear()
        with self.assertRaises(ValueError):
            rag.approve_materialization_link(session, target(), source, FACTORY, unrelated_id, endpoint.replace(FACTORY, "other-factory"))
        with self.assertRaises(ValueError):
            rag.approve_materialization_link(session, target(), source, FACTORY, connection_id, endpoint + "-wrong")
        result = rag.approve_materialization_link(session, target(), source, FACTORY, connection_id, endpoint)
        self.assertEqual(result["status"], "Approved")
        self.assertEqual([call[1] for call in session.calls if call[0] == "PUT"], [connection_id])
        self.assertEqual(session.arm_resources[unrelated_id]["properties"]["privateLinkServiceConnectionState"]["status"], "Pending")


class ExecutionTests(unittest.TestCase):
    def ready(self):
        source, raw = source_fixture()
        session = FakeSession(source, raw)
        rag.configure_materialization(session, target(), source, FACTORY, apply=True)
        session.calls.clear()
        return source, raw, session

    def test_start_one_post_then_poll_exact_run_and_staged_hash(self):
        source, raw, session = self.ready()
        started = rag.start_materialization(session, target(), source, FACTORY)
        self.assertEqual(started["run_id"], RUN_ID)
        self.assertEqual(session.started, 1)
        with patch.object(rag_sources, "read_blob", return_value=raw) as read:
            result = rag.poll_materialization(session, target(), source, FACTORY, RUN_ID)
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["content_verified"])
        self.assertEqual(result["bytes"], len(raw))
        self.assertEqual(session.started, 1)
        pinned = read.call_args.args[1]
        self.assertEqual(pinned.blob_path, rag.destination(source)["blob_path"])
        self.assertEqual(pinned.container, rag.CONTAINER)
        self.assertEqual(pinned.sha256, source.sha256)
        self.assertEqual(pinned.manifest_path, "")

    def test_secured_copy_output_uses_metadata_only_evidence_and_hash(self):
        source, raw, session = self.ready()
        session.activities[1]["output"] = {"message": "The output is secured."}
        session.activities[1]["error"] = {"errorCode": "", "message": "", "failureType": "",
                                         "target": "CopyPinnedDocuments", "details": ""}
        with patch.object(rag_sources, "read_blob", return_value=raw):
            self.assertTrue(rag.poll_materialization(session, target(), source, FACTORY, RUN_ID)["content_verified"])

    def test_zero_warning_missing_duplicate_failed_and_inconsistent_copy_fail(self):
        mutations = [
            lambda rows: rows[1]["output"].update(dataRead=0),
            lambda rows: rows[1]["output"].update(dataWritten=1),
            lambda rows: rows[1]["output"].update(warnings=[{"message": "do-not-log"}]),
            lambda rows: rows[1]["output"].update(filesSkipped=1),
            lambda rows: rows[1]["output"].update(executionDetails=[{"status": "Succeeded", "warnings": ["warning"]}]),
            lambda rows: rows[1].update(error={"errorCode": "400", "message": "do-not-log"}),
            lambda rows: rows[1].update(status="Failed"),
            lambda rows: rows[2]["output"].update(size=0),
            lambda rows: rows[2]["output"].update(size=True),
            lambda rows: rows.pop(),
            lambda rows: rows.append(copy.deepcopy(rows[1])),
        ]
        for mutate in mutations:
            source, _, session = self.ready()
            mutate(session.activities)
            with self.subTest(mutation=mutate), patch.object(rag_sources, "read_blob") as read:
                with self.assertRaises(RuntimeError) as error:
                    rag.poll_materialization(session, target(), source, FACTORY, RUN_ID)
                self.assertNotIn("do-not-log", str(error.exception))
                read.assert_not_called()

    def test_failed_or_unrelated_run_rejected_without_content_read_or_restart(self):
        for status, pipeline in (("Failed", None), ("Cancelled", None), ("Succeeded", "wrong-pipeline")):
            source, _, session = self.ready()
            session.pipeline_status = status
            if pipeline:
                session.pipeline_name = pipeline
            with patch.object(rag_sources, "read_blob") as read:
                with self.assertRaises((RuntimeError, ValueError)) as error:
                    rag.poll_materialization(session, target(), source, FACTORY, RUN_ID)
                self.assertNotIn("DO-NOT-LOG", str(error.exception))
                read.assert_not_called()
            self.assertEqual(session.started, 0)

    def test_timeout_does_not_restart(self):
        source, _, session = self.ready()
        session.pipeline_status = "InProgress"
        with patch.object(rag.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(TimeoutError, "resume polling"):
                rag.poll_materialization(session, target(), source, FACTORY, RUN_ID, timeout_seconds=1)
        self.assertEqual(session.started, 0)

    def test_changed_destination_bytes_fail(self):
        source, _, session = self.ready()
        with patch.object(rag_sources, "read_blob", return_value=b"changed"):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                rag.poll_materialization(session, target(), source, FACTORY, RUN_ID)

    def test_bounded_private_destination_read_preserves_binary_bytes(self):
        source, raw, session = self.ready()
        session.token = Mock(return_value="test-only-token")
        url = rag.destination(source)["blob_url"]
        response = Response(raw, url, {"Content-Length": str(len(raw))})
        with patch.object(rag_sources, "require_private_endpoint") as private, patch.object(rag_sources, "build_opener") as opener:
            opener.return_value.open.return_value = response
            result = rag.verify_destination(session, target(), source)
        self.assertEqual(result["sha256"], source.sha256)
        private.assert_called_once_with(url)
        self.assertTrue(all(0 < count <= 64 * 1024 for count in response.read_sizes))
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.get_header("Accept-encoding"), "identity")

    def test_destination_reader_rejects_oversized_redirected_encoded_and_missing(self):
        source, _, session = self.ready()
        session.token = Mock(return_value="test-only-token")
        url = rag.destination(source)["blob_url"]
        cases = [
            Response(b"", url, {"Content-Length": str(rag.MAX_BYTES + 1)}),
            Response(b"", url + "-other"),
            Response(b"", url, {"Content-Encoding": "gzip"}),
        ]
        for response in cases:
            with patch.object(rag_sources, "require_private_endpoint"), patch.object(rag_sources, "build_opener") as opener:
                opener.return_value.open.return_value = response
                with self.assertRaises((RuntimeError, ValueError)):
                    rag.verify_destination(session, target(), source)
        with patch.object(rag_sources, "require_private_endpoint"), patch.object(rag_sources, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError(url, 404, "missing", {}, io.BytesIO())
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                rag.verify_destination(session, target(), source)

    def test_wrong_session_or_target_fails_before_calls(self):
        source, raw = source_fixture()
        session = FakeSession(source, raw)
        session.tenant_id = "77777777-7777-7777-7777-777777777777"
        with self.assertRaises(ValueError):
            rag.configure_materialization(session, target(), source, FACTORY, apply=True)
        self.assertEqual(session.calls, [])
        with self.assertRaises(ValueError):
            rag.verify_destination(session, replace(target(), storage_name="different2001"), source)


if __name__ == "__main__":
    unittest.main()
