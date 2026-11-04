import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from sales_demo.sync_publication import (
    candidate_configuration, reconcile_native, refresh_permissions, quarantine_deleted,
)


class SyncPublicationTests(unittest.TestCase):
    def test_candidate_changes_only_demo_binding_not_shared_factory_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "publication.json"
            path.write_text(json.dumps({"dataset": "car-sales", "version": "graph-abc"}))
            current = {
                "owner": "demo", "dataset": "car-sales", "version": "v1",
                "master_prefix": "master/versions/v1", "project_prefix": "project/versions/v1",
                "factory_config": "unchanged-consumer-factory.json", "partitions": [], "publication": {},
                "evaluation_mode": "operator-preview", "operator_preview_user_id": "old",
            }
            result = candidate_configuration(current, path, {"json": {}, "excel": {}}, {"scope_id": "sales"})
            self.assertEqual(result["project_prefix"], "project/versions/graph-abc")
            self.assertEqual(result["factory_config"], current["factory_config"])
            self.assertNotIn("partitions", result)
            self.assertNotIn("operator_preview_user_id", result)
            self.assertEqual(current["version"], "v1")

    def reconcile(self, content_changed, calls, *, apply=True, allow_paid=True):
        state = SimpleNamespace(candidate=lambda *args: calls.append("epoch"))
        admin = SimpleNamespace(
            configure=lambda **kw: calls.append("configure"),
            wait=lambda **kw: calls.append("wait"),
            synchronize=lambda **kw: calls.append(("sync", kw)),
        )
        with patch("sales_demo.deployment.publish", side_effect=lambda *a, **kw: calls.append("publish")), \
                patch("sales_demo.sync_publication.refresh_permissions",
                      side_effect=lambda *a, **kw: calls.append("acl")), \
                patch("sales_demo.verification.verify_publication",
                      side_effect=lambda *a, **kw: calls.append("verify") or {"state": "verified"}):
            return reconcile_native(
                {}, state=state, scope_id="sales", epoch=1, storage=object(), source_reader=object(),
                search_admin=admin, search_reader=object(), authorization=object(), export_dir=Path("evidence"),
                source_recheck=lambda: calls.append("source-recheck"), content_changed=content_changed,
                apply=apply, allow_paid=allow_paid,
            )

    def test_content_refresh_remains_closed_until_new_native_publication_is_verified(self):
        calls = []
        self.assertEqual(self.reconcile(True, calls)["state"], "verified")
        self.assertEqual(calls, ["epoch", "source-recheck", "publish", "configure", "wait",
                                 "epoch", "verify", "source-recheck", "epoch"])

    def test_permission_only_refresh_applies_acl_then_native_resync_not_content_upload(self):
        calls = []
        self.reconcile(False, calls)
        self.assertEqual(calls[2], "acl")
        self.assertEqual(calls[3], ("sync", {
            "permissions_changed": True, "content_changed": False, "apply": True,
        }))
        self.assertNotIn("publish", calls)
        self.assertNotIn("configure", calls)
        self.assertEqual(calls[-3:], ["verify", "source-recheck", "epoch"])

    def test_no_mutation_before_explicit_approval(self):
        calls = []
        for apply, paid in ((False, True), (True, False)):
            with self.assertRaises(ValueError):
                self.reconcile(True, calls, apply=apply, allow_paid=paid)
        self.assertEqual(calls, [])
        with self.assertRaises(ValueError):
            refresh_permissions({}, object())

    def test_deleted_partition_is_revoked_not_returned_as_a_partial_total(self):
        config = {"partitions": [
            {"id": "json", "allowed_user_ids": ["user"], "allowed_group_ids": []},
            {"id": "excel", "allowed_user_ids": ["user"], "allowed_group_ids": []},
        ]}
        search = Mock()
        with patch("sales_demo.sync_publication.refresh_permissions") as update:
            result = quarantine_deleted(config, ["json"], object(), search, apply=True)
            changed = update.call_args.args[0]["partitions"]
        self.assertEqual(changed[0]["allowed_user_ids"], [])
        self.assertEqual(changed[1]["allowed_user_ids"], ["user"])
        self.assertFalse(result["serving_allowed"])
        search.synchronize.assert_called_once_with(permissions_changed=True, content_changed=False, apply=True)
        self.assertEqual(config["partitions"][0]["allowed_user_ids"], ["user"])


if __name__ == "__main__":
    unittest.main()
