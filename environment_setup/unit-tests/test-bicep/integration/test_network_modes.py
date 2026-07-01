"""Integration: private / hybrid / public network modes. Placeholder."""
from __future__ import annotations

import unittest

from tests.domain.scenarios import NetworkMode, Scenario
from tests.integration.base_live import LiveAzureTestCase


class TestNetworkModes(LiveAzureTestCase):
    def test_private(self) -> None:
        self.skipTest("placeholder: deploy + assert private endpoints (nslookup)")
        _ = Scenario, NetworkMode.PRIVATE

    def test_hybrid(self) -> None:
        self.skipTest("placeholder: deploy + assert hybrid access")

    def test_public(self) -> None:
        self.skipTest("placeholder: deploy + assert public access")


if __name__ == "__main__":
    unittest.main()
