"""Immutable candidate normalization, source lineage and oracle isolation."""
from copy import deepcopy
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shutil
import unittest

import openpyxl
import tiktoken

from sales_demo.dataset import generate
from sales_demo.configuration import load_config, make_config
from sales_demo.deployment import publication_plan
from sales_demo.graph_publication import build_candidate, candidate_version
from tests.test_graph_delta import USER, config, grant, item


ARTIFACTS = Path(__file__).resolve().parent.parent / ".test-artifacts-graph-publication"


class GraphPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ARTIFACTS / "fixture"
        generate(cls.fixture)
        cls.snapshots = {
            "json": {
                "raw": (cls.fixture / "master" / "ingestion" / "json" / "retail" /
                        "sales-json" / "car-sales-xyz.json").read_bytes(),
                "item": item("json-id", name="arbitrary.json"), "permissions": [grant()],
            },
            "excel": {
                "raw": (cls.fixture / "master" / "originals" /
                        "car-calculator-tool.xlsx").read_bytes(),
                "item": item("excel-id", name="arbitrary.xlsx"), "permissions": [grant()],
            },
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(ARTIFACTS, ignore_errors=True)

    def output(self):
        return ARTIFACTS / self._testMethodName

    def test_whole_sources_derived_version_lineage_and_identical_copies(self):
        version = candidate_version(config(), self.snapshots)
        self.assertRegex(version, r"^graph-[a-f0-9]{24}$")
        report = build_candidate(config(), self.snapshots, self.output(), version)
        self.assertEqual(set(report), {"dataset", "version", "seed", "state", "partitions", "files"})
        self.assertEqual(report["version"], version)
        self.assertNotIn("total", json.dumps(report).lower())
        self.assertFalse((self.output() / "evaluation").exists())
        encoding = tiktoken.get_encoding("cl100k_base")
        for partition in report["partitions"]:
            source = partition["id"]
            raw = (self.output() / "master" / partition["input_path"]).read_bytes()
            self.assertGreater(partition["input_tokens"], 9000)
            self.assertEqual(partition["input_tokens"],
                             len(encoding.encode(raw.decode(), disallowed_special=())))
            self.assertEqual(partition["expected_chunks"], 3)
            rows = [json.loads(line) for line in
                    (self.output() / "master" / partition["rows_path"]).read_text().splitlines()]
            self.assertEqual(partition["row_count"], len(rows))
            self.assertTrue(all(row["version"] == version for row in rows))
            self.assertEqual(partition["graph_lineage"]["source_version"], "v1")
            self.assertEqual(partition["graph_lineage"]["source_sha256"],
                             hashlib.sha256(self.snapshots[source]["raw"]).hexdigest())
            original_rows = [json.loads(line) for line in
                             (self.fixture / "master" / "structured" / source /
                              "rows.jsonl").read_text().splitlines()]
            self.assertEqual(rows, [{**row, "version": version} for row in original_rows])
        self.assertEqual((self.output() / "master" / "originals" /
                          "car-calculator-tool.xlsx").read_bytes(), self.snapshots["excel"]["raw"])
        for entry in report["files"]:
            first = (self.output() / "master" / entry["path"]).read_bytes()
            self.assertEqual(first, (self.output() / "project" / entry["path"]).read_bytes())
            self.assertEqual(hashlib.sha256(first).hexdigest(), entry["sha256"])
        self.assertEqual(len(list((self.output() / "master" / "ingestion").rglob("*.*"))), 2)

    def test_version_changes_for_content_not_permissions_or_signed_url(self):
        version = candidate_version(config(), self.snapshots)
        changed = deepcopy(self.snapshots)
        body = json.loads(changed["json"]["raw"])
        body["records"][0]["unit_price_minor"] += 100
        changed["json"]["raw"] = json.dumps(body).encode()
        self.assertNotEqual(version, candidate_version(config(), changed))
        changed = deepcopy(self.snapshots)
        changed["json"]["permissions"][0]["roles"] = ["write"]
        self.assertEqual(version, candidate_version(config(), changed))
        changed = deepcopy(self.snapshots)
        changed["json"]["item"]["@microsoft.graph.downloadUrl"] = "https://x/?sig=secret"
        self.assertEqual(version, candidate_version(config(), changed))

    def test_permission_only_change_keeps_input_hashes_and_version(self):
        first = build_candidate(config(), self.snapshots, self.output())
        changed = deepcopy(self.snapshots)
        changed["json"]["permissions"] = [grant(USER, "user")]
        second = build_candidate(config(), changed, self.output().with_name(self.output().name + "-acl"))
        self.assertEqual(first["version"], second["version"])
        self.assertEqual(first["files"], second["files"])
        for old, new in zip(first["partitions"], second["partitions"]):
            self.assertEqual(old["input_sha256"], new["input_sha256"])
            self.assertEqual(old["rows_sha256"], new["rows_sha256"])
            if old["id"] == "json":
                self.assertNotEqual(old["graph_lineage"]["permission_sha256"],
                                    new["graph_lineage"]["permission_sha256"])
                self.assertTrue(old["allowed_group_ids"])
                self.assertEqual(new["allowed_group_ids"], [])
                self.assertEqual(new["allowed_user_ids"], [USER])

    def test_candidate_reproducible_and_existing_output_immutable(self):
        first = build_candidate(config(), self.snapshots, self.output())
        second_root = self.output().with_name(self.output().name + "-second")
        second = build_candidate(config(), self.snapshots, second_root)
        self.assertEqual(first, second)
        before = (self.output() / "publication.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "empty"):
            build_candidate(config(), self.snapshots, self.output())
        self.assertEqual(before, (self.output() / "publication.json").read_bytes())

    def test_missing_deleted_foreign_or_unsupported_source_never_publishes(self):
        broken = []
        missing = deepcopy(self.snapshots)
        del missing["excel"]
        broken.append(missing)
        deleted = deepcopy(self.snapshots)
        deleted["excel"]["item"]["deleted"] = {}
        broken.append(deleted)
        foreign = deepcopy(self.snapshots)
        foreign["json"]["item"]["id"] = "outside"
        broken.append(foreign)
        denied = deepcopy(self.snapshots)
        denied["json"]["permissions"] = []
        broken.append(denied)
        for index, snapshots in enumerate(broken):
            output = self.output() / str(index)
            with self.subTest(index=index), self.assertRaises(ValueError):
                build_candidate(config(), snapshots, output)
            self.assertFalse(output.exists())

    def test_mixed_versions_wrong_schema_bad_arithmetic_duplicate_rows_and_small_inputs(self):
        original = json.loads(self.snapshots["json"]["raw"])
        variants = []
        mixed = deepcopy(original)
        mixed["version"] = "v2"
        for row in mixed["records"]:
            row["version"] = "v2"
        variants.append(mixed)
        wrong = deepcopy(original)
        wrong["dataset"] = "other"
        variants.append(wrong)
        malformed = deepcopy(original)
        malformed["records"][0]["quantity"] = True
        variants.append(malformed)
        duplicate = deepcopy(original)
        duplicate["records"].append(duplicate["records"][0])
        variants.append(duplicate)
        small = deepcopy(original)
        small["records"] = small["records"][:1]
        variants.append(small)
        extra = deepcopy(original)
        extra["records"][0]["unreviewed_field"] = "not-in-schema"
        variants.append(extra)
        for index, body in enumerate(variants):
            snapshots = deepcopy(self.snapshots)
            snapshots["json"]["raw"] = json.dumps(body).encode()
            output = self.output() / str(index)
            with self.subTest(index=index), self.assertRaises(ValueError):
                build_candidate(config(), snapshots, output)
            self.assertFalse(output.exists())

    def test_formula_workbook_fails_without_artifacts(self):
        snapshots = deepcopy(self.snapshots)
        workbook = openpyxl.load_workbook(BytesIO(snapshots["excel"]["raw"]))
        workbook["Car sales"]["D2"] = "=1+1"
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        snapshots["excel"]["raw"] = buffer.getvalue()
        with self.assertRaises(ValueError):
            build_candidate(config(), snapshots, self.output())
        self.assertFalse(self.output().exists())

    def test_caller_cannot_override_content_derived_version(self):
        with self.assertRaises(ValueError):
            build_candidate(config(), self.snapshots, self.output(), "v1")
        self.assertFalse(self.output().exists())

    def test_existing_loader_and_immutable_deployment_plan_accept_candidate(self):
        from types import SimpleNamespace
        report = build_candidate(config(), self.snapshots, self.output())
        factory = SimpleNamespace(
            tenant_id=config()["tenant_id"], subscription_id="44444444-4444-4444-4444-444444444444",
            project_number="001", environment="dev", common_resource_group="common",
            search_name="search", model_deployment="gpt-5.1", embedding_deployment="text-embedding-3-large")
        binding = {
            "storage_account_resource_id": "/subscriptions/44444444-4444-4444-4444-444444444444/"
                                           "resourceGroups/common/providers/Microsoft.Storage/storageAccounts/teststorage",
            "container": "explicit-container", "location": "common"}
        candidate = make_config(factory, binding, self.output(), self.output() / "factory.json", "test")
        candidate["partition_policies"] = {
            partition["id"]: {key: partition[key] for key in ("allowed_user_ids", "allowed_group_ids")}
            for partition in report["partitions"]}
        path = self.output() / "config.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        loaded = load_config(path)
        plan = publication_plan(loaded)
        self.assertEqual(len(plan["files"]), 5)
        self.assertEqual({entry["source"] for entry in plan["files"]}, {"json", "excel"})
        self.assertEqual(loaded["partitions"][0]["graph_lineage"]["item_id"], "json-id")


if __name__ == "__main__":
    unittest.main()
