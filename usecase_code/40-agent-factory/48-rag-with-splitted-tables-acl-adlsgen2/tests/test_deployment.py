import hashlib
from pathlib import Path
import tempfile
import unittest

from sales_demo.deployment import publication_plan, publish, broad_data_roles, missing_private_links, role_allows


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = "ingestion/json/site/library/table.json"
        for prefix in ("master", "project"):
            file = self.root / prefix / path
            file.parent.mkdir(parents=True)
            file.write_bytes(b"synthetic")
        self.config = {
            "artifacts_root": str(self.root), "master_prefix": "master/car-sales/v1",
            "project_prefix": "project/car-sales/v1", "owner": "aif48-test",
            "dataset": "car-sales", "version": "v1", "container": "lake3",
            "partitions": [{"id": "json", "allowed_group_ids": ["reader"], "allowed_user_ids": []}],
            "publication": {"files": [{"path": path, "sha256": hashlib.sha256(b"synthetic").hexdigest()}]},
        }

    def test_master_copy_integrity_and_excluded_assets(self):
        self.config["publication"]["files"].append({"path": "images/car.png", "sha256": "0" * 64})
        plan = publication_plan(self.config)
        self.assertEqual(len(plan["files"]), 1)
        self.assertFalse(plan["mutations"])
        self.assertIn("images/car.png", plan["excluded"])

    def test_corrupt_project_copy_fails_before_cloud(self):
        file = next((self.root / "project").rglob("*.json"))
        file.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            publication_plan(self.config)

    def test_manifest_cannot_publish_oracles(self):
        self.config["publication"]["files"].append({"path": "evaluation/expected.json", "sha256": "0" * 64})
        with self.assertRaises(ValueError):
            publication_plan(self.config)

    def test_writes_require_apply(self):
        with self.assertRaises(ValueError):
            publish(self.config, object(), apply=False)

    def test_broad_rbac_accounts_for_custom_wildcards_and_conditions(self):
        definitions = {
            "reader": {"permissions": [{"dataActions": ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"],
                                       "notDataActions": []}]},
            "custom": {"permissions": [{"dataActions": ["*"], "notDataActions": []}]},
            "arm-only": {"permissions": [{"actions": ["*"], "dataActions": []}]},
        }
        assignments = [
            {"properties": {"principalId": principal, "roleDefinitionId": role, "scope": "/account",
                            "condition": condition}}
            for principal, role, condition in (
                ("user", "reader", None), ("group", "custom", "some condition"),
                ("user", "arm-only", None), ("search-mi", "reader", None))
        ]
        result = broad_data_roles(assignments, definitions, {"user", "group"})
        self.assertEqual(len(result), 2)
        self.assertTrue(any(item["requires_condition_review"] for item in result))

    def test_private_links_are_resource_and_subresource_specific(self):
        links = [{"properties": {
            "privateLinkResourceId": "/storage", "groupId": "blob",
            "status": "Approved", "provisioningState": "Succeeded",
        }}]
        missing = missing_private_links(links, "/storage", "/foundry")
        self.assertEqual({item["groupId"] for item in missing}, {"dfs", "openai_account"})
        links[0]["properties"]["status"] = "Pending"
        self.assertEqual(len(missing_private_links(links, "/storage", "/foundry")), 3)

    def test_readonly_indexer_status_permission_is_distinct_from_query_data(self):
        assignments = [{"properties": {"principalId": "backend", "roleDefinitionId": "reader"}}]
        roles = {"reader": {"permissions": [{"actions": ["*/read"], "dataActions": []}]}}
        self.assertTrue(role_allows(assignments, roles, "backend", "actions",
                                    "Microsoft.Search/searchServices/indexers/read"))
        self.assertFalse(role_allows(assignments, roles, "backend", "dataActions",
                                     "Microsoft.Search/searchServices/indexes/documents/read"))


if __name__ == "__main__":
    unittest.main()
