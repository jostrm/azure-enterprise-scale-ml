import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from sales_demo.configuration import load_config, make_config, readiness


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.publication = {
            "dataset": "car-sales", "version": "v1", "state": "generated", "files": [],
            "partitions": [
                {"id": source, "source": source, "site": "retail", "library": source,
                 "input_path": f"ingestion/{source}/table.txt",
                 "rows_path": f"structured/{source}/rows.jsonl",
                 "input_sha256": "a" * 64, "rows_sha256": "b" * 64,
                 "input_tokens": 14000, "row_count": 100,
                 "sale_ids_sha256": "c" * 64, "expected_chunks": 3}
                for source in ("json", "excel")
            ],
        }
        raw = json.dumps(self.publication).encode()
        (self.root / "publication.json").write_bytes(raw)
        self.config = {
            "owner": "aif48-project001-dev", "dataset": "car-sales", "version": "v1",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "subscription_id": "22222222-2222-2222-2222-222222222222",
            "project": "project001", "environment": "dev",
            "storage_account": "teststorage", "container": "explicit-container",
            "storage_resource_id": "/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/common/providers/Microsoft.Storage/storageAccounts/teststorage",
            "master_prefix": "mlops/v1/master/environments/dev/datasets/car-sales/versions/v1",
            "project_prefix": "mlops/v1/projects/project001/environments/dev/usecases/car-sales/rag/corpora/car-sales/versions/v1",
            "artifacts_root": str(self.root), "publication_file": str(self.root / "publication.json"),
            "publication_sha256": hashlib.sha256(raw).hexdigest(),
            "partition_policies": {"json": {"allowed_group_ids": []}, "excel": {"allowed_group_ids": []}},
        }

    def save(self, config=None):
        path = self.root / "config.json"
        path.write_text(json.dumps(config or self.config))
        return path

    def test_hydrates_only_integrity_not_answers(self):
        config = load_config(self.save())
        self.assertEqual([p["id"] for p in config["partitions"]], ["json", "excel"])
        self.assertNotIn("expected_total", config)
        self.assertTrue(readiness(config))

    def test_manifest_pin_and_version_are_binding(self):
        for key, value in (("publication_sha256", "d" * 64), ("version", "v2")):
            config = copy.deepcopy(self.config)
            config[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_config(self.save(config))

    def test_paths_cannot_escape_owned_dataset(self):
        for key, value in (("project_prefix", "mlops/v1/projects/project002"),
                           ("master_prefix", "mlops/v1/master/environments/dev/datasets/other/versions/v1"),
                           ("container", "../lake3")):
            config = copy.deepcopy(self.config)
            config[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_config(self.save(config))

    def test_policy_cannot_override_integrity(self):
        self.config["partition_policies"]["json"]["rows_sha256"] = "e" * 64
        with self.assertRaises(ValueError):
            load_config(self.save())

    def test_principal_identifiers_are_canonical_before_membership_matching(self):
        self.config["partition_policies"]["json"]["allowed_group_ids"] = ["AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"]
        loaded = load_config(self.save())
        self.assertEqual(loaded["partitions"][0]["allowed_group_ids"], ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"])

    def test_oracle_fields_rejected(self):
        self.publication["expected_total"] = 42
        raw = json.dumps(self.publication).encode()
        (self.root / "publication.json").write_bytes(raw)
        self.config["publication_sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError):
            load_config(self.save())

    def test_new_config_requires_existing_source_binding(self):
        from types import SimpleNamespace
        factory = SimpleNamespace(
            tenant_id=self.config["tenant_id"], subscription_id=self.config["subscription_id"],
            project_number="001", environment="dev", common_resource_group="common",
            account_name="foundry", project_name="project", search_name="search",
            model_deployment="gpt-5.1", embedding_deployment="text-embedding-3-large",
        )
        binding = {"storage_account_resource_id": self.config["storage_resource_id"],
                   "container": "explicit-container", "location": "common"}
        result = make_config(factory, binding, self.root, self.root / "factory.json", "project001-dev")
        self.assertEqual(result["container"], "explicit-container")
        self.assertEqual(result["backend_identity_client_id"], "")
        self.assertFalse(result["paths_approved"])
        del binding["container"]
        with self.assertRaises(ValueError):
            make_config(factory, binding, self.root, self.root / "factory.json", "project001-dev")


if __name__ == "__main__":
    unittest.main()
