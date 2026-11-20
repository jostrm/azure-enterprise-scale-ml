"""Offline: a resource the group listing still names but whose own read answers 404 is absent, never a failure.

aif-165 (2026-11-19, release/v1.26 d3867a9d, catalog run e0267f20): the factory deletion removed a private DNS zone,
proved it gone (its GET answered 404), and re-read the common group before the next DELETE. ARM's resource list lags a
deletion, so the listing still named the zone; reading it answered 404, which only a dangling reference was allowed
to answer, and the run stopped with remote-request-failed-404 after 153 deletions, leaving 24 resources, the claim
and the Terraform state behind.

The listing is a hint; the resource's own read is the proof. A listed root or child whose read answers 404 is left
out of the closure as if the list had not named it, so the closure equals the one a caught-up listing gives and the
deletion goes on. Any other refusal of that read still blocks.
"""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("factory_lifecycle_stale_listing_base",
                                              Path(__file__).with_name("test_factory_lifecycle.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
fl = base.fl

ZONE = base.GROUP + "/providers/Microsoft.Network/privateDnsZones/privatelink.prod.migration.windowsazure.com"
STALE_RULE = base.NSG + "/securityRules/deleted-rule"


class StaleListingCloud(base.ClosureCloud):
    """The group listing (and the NSG's rule list) still name what was deleted; reading it answers like ARM."""

    def __init__(self, stale_root=True, stale_child=False, refusal=None, workers=1):
        super().__init__()
        self.stale_root, self.stale_child, self.refusal = stale_root, stale_child, refusal
        self.closure_read_workers = workers
        self.reads = []

    def provider_schema(self, namespace):
        schema = super().provider_schema(namespace)
        schema["resourceTypes"].append({"resourceType": "privateDnsZones", "apiVersions": ["2024-06-01"]})
        return schema

    def list_resources(self, scope):
        rows = super().list_resources(scope)
        if self.stale_root:
            rows.append({"id": ZONE, "type": "Microsoft.Network/privateDnsZones", "location": "global",
                         "tags": copy.deepcopy(self.bodies[base.NSG.lower()]["tags"])})
        return rows

    def collection(self, path, api_version, extension=False):
        rows, unsupported = super().collection(path, api_version, extension)
        if self.stale_child and path.lower() == base.NSG.lower() + "/securityrules":
            rows = rows + [{"id": STALE_RULE, "type": "Microsoft.Network/networkSecurityGroups/securityRules",
                            "properties": {"priority": 200}}]
        return rows, unsupported

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "GET" and resource_id.lower() in (ZONE.lower(), STALE_RULE.lower()):
            self.reads.append(resource_id.lower())
            status = self.refusal or 404
            # As Cloud.request: a status the caller did not allow raises remote-request-failed-<status>.
            fl.require(status in allowed, "remote-request-failed-" + str(status))
            return status, {}, None
        return super().arm(method, resource_id, api_version, allowed, headers)


def fresh(**kwargs):
    """The closure a caught-up listing gives: the same cloud, without the stale rows."""
    return fl.collect_resource_closure(StaleListingCloud(stale_root=False, stale_child=False, **kwargs), [base.GROUP])


@pytest.mark.parametrize("workers", [1, 4])
def test_a_listed_root_whose_read_answers_404_is_left_out_as_absent(workers):
    cloud = StaleListingCloud(workers=workers)
    closure, bodies = fl.collect_resource_closure(cloud, [base.GROUP])
    assert ZONE.lower() in cloud.reads  # the listing's hint was checked, not trusted
    assert ZONE.lower() not in closure["resources"] and ZONE.lower() not in bodies
    listing = closure["collections"][base.GROUP.lower() + "/resources"]
    assert ZONE.lower() not in listing["ids"] and all(row["id"].lower() != ZONE.lower() for row in listing["items"])
    assert listing["body_hash"] == fl.digest(listing["items"])
    # Exactly what the listing gives once it caught up, so every later inventory comparison sees no change.
    assert (closure, bodies) == fresh(workers=workers)


@pytest.mark.parametrize("workers", [1, 4])
def test_a_listed_child_whose_read_answers_404_is_left_out_of_its_parents_collection(workers):
    cloud = StaleListingCloud(stale_root=False, stale_child=True, workers=workers)
    closure, bodies = fl.collect_resource_closure(cloud, [base.GROUP])
    rules = closure["collections"][base.NSG.lower() + "/securityrules"]
    assert STALE_RULE.lower() in cloud.reads and STALE_RULE.lower() not in rules["ids"]
    assert STALE_RULE.lower() not in closure["resources"] and STALE_RULE.lower() not in bodies
    assert rules["body_hash"] == fl.digest(rules["items"])
    assert (closure, bodies) == fresh(workers=workers)


@pytest.mark.parametrize("status", [403, 409, 500])
def test_any_other_refusal_of_a_listed_read_still_blocks(status):
    with pytest.raises(fl.Blocked, match="^remote-request-failed-" + str(status) + "$"):
        fl.collect_resource_closure(StaleListingCloud(refusal=status), [base.GROUP])

