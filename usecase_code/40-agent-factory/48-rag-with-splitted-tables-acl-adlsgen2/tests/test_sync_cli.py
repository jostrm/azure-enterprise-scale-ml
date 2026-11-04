"""Offline real-file delta/reconciliation scenarios; no cloud or live-ACL claims."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from sales_demo.configuration import digest, load_config
from sales_demo.dataset import generate
from sales_demo.graph_delta import project_permissions, UnsupportedPermissions
from sales_demo.runtime import config_fingerprint
from sales_demo.sync_state import SyncState, SyncConflict
from test_graph_delta import config as graph_configuration, inventory, grant, USER

spec = importlib.util.spec_from_file_location("sales_sync_entry", Path(__file__).resolve().parents[1] / "sync.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class SyncCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        publication = generate(self.data)
        self.graph = {
            **graph_configuration(), "database": str(self.root / "sync.sqlite"),
            "staging_directory": str(self.root / "staged"), "max_age_seconds": 900,
        }
        self.state = SyncState(Path(self.graph["database"]))
        self.state.initialize(self.graph["scope_id"], self.graph["tenant_id"], self.graph["drive_id"])
        self.current = {
            "owner": "aif48-project001-dev", "dataset": "car-sales", "version": "v1",
            "project": "project001", "environment": "dev", "tenant_id": self.graph["tenant_id"],
            "subscription_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "container": "lake3",
            "storage_account": "demostorage",
            "storage_resource_id": "/subscriptions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/resourceGroups/common/providers/Microsoft.Storage/storageAccounts/demostorage",
            "master_prefix": "mlops/v1/master/environments/dev/datasets/car-sales/versions/v1",
            "project_prefix": "mlops/v1/projects/project001/environments/dev/usecases/car-sales/rag/corpora/car-sales/versions/v1",
            "artifacts_root": str(self.data), "publication_file": str(self.data / "publication.json"),
            "publication_sha256": digest((self.data / "publication.json").read_bytes()),
            "publication": publication, "partitions": publication["partitions"],
            "partition_policies": {key: {"allowed_user_ids": [USER], "allowed_group_ids": []}
                                   for key in ("json", "excel")},
            "graph_sync": entry.guard(self.graph),
        }
        self.items = inventory()
        self.snapshots = {}
        for key, item_id, path in (
            ("json", "json-id", "ingestion/json/retail/sales-json/car-sales-xyz.json"),
            ("excel", "excel-id", "originals/car-calculator-tool.xlsx"),
        ):
            policy = project_permissions(self.graph, [grant()])
            self.snapshots[key] = {
                "raw": (self.data / "master" / path).read_bytes(), "item": self.items[item_id],
                "permissions": [grant()], "permission_sha256": policy["permission_sha256"], "policy": policy,
            }
        self.round = {"items": list(self.items.values()), "full_resync": True,
                      "delta_link": "https://graph.microsoft.com/v1.0/drives/drive-1/root/delta?token=one"}
        self.client = SimpleNamespace(fetch=lambda cursor: deepcopy(self.round),
                                      inspect_selected=lambda items: deepcopy(self.snapshots))

    def stage(self):
        return entry.stage_round(self.graph, self.current, self.state, self.client)

    def accept_fake_service_proof(self, report):
        candidate = self.state.candidate(self.graph["scope_id"], report["epoch"])
        self.current = load_config(Path(candidate["candidate_config"]))
        proof = {
            "state": "verified", **{k: self.current[k] for k in ("owner", "dataset", "version")},
            "config_sha256": config_fingerprint(self.current), "structured_coverage_verified": True,
            "claims": {"real_text_split": True, "exact_three_chunks_per_table": True,
                       "all_source_bytes_preserved": True},
            "service_evidence": {key: {"verified": True, "ingestion_succeeded": True, "chunk_count": 3}
                                 for key in ("json", "excel")},
        }
        self.state.complete(self.graph["scope_id"], report["epoch"], self.current, proof)

    def test_content_then_permission_only_then_no_change_preserves_immutable_inputs(self):
        first = self.stage()
        self.assertEqual(first["action"], "content")
        self.assertIsNone(self.state.scope(self.graph["scope_id"])["cursor"])
        self.accept_fake_service_proof(first)
        before = {p["id"]: p["input_sha256"] for p in self.current["partitions"]}
        self.round["items"] = []
        self.round["full_resync"] = False
        self.round["delta_link"] += "-next"
        policy = project_permissions(self.graph, [grant(USER, "user")])
        self.snapshots["json"].update(permissions=[grant(USER, "user")], policy=policy,
                                      permission_sha256=policy["permission_sha256"])
        second = self.stage()
        self.assertEqual(second["action"], "permissions")
        self.accept_fake_service_proof(second)
        self.assertEqual({p["id"]: p["input_sha256"] for p in self.current["partitions"]}, before)
        current_hash = config_fingerprint(self.current)
        third = self.stage()
        self.assertEqual(third["action"], "recheck")
        candidate = self.state.candidate(self.graph["scope_id"], third["epoch"])
        self.assertEqual(candidate["candidate_config_sha256"], current_hash)

    def test_source_deletion_stages_quarantine_not_a_partial_dataset(self):
        self.round["items"] = [{"id": "root", "root": {}, "folder": {}}]
        report = self.stage()
        candidate = self.state.candidate(self.graph["scope_id"], report["epoch"])
        self.assertEqual(report["action"], "quarantine")
        self.assertEqual(set(candidate["deleted_partitions"]), {"json", "excel"})
        self.assertFalse(report["serving_allowed"])
        self.assertNotIn("candidate_config", candidate)

    def test_unrepresentable_permissions_quarantine_without_guessing_public_access(self):
        def unsupported(items):
            raise UnsupportedPermissions("Unsupported source link.")
        self.client.inspect_selected = unsupported
        report = self.stage()
        candidate = self.state.candidate(self.graph["scope_id"], report["epoch"])
        self.assertEqual(candidate["quarantine_reason"], "unsupported-source-permissions")
        self.assertIsNone(self.state.scope(self.graph["scope_id"])["cursor"])

    def test_notification_during_delta_never_commits_old_candidate(self):
        def concurrent(cursor):
            self.state.signal_many([(self.graph["scope_id"], "graph-notification")])
            return self.round
        self.client.fetch = concurrent
        with self.assertRaises(SyncConflict):
            self.stage()
        self.assertIsNone(self.state.scope(self.graph["scope_id"])["cursor"])

    def test_reconcile_rejects_unapproved_candidate_before_mutations(self):
        report = self.stage()
        arguments = SimpleNamespace(epoch=report["epoch"], approved_candidate="wrong", apply=True, allow_paid=True)
        with self.assertRaises(ValueError):
            entry.reconcile(self.graph, self.current, self.root / "active.json", self.state,
                            self.client, arguments, object())

    def test_restored_source_after_quarantine_forces_acl_repair(self):
        first = self.stage()
        self.accept_fake_service_proof(first)
        self.state.mark_repair_required(self.graph["scope_id"], first["epoch"])
        result = self.stage()
        self.assertEqual(result["action"], "permissions")

    def test_force_renew_is_explicitly_available_for_lifecycle_repair(self):
        args = entry.parser().parse_args([
            "renew", "--sync-config", "graph.json", "--config", "demo.json",
            "--subscription-id", "known-subscription", "--force-renew", "--apply",
        ])
        self.assertTrue(args.force_renew)


if __name__ == "__main__":
    unittest.main()
