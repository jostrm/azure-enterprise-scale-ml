"""Opt-in live checks; they read Azure state only and never create, train or delete anything."""
import json
import os
import unittest
from pathlib import Path

from tests import support  # noqa: F401  (puts the template on sys.path)

from ml_agent.configuration import load_config


@unittest.skipUnless(os.environ.get("AIF49_LIVE") == "1" and os.environ.get("AIF49_CONFIG"),
                     "Set AIF49_LIVE=1 and AIF49_CONFIG=<consumer config.json> for read-only live checks")
class LivePreflightTests(unittest.TestCase):
    def test_private_connectivity_and_prerequisites(self):
        from ml_agent.connectivity import preflight

        result = preflight(load_config(Path(os.environ["AIF49_CONFIG"])))
        self.assertTrue(result["ready"], json.dumps(result.get("gaps"), indent=2))


if __name__ == "__main__":
    unittest.main()
