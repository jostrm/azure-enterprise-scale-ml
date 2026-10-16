"""Explicitly approved real Graph source reads; never creates a subscription."""
import importlib.util
import os
from pathlib import Path
import unittest


@unittest.skipUnless(
    os.environ.get("AIF48_GRAPH_SERVICE_TESTS") == "1"
    and os.environ.get("AIF48_GRAPH_SOURCE_READ_APPROVED") == "1",
    "Real Graph source reads require explicit scope-bound approval.",
)
class GraphSourceServiceTests(unittest.TestCase):
    def test_business_delta_and_complete_selected_permission_reads(self):
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("graph_service_entry", root / "sync.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        graph = module.load_sync(Path(os.environ["AIF48_GRAPH_SYNC_CONFIG"]))
        demo = module.load_config(Path(os.environ["AIF48_CONFIG"]))
        self.assertEqual(graph["tenant_id"], demo["tenant_id"])
        session, _ = module.common.operator(demo)
        client = module.GraphDeltaClient(graph, module.BinaryGraphTransport(graph, session))
        round = client.fetch()
        self.assertTrue(round["full_resync"])
        inventory = module.reconcile_inventory({}, round)
        snapshots = client.inspect_selected(inventory)
        self.assertEqual(set(snapshots), {"json", "excel"})
        self.assertTrue(all(value["raw"] and value["permission_sha256"] for value in snapshots.values()))


if __name__ == "__main__":
    unittest.main()
