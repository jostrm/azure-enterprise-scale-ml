"""Unit tests for security/governance posture using mocked CLI + scenarios."""
from __future__ import annotations

import unittest
from unittest import mock

from tests.domain import governance
from tests.domain.scenarios import all_disabled, matrix


class TestSecurityPostureMocked(unittest.TestCase):
    def test_private_mode_has_zero_public_endpoints(self) -> None:
        ov = next(s for s in matrix() if s.name == "net_private").env_overrides()
        self.assertEqual(0, governance.public_endpoint_count(ov))

    def test_public_mode_has_public_endpoints(self) -> None:
        ov = next(s for s in matrix() if s.name == "net_public").env_overrides()
        self.assertGreater(governance.public_endpoint_count(ov), 0)

    def test_all_disabled_has_zero_public_endpoints(self) -> None:
        self.assertEqual(0, governance.public_endpoint_count(all_disabled().env_overrides()))

    @mock.patch(
        "tests.domain.governance.cli.az_json",
        return_value={"properties": {"disableLocalAuth": True}},
    )
    def test_key_auth_disabled_true(self, _json) -> None:
        self.assertTrue(governance.key_auth_disabled("foundry1"))

    @mock.patch(
        "tests.domain.governance.cli.az_json",
        return_value={"properties": {"disableLocalAuth": False}},
    )
    def test_key_auth_disabled_false(self, _json) -> None:
        self.assertFalse(governance.key_auth_disabled("foundry1"))


if __name__ == "__main__":
    unittest.main()
