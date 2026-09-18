import copy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from agent_factory import data, datafactory as adf, knowledge, network, rag_indexing, rag_materialization
from agent_factory.azure import AzureError
from agent_factory.cli import load_selection, parser, run
from agent_factory.config import FactoryConfig, Target
from agent_factory.discovery import discover
from agent_factory.rag_sources import RagSource
from test_data import MemorySearch, csv_bytes, target as legacy_target
from test_datafactory import FakeAzure, FACTORY, fixture
from test_knowledge import FakeSession as KnowledgeSession
from test_rag_sources import binding


def selected_target(common, container=""):
    return replace(
        legacy_target(), use_common_datalake_storage=common,
        storage_name="spiderlake" if common else "projectdata",
        storage_resource_group="common-rg" if common else "project-rg",
        storage_container=container,
    )


def selected_config(common, container=""):
    target = selected_target(common, container)
    return FactoryConfig(
        target.tenant_id, target.subscription_id, "dev", "001", target.resource_group,
        target.common_resource_group, storage_name=target.storage_name,
        storage_resource_group=target.storage_resource_group,
        storage_container=target.storage_container, use_common_datalake_storage=common,
    )


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config.json"
        values = {
            "tenantId": legacy_target().tenant_id, "dev_sub_id": legacy_target().subscription_id,
            "project_number_000": "001", "admin_aifactoryPrefixRG": "",
            "admin_aifactorySuffixRG": "-001", "admin_locationSuffix": "sdc",
            "projectPrefix": "", "projectSuffix": "", "vnetResourceGroupBase": "common",
        }
        (self.path.parent / "variables.json").write_text(json.dumps({"dev": values}), encoding="utf-8")
        self.settings = {
            "use_common_datalake_storage": False,
            "storage_targets": {
                "common": {"account_name": "spiderlake", "resource_group": "common-rg"},
                "project": {"account_name": "projectdata", "resource_group": "project-rg"},
            },
            "targets": [{"key": "one", "variables_file": "variables.json", "selection": {
                "resource_group": "project-rg", "common_resource_group": "common-rg",
            }}],
        }

    def load(self):
        self.path.write_text(json.dumps(self.settings), encoding="utf-8")
        return load_selection(self.path, "one")[1]

    def test_root_true_false_defaults_and_offline_plan(self):
        for flag, group, name, container in (
            (True, "common-rg", "spiderlake", "lake3"),
            (False, "project-rg", "projectdata", "agent-factory"),
        ):
            with self.subTest(flag=flag):
                self.settings["use_common_datalake_storage"] = flag
                config = self.load()
                self.assertIs(config.use_common_datalake_storage, flag)
                self.assertEqual((group, name, container),
                                 (config.storage_resource_group, config.storage_name, config.storage_container))
                with patch("agent_factory.cli.AzureSession") as session:
                    result = run(parser().parse_args(["plan", "--config", str(self.path)]))
                session.assert_not_called()
                self.assertEqual(container, result["target"]["storage_container"])

    def test_omitted_flag_keeps_legacy_discovery_and_containers(self):
        self.settings.pop("use_common_datalake_storage")
        config = self.load()
        self.assertIsNone(config.use_common_datalake_storage)
        self.assertEqual("", config.storage_name)
        target = legacy_target()
        self.assertEqual("agent-factory", target.resolve_container())
        self.assertEqual(adf.CONTAINER, target.resolve_container(legacy=adf.CONTAINER))
        self.assertEqual("old-custom", target.resolve_container("old-custom"))

    def test_per_target_flag_and_profile_field_overrides_inherit_other_fields(self):
        selection = self.settings["targets"][0]["selection"]
        selection.update(use_common_datalake_storage=True,
                         storage_targets={"common": {"container": "reviewed", "account_name": "mrveldata"}})
        self.settings["targets"].append({
            "key": "two", "variables_file": "variables.json",
            "selection": {"resource_group": "project-rg", "common_resource_group": "common-rg"},
        })
        config = self.load()
        self.assertEqual(("mrveldata", "common-rg", "reviewed"),
                         (config.storage_name, config.storage_resource_group, config.storage_container))
        self.assertEqual("projectdata", load_selection(self.path, "two")[1].storage_name)
        self.assertEqual("spiderlake", self.settings["storage_targets"]["common"]["account_name"])

    def test_strict_boolean_including_root_even_if_target_overrides_it(self):
        for value in ("true", "false", 0, 1, None, [], {}):
            for location in ("root", "selection"):
                with self.subTest(value=value, location=location), self.assertRaisesRegex(ValueError, "JSON boolean"):
                    self.settings["use_common_datalake_storage"] = value if location == "root" else False
                    self.settings["targets"][0]["selection"]["use_common_datalake_storage"] = True if location == "root" else value
                    self.load()

    def test_missing_account_wrong_group_bad_container_and_contradictions(self):
        for changes in (
            {"account_name": ""}, {"account_name": "artifact1001"},
            {"resource_group": "common-rg"}, {"container": "bad/container"},
            {"account_name": "https://account"}, {"container": None},
        ):
            saved = copy.deepcopy(self.settings)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.settings["storage_targets"]["project"].update(changes)
                self.load()
            self.settings = saved
        self.settings["targets"][0]["selection"]["storage_name"] = "other2001"
        with self.assertRaisesRegex(ValueError, "contradicts"):
            self.load()
        self.settings["targets"][0]["selection"].pop("storage_name")
        self.settings.pop("storage_targets")
        with self.assertRaisesRegex(ValueError, "account_name"):
            self.load()

    def test_unknown_profile_fields_and_nonobject_selection_fail(self):
        self.settings["storage_targets"]["project"]["accountKey"] = "not-a-secret"
        with self.assertRaisesRegex(ValueError, "profile fields"):
            self.load()
        self.settings["targets"][0]["selection"] = None
        with self.assertRaisesRegex(ValueError, "objects"):
            self.load()


class DiscoverySession:
    def __init__(self, config):
        self.subscription_id, self.tenant_id = config.subscription_id, config.tenant_id
        self.calls = []
        self.project_id = f"/subscriptions/{config.subscription_id}/resourceGroups/project-rg"
        self.account = self.project_id + "/providers/Microsoft.CognitiveServices/accounts/foundry"
        self.identity = self.project_id + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi-prj001-data"
        self.resources = {
            "project-rg": [
                {"name": "foundry", "id": self.account, "type": "Microsoft.CognitiveServices/accounts",
                 "kind": "AIServices", "location": "swedencentral"},
                {"name": "search", "type": "Microsoft.Search/searchServices"},
                {"name": "mi-prj001-data", "id": self.identity, "type": "Microsoft.ManagedIdentity/userAssignedIdentities"},
            ],
            "common-rg": [],
        }
        for group, names in (("project-rg", ["projectdata", "aifstorage2001", "artifact1001", "amlworkspace"]),
                             ("common-rg", ["mrveldata", "spiderlake"])):
            for name in names:
                self.resources[group].append({
                    "name": name, "type": "Microsoft.Storage/storageAccounts",
                    "id": f"/subscriptions/{config.subscription_id}/resourceGroups/{group}/providers/Microsoft.Storage/storageAccounts/{name}",
                })

    def pages(self, url):
        self.calls.append(("GET", url))
        if "/resources?" in url:
            return self.resources[url.split("/resourceGroups/")[1].split("/")[0]]
        if "/projects?" in url:
            return [{"name": "project-001"}]
        if "/deployments?" in url:
            return [{"name": "chat", "properties": {"provisioningState": "Succeeded",
                                                  "model": {"format": "OpenAI", "name": "gpt"}}}]
        raise AssertionError(url)

    def arm(self, method, resource_id, **kwargs):
        self.calls.append((method, resource_id))
        if resource_id.endswith("/projects/project-001"):
            return {"properties": {"endpoints": {"AI Foundry API":
                "https://foundry.services.ai.azure.com/api/projects/project-001"}}}
        if resource_id == self.identity:
            return {"id": self.identity, "properties": {"clientId": legacy_target().identity_client_id}}
        raise AssertionError(resource_id)


class StorageDiscoveryTests(unittest.TestCase):
    def test_multiple_accounts_resolve_only_explicit_profile_and_keep_project_identity(self):
        for flag in (True, False):
            config = selected_config(flag)
            session = DiscoverySession(config)
            target = discover(config, session)
            self.assertEqual(config.storage_name, target.storage_name)
            self.assertEqual(selected_target(flag).storage_id, target.storage_id)
            self.assertIn("/resourceGroups/project-rg/", target.project_id)
            self.assertIn("/resourceGroups/project-rg/", target.identity_id)
            self.assertEqual("search", target.search_name)
            self.assertTrue(all(method == "GET" for method, _ in session.calls))
            common_reads = [url for _, url in session.calls if "/resourceGroups/common-rg/" in url]
            self.assertEqual(flag, bool(common_reads))

    def test_legacy_2001_ambiguity_and_wrong_group_never_fall_back(self):
        config = FactoryConfig(legacy_target().tenant_id, legacy_target().subscription_id,
                               "dev", "001", "project-rg", "common-rg")
        session = DiscoverySession(config)
        self.assertEqual("aifstorage2001", discover(config, session).storage_name)
        session.resources["project-rg"].append({
            "name": "other2001", "type": "Microsoft.Storage/storageAccounts",
        })
        with self.assertRaisesRegex(ValueError, "exactly one"):
            discover(config, session)
        config = selected_config(True)
        session = DiscoverySession(config)
        session.resources["common-rg"][-1]["id"] = selected_target(False).storage_id
        with self.assertRaisesRegex(ValueError, "outside"):
            discover(config, session)
        session.resources["common-rg"] = session.resources["common-rg"][:-1]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            discover(config, session)

    def test_workspace_artifact_account_is_never_selected_as_project_data(self):
        config = selected_config(False)
        session = DiscoverySession(config)
        workspace_id = session.project_id + "/providers/Microsoft.MachineLearningServices/workspaces/project-ml"
        session.resources["project-rg"].append({
            "name": "project-ml", "id": workspace_id, "type": "Microsoft.MachineLearningServices/workspaces",
        })
        original = session.arm

        def arm(method, resource_id, **kwargs):
            if resource_id == workspace_id:
                return {"properties": {"storageAccount": selected_target(False).storage_id}}
            return original(method, resource_id, **kwargs)

        with patch.object(session, "arm", side_effect=arm), self.assertRaisesRegex(ValueError, "AML workspace artifact"):
            discover(config, session)

    def test_serialized_target_backcompat_defaults_and_contradictory_metadata(self):
        old = legacy_target().to_dict()
        for key in ("storage_resource_group", "storage_container", "use_common_datalake_storage"):
            old.pop(key)
        restored = Target(**old)
        self.assertEqual(legacy_target(), restored)
        self.assertEqual("project-rg", restored.storage_summary()["resource_group"])
        for flag in (True, False):
            target = selected_target(flag)
            self.assertEqual(target, Target(**json.loads(json.dumps(target.to_dict()))))
            with self.assertRaisesRegex(ValueError, "contradicts"):
                replace(target, storage_resource_group="wrong-rg")
            with self.assertRaises(ValueError):
                replace(target, storage_name="artifact1001")
            with self.assertRaisesRegex(ValueError, "JSON boolean"):
                replace(target, use_common_datalake_storage="false")
            with self.assertRaisesRegex(ValueError, "contradicts"):
                target.resolve_container("unreviewed")

    def test_network_probe_uses_selected_blob_without_changing_foundry(self):
        for flag in (True, False):
            target = selected_target(flag)
            with patch.object(network.socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("10.1.2.3", 443))]), \
                    patch.object(network.socket, "create_connection", return_value=MagicMock()):
                checks = network.private_endpoint_checks(target)
            self.assertIn(f"{target.storage_name}.blob.core.windows.net", {row["host"] for row in checks})
            self.assertIn("foundry-account.openai.azure.com", {row["host"] for row in checks})


class StorageConsumersTests(unittest.TestCase):
    def test_uploads_and_search_documents_use_selected_container(self):
        for flag in (True, False):
            target = selected_target(flag)
            search, service = MemorySearch(), MagicMock()
            service.get_container_client.return_value.get_container_properties.return_value = {}
            with patch.object(data, "require_private_endpoint"), patch.object(data, "_managed_identity"), \
                    patch.object(data, "_ManagedIdentitySession", return_value=search), \
                    patch.object(data, "download_dataset", return_value=csv_bytes()), \
                    patch.object(data, "_blob_service", return_value=service) as blob_service, \
                    patch.object(data, "_put_blob"):
                result = data.ingest(target)
            blob_service.assert_called_once()
            self.assertEqual(f"https://{target.storage_name}.blob.core.windows.net", blob_service.call_args.args[0])
            service.get_container_client.assert_called_once_with(target.storage_container)
            service.get_container_client.return_value.create_container.assert_not_called()
            self.assertEqual(target.storage_summary(), result["storage"])
            self.assertTrue(all(f"/{target.storage_container}/" in row["document_url"] for row in search.documents.values()))

    def test_conflicting_upload_container_fails_before_external_calls(self):
        with patch.object(data, "_managed_identity") as credential, \
                self.assertRaisesRegex(ValueError, "contradicts"):
            data.ingest(selected_target(True), container="agent-factory")
        credential.assert_not_called()

    def test_selected_container_is_not_created_or_made_private_implicitly(self):
        target = selected_target(True)
        session = MagicMock()
        session.arm.side_effect = AzureError(404, "GET", target.storage_id, "missing")
        with self.assertRaisesRegex(RuntimeError, "must already exist"):
            adf._selected_container(session, target, legacy=adf.CONTAINER, owner=adf.ADF_OWNER, apply=True)
        self.assertEqual(["GET"], [call.args[0] for call in session.arm.call_args_list])
        session.arm.side_effect = None
        session.arm.return_value = {"properties": {"publicAccess": "Container"}}
        with self.assertRaisesRegex(ValueError, "forbid anonymous"):
            adf._selected_container(session, target, legacy=adf.CONTAINER, owner=adf.ADF_OWNER, apply=True)
        self.assertTrue(all(call.args[0] == "GET" for call in session.arm.call_args_list))

    def test_knowledge_requires_selected_storage_provenance_and_keeps_project_scope(self):
        for flag in (True, False):
            target = selected_target(flag)
            session = KnowledgeSession()
            session.count = 1
            original = session.request
            document_url = "https://oldaccount.blob.core.windows.net/old-container/document.md"

            def request(method, url, body=None, **kwargs):
                result = original(method, url, body, **kwargs)
                if "/docs/search?" in url and body.get("queryType") != "semantic":
                    for row in result["value"]:
                        row["document_url"] = document_url
                return result

            with patch.object(knowledge, "require_private_endpoint"), patch.object(session, "request", side_effect=request):
                with self.assertRaisesRegex(ValueError, "another storage selection"):
                    knowledge.configure_knowledge(session, target)
                self.assertFalse(any(method == "PUT" for method, *_ in session.calls))
                document_url = f"https://{target.storage_name}.blob.core.windows.net/{target.storage_container}/document.md"
                result = knowledge.configure_knowledge(session, target)
            self.assertEqual(target.storage_summary(), result["storage"])
            self.assertTrue(result["connection_id"].startswith(target.project_id))

    def test_adf_links_search_sources_and_existing_container_use_selected_scope(self):
        for flag in (True, False):
            target = selected_target(flag, "reviewed-data")
            definitions = adf.build_datafactory_definitions(target, factory_name=FACTORY)
            self.assertEqual("reviewed-data", definitions["data_source"]["container"]["name"])
            self.assertEqual(f"ResourceId={target.storage_id};", definitions["data_source"]["credentials"]["connectionString"])
            for body in definitions["datasets"].values():
                location = body["properties"]["typeProperties"]["location"]
                if location["type"] != "HttpServerLocation":
                    self.assertEqual("reviewed-data", location["container"])
            self.assertIn(f"/resourceGroups/project-rg/", definitions["factory_id"])
            rows, pin = fixture()
            session = FakeAzure(rows, pin, approved=False)
            session.arm_resources[target.storage_id] = {
                "properties": {"publicNetworkAccess": "Disabled", "allowBlobPublicAccess": False},
            }
            container_id = target.storage_id + "/blobServices/default/containers/reviewed-data"
            session.arm_resources[container_id] = {"properties": {"metadata": {"owner": "existing-owner"}}}
            with patch.object(adf, "require_private_endpoint"):
                result = adf.configure_datafactory_ingestion(session, target, factory_name=FACTORY)
            self.assertEqual(target.storage_summary(), result["storage"])
            self.assertTrue(all(item["storage_id"] == target.storage_id for item in result["private_endpoints"]))
            self.assertFalse(any(method == "PUT" and resource == container_id for method, resource, *_ in session.calls))
            self.assertFalse(any("ls_storage_lake" in resource for _, resource, *_ in session.calls))
            self.assertIn(target.storage_id, " ".join(result["prerequisites"]))

    def test_rag_inherits_profile_for_both_source_and_materialization(self):
        inherited = {key: value for key, value in binding().items()
                     if key not in {"location", "storage_account_resource_id", "container"}}
        for flag in (True, False):
            config, target = selected_config(flag), selected_target(flag)
            source = RagSource.from_binding(inherited, config, target, source_key="documents")
            self.assertEqual(target.storage_id, source.storage_id)
            self.assertEqual(target.storage_container, source.container)
            dest = rag_materialization.destination(source)
            self.assertEqual(target.storage_id, dest["storage_id"])
            self.assertEqual(target.storage_resource_group, dest["storage_resource_group"])
            self.assertEqual(target.storage_container, dest["container"])
            self.assertTrue(dest["blob_path"].endswith(".jsonl"))
            body = rag_indexing.definitions(source)
            self.assertEqual(target.storage_container, body["data_source"]["container"]["name"])
            self.assertEqual(f"ResourceId={target.storage_id};", body["data_source"]["credentials"]["connectionString"])
            copies = rag_materialization.definitions(source, FACTORY)
            for dataset in copies["datasets"].values():
                self.assertEqual(target.storage_container, dataset["properties"]["typeProperties"]["location"]["container"])
            if flag:
                scope, _, role = rag_materialization.reader_assignment(target, source, target.identity_client_id)
                self.assertEqual(f"{target.storage_id}/blobServices/default/containers/{target.storage_container}", scope)
                self.assertIn(source.blob_path, role["properties"]["condition"])
            for name, value in (("container", "wrong-container"), ("location", "project" if flag else "common"),
                                ("storage_account_resource_id", legacy_target().storage_id)):
                with self.subTest(flag=flag, field=name), self.assertRaisesRegex(ValueError, "contradicts"):
                    RagSource.from_binding({**inherited, name: value}, config, target)

    def test_rag_knowledge_array_format_and_pin_are_independent_of_storage_location(self):
        selected = {key: value for key, value in binding().items()
                    if key not in {"location", "storage_account_resource_id", "container",
                                   "manifest_path", "manifest_sha256"}}
        selected.update(format="knowledge-json-array", blob_path="kaggle-rag-v1/knowledge/items.json")
        for flag in (True, False):
            source = RagSource.from_binding(selected, selected_config(flag), selected_target(flag))
            self.assertTrue(rag_materialization.destination(source)["blob_path"].endswith(".json"))
            self.assertEqual("jsonArray", rag_indexing.definitions(source)["indexer"]["parameters"]["configuration"]["parsingMode"])
            with self.assertRaisesRegex(ValueError, "different project"):
                RagSource.from_binding({**selected, "blob_path": "project002/knowledge/items.json"},
                                       selected_config(flag), selected_target(flag))

    def test_worker_inherits_serialized_target_without_a_container_default(self):
        path = Path(__file__).resolve().parents[1] / "43-data" / "worker.py"
        spec = importlib.util.spec_from_file_location("storage_worker", path)
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        target = selected_target(True)
        source = MagicMock()
        source.read_text.return_value = json.dumps(target.to_dict())
        args = SimpleNamespace(target=source, container=None, prefix="kaggle-rag-v1", index="test-index")
        with patch.object(worker.argparse.ArgumentParser, "parse_args", return_value=args), \
                patch.object(worker, "ingest", return_value={}) as ingest, patch("builtins.print"):
            worker.main()
        ingest.assert_called_once_with(target, container=None, prefix="kaggle-rag-v1", index_name="test-index")


if __name__ == "__main__":
    unittest.main()
