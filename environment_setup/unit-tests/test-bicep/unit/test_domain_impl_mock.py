"""Unit tests for newly implemented domain functions via mocked CLI seam.

Covers iac.what_if_clean, governance.identity_roles, paas foundry
connections, and idempotent factory/project cleanup. All offline.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from tests.base.cli import CmdResult
from tests.domain import factory, governance, iac, paas, project


class TestWhatIfClean(unittest.TestCase):
    @mock.patch("tests.domain.iac.cli.az", return_value=CmdResult(0, '{"changes":[{"changeType":"NoChange"}]}', ""))
    def test_no_drift(self, _az) -> None:
        self.assertTrue(iac.what_if_clean("rg", Path("t.bicep"), {"a": "1"}))

    @mock.patch("tests.domain.iac.cli.az", return_value=CmdResult(0, '{"changes":[{"changeType":"Modify"}]}', ""))
    def test_drift_detected(self, _az) -> None:
        self.assertFalse(iac.what_if_clean("rg", Path("t.bicep"), {}))


class TestIdentityRoles(unittest.TestCase):
    @mock.patch("tests.domain.governance.cli.az_json", return_value=[{"roleDefinitionName": "Reader"}, {"roleDefinitionName": "Reader"}])
    def test_dedup_sorted(self, _json) -> None:
        self.assertEqual(["Reader"], governance.identity_roles("pid"))

    @mock.patch("tests.domain.governance.cli.az_json", return_value=None)
    def test_empty(self, _json) -> None:
        self.assertEqual([], governance.identity_roles("pid"))


class TestFoundryConnections(unittest.TestCase):
    @mock.patch("tests.domain.paas.cli.resolves_to_private_ip", return_value=True)
    @mock.patch("tests.domain.paas.cli.az_json", return_value=[{"properties": {"target": "srch1.search.windows.net"}}])
    def test_reaches_search(self, _json, _dns) -> None:
        self.assertTrue(paas.foundry_can_reach_search("f1", "srch1"))

    @mock.patch("tests.domain.paas.cli.resolves_to_private_ip", return_value=True)
    @mock.patch("tests.domain.paas.cli.az_json", return_value=[])
    def test_no_connection(self, _json, _dns) -> None:
        self.assertFalse(paas.foundry_can_reach_search("f1", "srch1"))


class TestCleanupIdempotent(unittest.TestCase):
    @mock.patch("tests.domain.factory.cli.az_json", return_value=None)
    def test_common_already_gone(self, _json) -> None:
        c = factory.DeployedCommon("rg", "vnet", "acr", "eus2")
        self.assertTrue(factory.cleanup_common(c))

    @mock.patch("tests.domain.project.cli.az", return_value=CmdResult(0, "", ""))
    @mock.patch("tests.domain.project.cli.az_json", return_value={"name": "rg"})
    def test_project_deletes(self, _json, _az) -> None:
        self.assertTrue(project.cleanup_project(project.DeployedProject("rg", "001")))


if __name__ == "__main__":
    unittest.main()
