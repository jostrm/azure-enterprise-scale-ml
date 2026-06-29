"""Integration: live security posture (key auth, RBAC, public endpoints). Placeholder."""
from __future__ import annotations

import unittest

from tests.domain import governance
from tests.integration.base_live import LiveAzureTestCase


class TestSecurityPosture(LiveAzureTestCase):
    def test_key_auth_disabled_on_foundry(self) -> None:
        self.skipTest("placeholder: assert governance.key_auth_disabled(<foundry>)")
        _ = governance.key_auth_disabled

    def test_managed_identity_least_privilege(self) -> None:
        self.skipTest("placeholder: assert governance.identity_roles(<pid>) subset of expected")

    def test_private_mode_no_public_endpoints(self) -> None:
        self.skipTest("placeholder: enumerate resources, assert 0 public endpoints")


if __name__ == "__main__":
    unittest.main()
