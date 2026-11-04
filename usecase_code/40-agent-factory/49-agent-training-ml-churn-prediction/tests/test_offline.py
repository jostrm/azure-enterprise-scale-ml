"""Reproduce the M49 use case from scratch locally: no Azure, no downloaded or third-party data."""
import tempfile
import unittest
from pathlib import Path

from tests.support import consumer

from ml_agent.configuration import paths
from ml_agent.factory import offline_demo, write_scenario


class OfflineReproductionTests(unittest.TestCase):
    def test_synthesize_prepare_train_evaluate_and_score_from_scratch(self):
        with tempfile.TemporaryDirectory() as temporary:
            location = paths(consumer(Path(temporary)))
            write_scenario(location)
            first = offline_demo(location, Path(temporary) / "work-1")
            self.assertFalse(first["azure_written"])
            self.assertEqual(first["data"]["rows"], 7043)
            self.assertEqual(first["requests"], 50)
            self.assertTrue(first["evaluation"]["quality_gate"]["passed"])
            self.assertGreaterEqual(first["evaluation"]["metrics"]["accuracy"], 0.65)
            self.assertTrue(0 < first["predicted_churn"] < 50)
            second = offline_demo(location, Path(temporary) / "work-2")
            self.assertEqual(second["data"]["sha256"], first["data"]["sha256"])
            self.assertEqual(second["predicted_churn_request_ids"], first["predicted_churn_request_ids"])
            with self.assertRaises(ValueError):
                offline_demo(location, Path(temporary) / "work-1")


if __name__ == "__main__":
    unittest.main()
