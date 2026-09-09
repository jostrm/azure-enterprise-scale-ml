"""Contracts for the unified AI Factory scale-set dispatcher."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DISPATCHER = ROOT / "bootstrap/ALL-create-new-aifactory-scaleset.sh"
START = ROOT / "00-start.sh"


class TestAllScaleSetDispatcher(unittest.TestCase):
    def test_routes_to_existing_ado_and_gha_launchers(self) -> None:
        script = DISPATCHER.read_text(encoding="utf-8")
        self.assertIn("AIF_ORCHESTRATOR", script)
        self.assertIn("--orchestrator", script)
        self.assertIn("ADO-create-new-aifactory-scaleset.sh", script)
        self.assertIn("GHA-create-new-aifactory-scaleset.sh", script)
        self.assertIn('exec bash "$LAUNCHER" "${FORWARD_ARGS[@]}"', script)

    def test_start_script_copies_unified_dispatcher(self) -> None:
        self.assertIn(
            "ALL-create-new-aifactory-scaleset.sh",
            START.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
