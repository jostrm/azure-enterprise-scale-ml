"""Integration: deploy 1 project with ALL enableX=false. Placeholder."""
from __future__ import annotations

import unittest

from domain.scenarios import all_disabled
from integration.base_live import LiveAzureTestCase


class TestProjectAllDisabled(LiveAzureTestCase):
    def test_project_all_services_disabled(self) -> None:
        self.skipTest("placeholder: implement deploy_project for all_disabled()")
        _ = all_disabled


if __name__ == "__main__":
    unittest.main()
