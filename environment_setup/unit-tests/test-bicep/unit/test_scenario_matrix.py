"""Unit tests for the scenario domain model (offline, no Azure)."""
from __future__ import annotations

import unittest

from domain.scenarios import (
    SERVICE_FLAGS,
    ByoMode,
    NetworkMode,
    all_disabled,
    all_enabled,
    matrix,
)


class TestScenarioMatrix(unittest.TestCase):
    def test_all_enabled_flags_true(self) -> None:
        ov = all_enabled().env_overrides()
        self.assertTrue(all(ov[f] == "true" for f in SERVICE_FLAGS))

    def test_all_disabled_flags_false(self) -> None:
        ov = all_disabled().env_overrides()
        self.assertTrue(all(ov[f] == "false" for f in SERVICE_FLAGS))

    def test_private_mode_closes_public_access(self) -> None:
        ov = next(s for s in matrix() if s.name == "net_private").env_overrides()
        self.assertEqual(ov["ENABLE_PUBLIC_GENAI_ACCESS"], "false")
        self.assertEqual(ov["ALLOW_PUBLIC_ACCESS_WHEN_BEHINDVNET"], "false")

    def test_public_mode_opens_public_access(self) -> None:
        ov = next(s for s in matrix() if s.name == "net_public").env_overrides()
        self.assertEqual(ov["ENABLE_PUBLIC_GENAI_ACCESS"], "true")

    def test_byo_subnets_sets_flag(self) -> None:
        ov = next(s for s in matrix() if s.name == "byo_byo_subnets").env_overrides()
        self.assertEqual(ov["BYO_SUBNETS"], "true")

    def test_matrix_covers_all_modes(self) -> None:
        names = {s.name for s in matrix()}
        for m in NetworkMode:
            self.assertIn(f"net_{m.value}", names)
        for b in ByoMode:
            self.assertIn(f"byo_{b.value}", names)


if __name__ == "__main__":
    unittest.main()
