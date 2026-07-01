"""Shared base for live integration tests: gate on LIVE_AZURE + az login.

Once-and-only-once skip logic so every integration test re-runs cleanly and
only when explicitly opted in. Subclasses implement deploy/verify; teardown is
guaranteed by app.lifecycle context managers.
"""
from __future__ import annotations

import unittest

from app.lifecycle import live_enabled
from base import cli


class LiveAzureTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not live_enabled():
            raise unittest.SkipTest("set LIVE_AZURE=1 to run live integration tests")
        if not cli.tool_available("az"):
            raise unittest.SkipTest("az CLI not available")
        if not cli.az_json(["account", "show"]):
            raise unittest.SkipTest("run 'az login' before live tests")
