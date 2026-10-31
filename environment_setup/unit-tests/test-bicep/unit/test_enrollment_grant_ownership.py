"""enroll-scale-set grants the bound deployment principal Contributor and Role Based Access Control Administrator on each
enrolled group. Role assignments carry no tags and the enrollment records them in its audit record, not in a worker
receipt, so the first common deployment of an added scale set refused with child-ownership-evidence-required
(aif-138 scale set 002, 2026-10-31). Exactly those grants are the scale set's own."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("factory_lifecycle_grant", ROOT / "bootstrap/lib/factory_lifecycle.py")
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)

SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PRINCIPAL = "0f3e5778-b57f-4277-98c5-0689d3f81a67"
GROUP = "/subscriptions/" + SUB + "/resourcegroups/aif-138-esml-common-sdc-dev-002"
CONTRIBUTOR = "b24988ac-6180-42a0-ab88-20f7382dd24c"
DOCUMENT = {"identity": {"deployment_object_id": PRINCIPAL}}


def assignment(role=CONTRIBUTOR, principal=PRINCIPAL, scope=GROUP):
    key = scope + "/providers/microsoft.authorization/roleassignments/b6aa568c-a988-5856-bec3-e57d83305f8e"
    body = {"properties": {"principalId": principal, "scope": scope,
                           "roleDefinitionId": "/subscriptions/" + SUB + "/providers/Microsoft.Authorization/roleDefinitions/" + role}}
    return key, body


def test_the_enrollment_grants_on_an_enrolled_group_are_the_scale_sets_own():
    for role in (CONTRIBUTOR, "f58310d9-a9f6-439a-9e8d-f62e7b41a168"):
        key, body = assignment(role=role)
        assert fl.enrollment_grant(key, body, DOCUMENT, [GROUP.upper()])


def test_any_other_role_assignment_still_needs_ownership_evidence():
    owner_role = "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
    other_group = "/subscriptions/" + SUB + "/resourcegroups/other"
    for key, body in (assignment(role=owner_role), assignment(principal="11111111-2222-3333-4444-555555555555"),
                      assignment(scope=other_group)):
        assert not fl.enrollment_grant(key, body, DOCUMENT, [GROUP])
    key, body = assignment()
    assert not fl.enrollment_grant(GROUP + "/providers/microsoft.storage/storageaccounts/x", body, DOCUMENT, [GROUP])
    assert not fl.enrollment_grant(key, {"properties": {}}, DOCUMENT, [GROUP])
