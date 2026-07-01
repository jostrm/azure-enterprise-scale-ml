"""Integration: PaaS reachability (ACR, Foundry->Search/Storage). Placeholder."""
from __future__ import annotations

import unittest

from domain import paas
from integration.base_live import LiveAzureTestCase


class TestPaasValidation(LiveAzureTestCase):
    def test_acr_reachable(self) -> None:
        self.skipTest("placeholder: assert paas.acr_reachable(<acr>)")
        _ = paas.acr_reachable

    def test_foundry_reaches_search(self) -> None:
        self.skipTest("placeholder: assert paas.foundry_can_reach_search(...)")

    def test_foundry_reaches_storage(self) -> None:
        self.skipTest("placeholder: assert paas.foundry_can_reach_storage(...)")


if __name__ == "__main__":
    unittest.main()
