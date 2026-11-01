"""Whole-factory deletion validates a resource's fingerprint as the closure recorded it, with its recorded type.

aif-138 (2026-11-01): the factory deletion freeze refused with factory-delete-resource-fingerprint-required.
A listed Log Analytics table has no "type" in its body, so the closure hashed it with its recorded type and the
validation, hashing it without one, never matched (as 8a54f7aa fixed for verify_fingerprint).
"""

import copy

from .test_factory_lifecycle import fl, GROUP, OWNER
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import tagged


TYPELESS = GROUP + "/providers/Microsoft.Network/publicIPAddresses/typeless-ip"


def test_a_typeless_body_validates_with_its_recorded_type(monkeypatch):
    # As a Log Analytics table: the recorded type selects volatile fields that the typeless body cannot name.
    monkeypatch.setitem(fl.VOLATILE_FIELDS, "microsoft.network/publicipaddresses", (("properties", "ipAddress"),))
    document, cloud, projects = factory_prepared()
    body = tagged(TYPELESS, "Microsoft.Network/publicIPAddresses", OWNER, {"ipAddress": "10.0.0.4"})
    del body["type"]
    cloud.bodies[TYPELESS.lower()] = body
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    data = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    row = next(item for item in data["resources"] if item["id"].lower() == TYPELESS.lower())
    assert row["body_hash"] == fl.resource_digest(body, "microsoft.network/publicipaddresses") != fl.resource_digest(body)
