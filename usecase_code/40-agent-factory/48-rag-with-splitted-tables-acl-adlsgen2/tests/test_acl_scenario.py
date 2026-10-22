"""Offline contracts for S09: per-folder ADLS Gen2 ACLs enforced by Storage, AI Search and a Foundry agent."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sales_demo.acl_scenario import (
    AclScenario, load_scenario, merge_acl, plan, reader_condition,
)
from sales_demo.deployment import StorageError

TEST_USER = "11111111-1111-1111-1111-111111111111"
OPERATOR = "22222222-2222-2222-2222-222222222222"
SEARCH_MI = "33333333-3333-3333-3333-333333333333"
ROOT = "s09-acl-demo/v1"


def config():
    return {
        "owner": "aif48-project001-dev", "version": "v1", "tenant_id": "44444444-4444-4444-4444-444444444444",
        "search_endpoint": "https://demo.search.windows.net",
        "storage_account": "demostorage", "container": "lake3",
        "storage_resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/demostorage",
        "search_identity_object_id": SEARCH_MI,
    }


def scenario(**changes):
    value = {"approved": True, "root": ROOT, "test_user_id": TEST_USER, "operator_user_id": OPERATOR,
             "model_deployment": "aifactory-agent-gpt-6-1-sol"}
    value.update(changes)
    return value


class ScenarioValidationTests(unittest.TestCase):
    def test_requires_explicit_approval_and_distinct_object_ids(self):
        for change in ({"approved": False}, {"test_user_id": "not-a-guid"}, {"operator_user_id": TEST_USER},
                       {"root": "../escape"}, {"root": "/absolute"}, {"model_deployment": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                load_scenario(scenario(**change))

    def test_valid_scenario_is_normalised(self):
        loaded = load_scenario(scenario(test_user_id=TEST_USER.upper()))
        self.assertEqual(loaded["test_user_id"], TEST_USER)
        self.assertEqual(loaded["root"], ROOT)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan(config(), load_scenario(scenario()))

    def test_two_sites_where_only_site_a_admits_the_test_user(self):
        folders = {item["site"]: item for item in self.plan["folders"]}
        self.assertEqual(set(folders), {"site-a-sales-team", "site-b-finance-board"})
        self.assertEqual(set(folders["site-a-sales-team"]["readers"]), {TEST_USER, OPERATOR})
        self.assertEqual(folders["site-b-finance-board"]["readers"], [OPERATOR])
        for item in self.plan["files"]:
            self.assertTrue(item["path"].startswith(ROOT + "/" + item["site"] + "/"))
            self.assertEqual(item["readers"], folders[item["site"]]["readers"])
            self.assertIn("SYNTHETIC", item["text"])
        self.assertEqual(len(self.plan["files"]), 4)

    def test_expected_access_matrix_is_derived_from_the_acl_plan(self):
        expected = self.plan["expected_access"]
        self.assertEqual(sorted(expected[TEST_USER]), sorted(
            f["title"] for f in self.plan["files"] if f["site"] == "site-a-sales-team"))
        self.assertEqual(sorted(expected[OPERATOR]), sorted(f["title"] for f in self.plan["files"]))

    def test_every_ancestor_grants_traversal_to_both_readers(self):
        self.assertEqual(self.plan["traversal"], ["", "s09-acl-demo", ROOT])
        self.assertEqual(set(self.plan["traversal_users"]), {TEST_USER, OPERATOR})

    def test_index_filters_by_acl_entries_only_without_vectors_or_rbac_scope(self):
        index = self.plan["index"]
        self.assertEqual(index["permissionFilterOption"], "enabled")
        permissions = {f["name"]: f.get("permissionFilter") for f in index["fields"] if f.get("permissionFilter")}
        self.assertEqual(permissions, {"UserIds": "userIds", "GroupIds": "groupIds"})
        self.assertFalse(any("Single" in f["type"] for f in index["fields"]))
        self.assertNotIn("vectorSearch", index)
        self.assertIn("metadata_storage_path", {f["name"] for f in index["fields"]})
        self.assertEqual(self.plan["datasource"]["indexerPermissionOptions"], ["userIds", "groupIds"])
        self.assertEqual(self.plan["datasource"]["container"], {"name": "lake3", "query": ROOT + "/"})

    def test_indexer_maps_native_permission_metadata(self):
        mappings = {m["targetFieldName"]: m["sourceFieldName"] for m in self.plan["indexer"]["fieldMappings"]}
        self.assertEqual(mappings["UserIds"], "metadata_user_ids")
        self.assertEqual(mappings["GroupIds"], "metadata_group_ids")
        self.assertEqual(self.plan["indexer"]["parameters"]["configuration"]["executionEnvironment"], "private")
        self.assertNotIn("skillsetName", self.plan["indexer"])

    def test_agent_requires_a_per_request_user_token_for_retrieval(self):
        agent = self.plan["agent"]
        self.assertEqual(agent["tool"]["headers"], {"x-ms-query-source-authorization": "{{search_auth_token}}"})
        self.assertEqual(agent["tool"]["allowed_tools"], ["knowledge_base_retrieve"])
        self.assertTrue(agent["structured_inputs"]["search_auth_token"]["required"])
        self.assertTrue(agent["tool"]["server_url"].startswith(
            "https://demo.search.windows.net/knowledgebases/" + self.plan["knowledge_base"]["name"] + "/mcp?"))

    def test_names_are_scoped_to_the_owner_and_scenario(self):
        for key in ("datasource", "index", "indexer", "knowledge_source", "knowledge_base"):
            self.assertTrue(self.plan[key]["name"].startswith("aif48-project001-dev-v1-s09-"), key)

    def test_plan_is_offline_and_deterministic(self):
        self.assertEqual(self.plan, plan(config(), load_scenario(scenario())))
        self.assertFalse(self.plan["mutations"])


class ConditionTests(unittest.TestCase):
    def test_reader_condition_allows_exact_s09_paths_and_listing_only(self):
        value = reader_condition(plan(config(), load_scenario(scenario())))
        for path in ("", "s09-acl-demo", ROOT, ROOT + "/site-b-finance-board/board-margin-forecast.md"):
            self.assertIn(f"StringEquals '{path}'", value)
        self.assertIn(f"StringEquals '{ROOT}/'", value)
        self.assertNotIn("mlops", value)
        self.assertIn("@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringEquals 'lake3'", value)


class MergeAclTests(unittest.TestCase):
    def test_adds_only_missing_traversal_and_keeps_everything_else(self):
        existing = "user::rwx,user:aaaa:--x,group::r-x,mask::r-x,other::---"
        merged = merge_acl(existing, {TEST_USER: "--x", "aaaa": "--x"})
        self.assertEqual(merged.split(","), [
            "user::rwx", "user:aaaa:--x", f"user:{TEST_USER}:--x", "group::r-x", "mask::r-x", "other::---"])

    def test_unchanged_acl_returns_none(self):
        self.assertIsNone(merge_acl(f"user::rwx,user:{TEST_USER}:--x,mask::r-x,other::---", {TEST_USER: "--x"}))

    def test_refuses_to_weaken_or_rewrite_an_existing_entry(self):
        with self.assertRaises(ValueError):
            merge_acl(f"user::rwx,user:{TEST_USER}:r-x,mask::r-x", {TEST_USER: "--x"})
        with self.assertRaises(ValueError):
            merge_acl("user::rwx,mask::r--", {TEST_USER: "--x"})


class AccessChecksTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.scenario = AclScenario(config(), load_scenario(scenario()), self.session, target=None)

    def test_storage_check_reports_allowed_and_denied_without_fallback(self):
        reader = Mock()
        reader.read.side_effect = lambda path: (_ for _ in ()).throw(StorageError(403)) \
            if "site-b" in path else b"content"
        result = self.scenario.storage_check(reader)
        statuses = {row["site"]: set() for row in result}
        for row in result:
            statuses[row["site"]].add(row["access"])
        self.assertEqual(statuses, {"site-a-sales-team": {"allowed"}, "site-b-finance-board": {"denied (403)"}})

    def test_storage_check_surfaces_unexpected_errors(self):
        reader = Mock()
        reader.read.side_effect = StorageError(500)
        with self.assertRaises(StorageError):
            self.scenario.storage_check(reader)

    def test_search_sends_the_end_user_token_as_query_source_authorization(self):
        self.session.request.return_value = {"value": [{"title": "a.md", "metadata_storage_path": "p"}],
                                             "@odata.count": 1}
        result = self.scenario.search("user-token")
        method, url, body = self.session.request.call_args.args
        self.assertEqual(method, "POST")
        self.assertIn("/indexes/" + self.scenario.plan["index"]["name"] + "/docs/search?api-version=", url)
        self.assertEqual(self.session.request.call_args.kwargs["headers"],
                         {"x-ms-query-source-authorization": "user-token"})
        self.assertEqual(result["titles"], ["a.md"])

    def test_search_without_a_user_token_is_refused_locally(self):
        with self.assertRaises(ValueError):
            self.scenario.search("")

    def test_retrieve_passes_the_user_token_to_the_knowledge_base(self):
        self.session.request.return_value = {"references": [{"sourceData": {"title": "a.md"}}], "activity": []}
        result = self.scenario.retrieve("user-token", "What can I see?")
        self.assertIn("/knowledgebases/" + self.scenario.plan["knowledge_base"]["name"] + "/retrieve",
                      self.session.request.call_args.args[1])
        self.assertEqual(self.session.request.call_args.kwargs["headers"],
                         {"x-ms-query-source-authorization": "user-token"})
        self.assertEqual(result["titles"], ["a.md"])

    def test_root_acl_is_read_with_head_on_the_container_root_only(self):
        store = self.scenario.storage(Mock(token=Mock(return_value="operator-token")))
        response = Mock()
        response.headers = {"x-ms-acl": "user::rwx,other::---"}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        store.opener = Mock(open=Mock(return_value=response))
        with patch("agent_factory.data.require_private_endpoint") as private:
            self.assertEqual(store.root_acl(), "user::rwx,other::---")
        private.assert_called_once()
        request = store.opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "HEAD")
        self.assertEqual(request.full_url,
                         "https://demostorage.dfs.core.windows.net/lake3/?action=getAccessControl")

    def test_writes_require_apply(self):
        for method in (self.scenario.publish, self.scenario.configure, self.scenario.deploy):
            with self.subTest(method=method.__name__), self.assertRaises(ValueError):
                method(apply=False)


if __name__ == "__main__":
    unittest.main()
