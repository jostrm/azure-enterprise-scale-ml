"""Integration: live `az bicep build`/lint on every template. Placeholder."""
from __future__ import annotations

import unittest

from domain import iac
from integration.base_live import LiveAzureTestCase


class TestIacBuild(LiveAzureTestCase):
    def test_all_templates_build(self) -> None:
        failures = [str(t) for t in iac.all_templates() if not iac.build_ok(t)]
        self.assertEqual([], failures, f"templates failed bicep build: {failures}")

    def test_all_templates_lint_clean(self) -> None:
        dirty = [str(t) for t in iac.all_templates() if not iac.lint_clean(t)]
        self.assertEqual([], dirty, f"templates with lint findings: {dirty}")

    def test_what_if_no_drift(self) -> None:
        self.skipTest("placeholder: requires deployed RG; iac.what_if_clean(rg, template, params)")


if __name__ == "__main__":
    unittest.main()
