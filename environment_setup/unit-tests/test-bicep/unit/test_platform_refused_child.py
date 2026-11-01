"""Offline: a listed child that the platform refuses to every client is recorded from its list row.

aif-138 (2026-11-01): the factory deletion's inventory listed the Container Apps subnet link
serviceAssociationLinks/legionservicelink/details/detail; reading it on its own answers 409
UnauthorizedClientApplication for every caller, so prepare refused with remote-request-failed-409.
"""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("factory_lifecycle_refused_base",
                                              Path(__file__).with_name("test_factory_lifecycle.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
fl = base.fl


class RefusingCloud(base.ClosureCloud):
    def __init__(self, code):
        super().__init__()
        self.code = code

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "GET" and resource_id.lower() == base.RULE.lower():
            fl.require(409 in allowed, "remote-request-failed-409")
            return 409, {}, {"error": {"code": self.code, "message": "refused"}}
        return super().arm(method, resource_id, api_version, allowed, headers)


def test_a_listed_child_the_platform_refuses_to_read_is_fingerprinted_from_its_list_row():
    cloud = RefusingCloud("UnauthorizedClientApplication")
    closure, bodies = fl.collect_resource_closure(cloud, [base.GROUP])
    row = cloud.bodies[base.RULE.lower()]
    kind = fl.resource_type_from_id(base.RULE)
    assert closure["resources"][base.RULE.lower()]["body_hash"] == fl.resource_digest(fl.fingerprint_body(row), kind)
    assert bodies[base.RULE.lower()]["id"] == base.RULE


def test_any_other_conflict_on_a_child_read_still_blocks():
    with pytest.raises(fl.Blocked, match="^remote-request-failed-409$"):
        fl.collect_resource_closure(RefusingCloud("Conflict"), [base.GROUP])


DETAIL = base.RULE + "/details/detail"


class ReferencedRefusalCloud(base.ClosureCloud):
    """As live: another body names the refused child, and its own list endpoint returns nothing."""

    def __init__(self, code):
        super().__init__()
        self.code = code
        self.bodies[base.NSG.lower()]["properties"] = {"link": {"id": DETAIL}}

    def provider_schema(self, namespace):
        schema = super().provider_schema(namespace)
        schema["resourceTypes"].append({"resourceType": "networkSecurityGroups/securityRules/details",
                                        "apiVersions": ["2024-05-01"]})
        return schema

    def collection(self, path, api_version, extension=False):
        if path.lower().endswith("/details"):
            return [], None
        return super().collection(path, api_version, extension)

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "GET" and resource_id.lower() == DETAIL.lower():
            fl.require(409 in allowed, "remote-request-failed-409")
            return 409, {}, {"error": {"code": self.code, "message": "refused"}}
        return super().arm(method, resource_id, api_version, allowed, headers)


def test_a_referenced_child_the_platform_refuses_to_read_stays_a_recorded_reference():
    closure, bodies = fl.collect_resource_closure(ReferencedRefusalCloud("UnauthorizedClientApplication"), [base.GROUP])
    assert DETAIL.lower() not in closure["resources"] and DETAIL.lower() not in bodies
    assert DETAIL.lower() in closure["references"][base.NSG.lower()]


def test_any_other_conflict_on_a_referenced_read_still_blocks():
    with pytest.raises(fl.Blocked, match="^remote-request-failed-409$"):
        fl.collect_resource_closure(ReferencedRefusalCloud("Conflict"), [base.GROUP])
