"""Integration: BYO vNet / BYO subnets / BYO ASE v3 modes. Placeholder."""
from __future__ import annotations

import unittest

from domain.scenarios import ByoMode
from integration.base_live import LiveAzureTestCase


class TestByoModes(LiveAzureTestCase):
    def test_byo_vnet_only(self) -> None:
        self.skipTest("placeholder: pre-create vNet, deploy, assert subnets created")
        _ = ByoMode.VNET_ONLY

    def test_byo_subnets(self) -> None:
        self.skipTest("placeholder: pre-create vNet+subnets, deploy, assert reuse")

    def test_byo_ase(self) -> None:
        self.skipTest("placeholder: pre-create ASE v3, deploy, assert reuse")


if __name__ == "__main__":
    unittest.main()
