"""Unit tests for config integrity over the committed .env.template (offline)."""
from __future__ import annotations

import unittest

from tests.base import config
from tests.domain import governance


class TestConfigIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.env = config.env_defaults()

    def test_no_placeholder_defaults_leak(self) -> None:
        # mandatory .env defaults must be concrete, not <todo> placeholders.
        self.assertEqual(
            [], governance.placeholder_leaks(self.env, governance.MANDATORY_VARS)
        )

    def test_mandatory_vars_present(self) -> None:
        self.assertEqual([], governance.missing_mandatory(self.env))

    def test_cmk_with_short_softdelete_is_conflict(self) -> None:
        bad = {"CMK": "true", "KEYVAULT_SOFT_DELETE": "7"}
        self.assertTrue(governance.cmk_softdelete_conflict(bad))

    def test_cmk_with_long_softdelete_ok(self) -> None:
        good = {"CMK": "true", "KEYVAULT_SOFT_DELETE": "90"}
        self.assertFalse(governance.cmk_softdelete_conflict(good))

    def test_cmk_disabled_never_conflicts(self) -> None:
        self.assertFalse(governance.cmk_softdelete_conflict({"CMK": "false"}))


if __name__ == "__main__":
    unittest.main()
