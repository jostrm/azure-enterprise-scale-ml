"""Integration: deploy 1 project with ALL enableX=true after common. Placeholder."""
from __future__ import annotations

import unittest

from domain.scenarios import all_enabled
from integration.base_live import LiveAzureTestCase


class TestProjectAllEnabled(LiveAzureTestCase):
    def test_project_all_services_enabled(self) -> None:
        self.skipTest("placeholder: implement deploy_project for all_enabled()")
        _ = all_enabled


if __name__ == "__main__":
    unittest.main()
