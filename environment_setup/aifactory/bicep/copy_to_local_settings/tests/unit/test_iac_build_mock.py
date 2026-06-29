"""Unit tests for IaC build/lint via a mocked CLI seam (offline, cheap).

Verifies the orchestration in domain.iac without invoking az/bicep: discovers
real templates, then asserts build/lint pass when the CLI returns ok and fail
when it returns errors. Live `az bicep build` runs in integration/.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from tests.base.cli import CmdResult
from tests.domain import iac


class TestIacBuildMocked(unittest.TestCase):
    def test_discovers_genai_and_common_templates(self) -> None:
        self.assertTrue(iac.all_templates(), "expected bicep templates to exist")

    @mock.patch("tests.domain.iac.cli.az", return_value=CmdResult(0, "{}", ""))
    def test_build_ok_when_compiler_succeeds(self, _az) -> None:
        self.assertTrue(iac.build_ok(Path("any.bicep")))

    @mock.patch(
        "tests.domain.iac.cli.az", return_value=CmdResult(1, "", "Error BCP000")
    )
    def test_build_fails_on_error(self, _az) -> None:
        self.assertFalse(iac.build_ok(Path("any.bicep")))

    @mock.patch("tests.domain.iac.cli.az", return_value=CmdResult(0, "", ""))
    def test_lint_clean_when_no_stderr(self, _az) -> None:
        self.assertTrue(iac.lint_clean(Path("any.bicep")))

    @mock.patch("tests.domain.iac.cli.az", return_value=CmdResult(0, "", "warn"))
    def test_lint_dirty_when_warnings(self, _az) -> None:
        self.assertFalse(iac.lint_clean(Path("any.bicep")))

    @mock.patch("tests.domain.iac.cli.az", return_value=CmdResult(0, "{}", ""))
    def test_bicepparam_parses(self, _az) -> None:
        self.assertTrue(iac.bicepparam_parses(Path("p.bicepparam")))


if __name__ == "__main__":
    unittest.main()
