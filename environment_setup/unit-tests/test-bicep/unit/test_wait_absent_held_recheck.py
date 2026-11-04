"""Waiting for a deleted resource proves the held claim once a minute, not on every 5-second poll.

aif-145 Scenario 5 (2026-11-04, run 0d29bd55): the scale-set deletion's single-writer claim lives on a GitHub state
branch whose state.json is 10.9 MB. wait_absent re-read it (four GitHub GETs) on every poll of the group DELETE and
again for each of the group's 833 children, so the worker spent the account's 5,000 GitHub requests per hour and its
next state write failed github 403 after every resource was gone. The wait is read-only; every DELETE still re-proves
the claim first, and a lost claim still stops the wait within a minute.
"""

import types
from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import fl

GROUP = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/aif-145-esml-common-sdc-dev-002"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def absent_after(polls):
    cloud = types.SimpleNamespace(calls=0)

    def arm(method, resource_id, api_version, allowed=(200,)):
        cloud.calls += 1
        return (404 if cloud.calls >= polls else 200), {}, {}
    cloud.arm = arm
    return cloud


def test_a_long_group_delete_proves_the_claim_once_a_minute():
    clock, locks = Clock(), types.SimpleNamespace(assert_held=Mock())
    fl.wait_absent(absent_after(721), locks, GROUP, fl.RG_API, clock.sleep, clock=clock)  # one hour of 5-s polls
    assert clock.now - 1000.0 == 3600
    assert 60 <= locks.assert_held.call_count <= 61


def test_confirming_the_children_of_a_deleted_group_reads_the_claim_once():
    clock, locks = Clock(), types.SimpleNamespace(assert_held=Mock())
    for index in range(833):
        fl.wait_absent(absent_after(1), locks, GROUP + "/providers/microsoft.network/nics/n%d" % index,
                       "2024-05-01", clock.sleep, clock=clock)
    assert locks.assert_held.call_count == 1


def test_a_lost_claim_still_stops_the_wait_within_a_minute():
    clock = Clock()
    lost = Mock(side_effect=[None, fl.Blocked("single-writer-active-claim-changed")])
    with pytest.raises(fl.Blocked, match="single-writer-active-claim-changed"):
        fl.wait_absent(absent_after(10 ** 6), types.SimpleNamespace(assert_held=lost), GROUP, fl.RG_API,
                       clock.sleep, clock=clock)
    assert clock.now - 1000.0 <= 60 + 5
