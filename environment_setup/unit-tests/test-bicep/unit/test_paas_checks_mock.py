"""Unit tests for PaaS reachability checks using a mocked CLI seam.

Demonstrates the mocking strategy: patch base.cli so domain.paas logic is
tested offline without az/nslookup. Live equivalents live in integration/.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests.domain import paas


class TestPaasChecksMocked(unittest.TestCase):
    @mock.patch("tests.domain.paas.cli.resolves_to_private_ip", return_value=True)
    @mock.patch("tests.domain.paas.cli.az_json", return_value={"name": "acr1"})
    def test_acr_reachable_when_private_and_show_ok(self, _json, _dns) -> None:
        self.assertTrue(paas.acr_reachable("acr1"))

    @mock.patch("tests.domain.paas.cli.resolves_to_private_ip", return_value=False)
    @mock.patch("tests.domain.paas.cli.az_json", return_value=None)
    def test_acr_unreachable_when_public(self, _json, _dns) -> None:
        self.assertFalse(paas.acr_reachable("acr1"))

    @mock.patch("tests.domain.paas.cli.resolves_to_private_ip", return_value=True)
    def test_search_private_endpoint(self, _dns) -> None:
        self.assertTrue(paas.search_reachable("srch1"))

    @mock.patch("tests.domain.paas.cli.resolves_to_private_ip", return_value=True)
    def test_storage_private_endpoint(self, _dns) -> None:
        self.assertTrue(paas.storage_reachable("stg1"))


if __name__ == "__main__":
    unittest.main()
