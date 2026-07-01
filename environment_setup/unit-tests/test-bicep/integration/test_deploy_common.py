"""Integration: deploy the AI Factory common part, verify, cleanup. Placeholder."""
from __future__ import annotations

import unittest

from base.config import env_defaults
from domain.scenarios import Scenario
from integration.base_live import LiveAzureTestCase


class TestDeployCommon(LiveAzureTestCase):
    def test_deploy_and_cleanup_common(self) -> None:
        self.skipTest("placeholder: implement deploy_common + cleanup_common")
        # from app.lifecycle import common_environment
        # with common_environment(Scenario("common"), env_defaults()) as c:
        #     self.assertTrue(c.resource_group)
        _ = env_defaults, Scenario


if __name__ == "__main__":
    unittest.main()
