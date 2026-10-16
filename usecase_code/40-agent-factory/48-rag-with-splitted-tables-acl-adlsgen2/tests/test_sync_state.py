import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from sales_demo.sync_state import SyncState, SyncConflict, guard_snapshot, assert_guard_unchanged
from sales_demo.identity import SalesUnavailable
from sales_demo.runtime import config_fingerprint


class SyncStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "sync.sqlite"
        self.store = SyncState(self.db)
        self.store.initialize("sales", "tenant", "drive")
        self.config = {
            "owner": "owner", "dataset": "car-sales", "version": "v1", "tenant_id": "tenant",
            "graph_sync": {"database": str(self.db), "scope_id": "sales", "max_age_seconds": 900},
        }

    def proof(self):
        return {
            "state": "verified", "owner": "owner", "dataset": "car-sales", "version": "v1",
            "config_sha256": config_fingerprint(self.config), "structured_coverage_verified": True,
            "claims": {"real_text_split": True, "exact_three_chunks_per_table": True,
                       "all_source_bytes_preserved": True},
            "service_evidence": {
                key: {"verified": True, "ingestion_succeeded": True, "chunk_count": 3}
                for key in ("json", "excel")
            },
        }

    def ready(self):
        cycle = self.store.begin("sales")
        self.store.stage("sales", cycle["epoch"], {
            "delta_link": "opaque-cursor", "inventory": {"item": {"id": "item"}},
            "plan": {"changes": []},
        })
        self.store.complete("sales", cycle["epoch"], self.config, self.proof())
        return cycle

    def test_initial_and_interrupted_rounds_are_closed(self):
        with self.assertRaises(SalesUnavailable):
            guard_snapshot(self.config)
        cycle = self.store.begin("sales")
        self.store.stage("sales", cycle["epoch"], {"delta_link": "next", "inventory": {}, "plan": {}})
        with self.assertRaises(SalesUnavailable):
            guard_snapshot(self.config)
        self.assertIsNone(self.store.scope("sales")["cursor"])

    def test_cursor_commits_only_after_verified_publication(self):
        self.ready()
        self.assertEqual(self.store.scope("sales")["cursor"], "opaque-cursor")
        self.assertIsNotNone(guard_snapshot(self.config))

    def test_new_notification_prevents_old_round_publication(self):
        cycle = self.ready()
        token = guard_snapshot(self.config)
        self.store.signal_many([("sales", "graph-notification")])
        with self.assertRaises(SalesUnavailable):
            assert_guard_unchanged(self.config, token)
        with self.assertRaises(SyncConflict):
            self.store.complete("sales", cycle["epoch"], self.config, self.proof())

    def test_older_worker_cannot_replace_new_candidate(self):
        first = self.store.begin("sales")
        second = self.store.begin("sales")
        with self.assertRaises(SyncConflict):
            self.store.stage("sales", first["epoch"], {"delta_link": "old", "inventory": {}, "plan": {}})
        self.store.stage("sales", second["epoch"], {"delta_link": "new", "inventory": {}, "plan": {}})

    def test_incomplete_evidence_cannot_open_guard(self):
        cycle = self.store.begin("sales")
        self.store.stage("sales", cycle["epoch"], {"delta_link": "new", "inventory": {}, "plan": {}})
        proof = self.proof()
        proof["structured_coverage_verified"] = False
        with self.assertRaises(ValueError):
            self.store.complete("sales", cycle["epoch"], self.config, proof)
        with self.assertRaises(SalesUnavailable):
            guard_snapshot(self.config)

    def test_expired_freshness_is_not_cached_success(self):
        self.ready()
        with self.assertRaises(SalesUnavailable):
            guard_snapshot(self.config, now=self.store.scope("sales")["reconciled_at"] + 901)

    def test_subscription_secret_is_hashed_and_queue_signal_is_durable(self):
        self.ready()
        self.store.register_subscription("sub", "sales", "tenant", "/drives/drive/root", "secret", 9999999999)
        recorded = self.store.subscription("sub")
        self.assertEqual(recorded["client_state_sha256"], hashlib.sha256(b"secret").hexdigest())
        self.assertNotIn("client_state", recorded)
        self.store.signal_many([("sales", "notification"), ("sales", "notification")])
        self.assertEqual(self.store.scope("sales")["state"], "pending")
        reopened = SyncState(self.db)
        self.assertEqual(reopened.scope("sales")["state"], "pending")

    def test_batch_with_unknown_scope_does_not_partially_invalidate(self):
        self.ready()
        before = self.store.scope("sales")["epoch"]
        with self.assertRaises(ValueError):
            self.store.signal_many([("sales", "notification"), ("unknown", "notification")])
        self.assertEqual(self.store.scope("sales")["epoch"], before)

    def test_missing_database_is_fail_closed_not_auto_created(self):
        self.config["graph_sync"]["database"] = str(self.db.parent / "missing.sqlite")
        with self.assertRaises(SalesUnavailable):
            guard_snapshot(self.config)
        self.assertFalse((self.db.parent / "missing.sqlite").exists())

    def test_changed_publication_binding_stays_closed(self):
        self.ready()
        self.config["version"] = "v2"
        with self.assertRaises(SalesUnavailable):
            guard_snapshot(self.config)

    def test_no_graph_extension_preserves_existing_runtime(self):
        self.assertIsNone(guard_snapshot({"tenant_id": "tenant"}))
        assert_guard_unchanged({"tenant_id": "tenant"}, None)

    def test_lifecycle_hold_survives_delta_until_subscription_repair(self):
        self.store.register_subscription("sub", "sales", "tenant", "/drives/drive/root", "secret", 9999999999)
        self.store.signal_many([("sales", "graph-reauthorization-required")])
        cycle = self.store.begin("sales")
        self.store.stage("sales", cycle["epoch"], {"delta_link": "cursor", "inventory": {}, "plan": {}})
        with self.assertRaises(SyncConflict):
            self.store.complete("sales", cycle["epoch"], self.config, self.proof())
        self.store.update_subscription_expiry("sub", 9999999999)
        self.store.complete("sales", cycle["epoch"], self.config, self.proof())
        self.assertIsNotNone(guard_snapshot(self.config))

    def test_new_security_subscription_retires_old_expiry_without_false_readiness(self):
        self.store.register_subscription("old", "sales", "tenant", "/drives/drive/root", "old-secret", 9999999999)
        self.store.register_subscription("new", "sales", "tenant", "/drives/drive/root", "new-secret", 9999999999)
        self.assertEqual(self.store.subscription("old")["active"], 0)
        with self.assertRaises(ValueError):
            self.store.update_subscription_expiry("old", 9999999999)
        self.assertEqual(self.store.scope("sales")["state"], "pending")

    def test_renewal_cannot_clear_an_uncertain_create_attempt(self):
        self.store.register_subscription("old", "sales", "tenant", "/drives/drive/root", "secret", 9999999999)
        self.store.mark_subscription_attempt("sales", "create")
        self.store.update_subscription_expiry("old", 9999999999)
        with self.assertRaises(SyncConflict):
            self.store.mark_subscription_attempt("sales", "create")

    def test_apply_lock_excludes_other_workers_but_does_not_block_notifications(self):
        with self.store.apply_lock("sales"):
            other = SyncState(self.db)
            with self.assertRaises(SyncConflict):
                with other.apply_lock("sales"):
                    self.fail("A second writer entered the external-write phase.")
            other.signal_many([("sales", "graph-notification")])
            self.assertEqual(other.scope("sales")["reason"], "graph-notification")
        with self.store.apply_lock("sales"):
            self.assertEqual(self.store.scope("sales")["state"], "pending")

    def test_partial_write_marker_survives_notifications_and_requires_repair(self):
        cycle = self.store.begin("sales")
        self.store.mark_repair_required("sales", cycle["epoch"])
        self.store.signal_many([("sales", "graph-notification")])
        self.assertTrue(self.store.begin("sales")["repair_required"])

    def test_recreation_between_validation_and_enqueue_cannot_apply_old_lifecycle(self):
        self.store.register_subscription("old", "sales", "tenant", "/drives/drive/root", "secret", 9999999999)
        record = self.store.subscription("old")
        event = {
            "subscription_id": "old", "scope_id": "sales", "client_state_sha256": record["client_state_sha256"],
            "expires_at": record["expires_at"], "priority": 3, "reason": "graph-reauthorization-required",
        }
        self.store.register_subscription("new", "sales", "tenant", "/drives/drive/root", "new-secret", 9999999999)
        before = self.store.scope("sales")["epoch"]
        self.store.signal_notifications([event])
        self.assertEqual(self.store.scope("sales")["epoch"], before)
        self.assertFalse(self.store.scope("sales")["lifecycle_hold"])


if __name__ == "__main__":
    unittest.main()
