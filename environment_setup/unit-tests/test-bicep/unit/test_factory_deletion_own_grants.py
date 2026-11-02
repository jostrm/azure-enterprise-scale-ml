"""Offline: the executing identity's own enrollment grants on a deleted group go with the group, never one by one.

aif-138 (2026-11-02): the factory deletion's project stage deleted the deployment identity's Role Based Access Control
Administrator grant on the project group second of 21 role assignments; the next permission check then refused with
project-delete-permission-required. No order works: its Contributor grant is what deletes the group and its RBAC
Administrator grant is what deletes role assignments, so both must go with the group delete itself.
"""

from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import fl

SUB = "f0fe8b33-73bf-41e4-9997-e3920d793c06"
PRINCIPAL = "0f3e5778-b57f-4277-98c5-0689d3f81a67"
GROUP = "/subscriptions/" + SUB + "/resourceGroups/aif-138-esml-project001-sdc-dev-001-rg"
RBAC_ADMIN, CONTRIBUTOR, OTHER_ROLE = ("f58310d9-a9f6-439a-9e8d-f62e7b41a168", "b24988ac-6180-42a0-ab88-20f7382dd24c",
                                       "1c0163c0-47e6-4577-8991-ea5c82e286e4")
RA_TYPE = "microsoft.authorization/roleassignments"


def assignment(name, role, principal=PRINCIPAL, scope=GROUP):
    key = scope + "/providers/Microsoft.Authorization/roleAssignments/" + name
    body = {"id": key, "type": "Microsoft.Authorization/roleAssignments",
            "properties": {"principalId": principal, "scope": scope,
                           "roleDefinitionId": "/subscriptions/" + SUB
                           + "/providers/Microsoft.Authorization/roleDefinitions/" + role}}
    return {"id": key, "type": RA_TYPE, "api_version": "2022-04-01", "delete": True, "depends_on": []}, body


OWN_ADMIN = assignment("57f87b7b-b639-569c-8a60-f69a6330183e", RBAC_ADMIN)
OWN_CONTRIBUTOR = assignment("bef0b89d-72f9-509a-a526-4b3636d67672", CONTRIBUTOR)
OTHER = assignment("366c0fb3-c549-5a84-bcf5-ec946664cb9f", OTHER_ROLE, principal="f030d09b-c7ae-4888-8e05-1949ad84294f")
FOREIGN_SCOPE = assignment("8a1f0000-0000-5000-8000-000000000001", RBAC_ADMIN,
                           scope="/subscriptions/" + SUB + "/resourceGroups/aif-138-esml-common-sdc-dev-001")
GROUP_ROW = {"id": GROUP, "type": "microsoft.resources/resourcegroups", "delete": True, "depends_on": []}


def document(*items):
    return {"identity": {"deployment_object_id": PRINCIPAL, "object_id": "4e6f97b5-7140-40eb-b030-c31d73072197"},
            "deletion": {"flags": dict.fromkeys(fl.factory_deletion_module().DELETE_FLAGS, True),
                         "inventory_mode": "ordered-project-pipelines-v1",
                         "resources": [row for row, _ in items], "resource_groups": [GROUP_ROW],
                         "bodies": {row["id"].lower(): body for row, body in items}}}


def test_only_the_identitys_enrollment_grants_on_a_deleted_group_go_with_it():
    module = fl.factory_deletion_module()
    doc = document(OWN_ADMIN, OWN_CONTRIBUTOR, OTHER, FOREIGN_SCOPE)
    rows = doc["deletion"]["resources"] + [GROUP_ROW]
    assert module.group_cascaded_grants(doc, rows) == {OWN_ADMIN[0]["id"].lower(), OWN_CONTRIBUTOR[0]["id"].lower()}
    # A group this stage does not delete keeps every grant on it a row of its own.
    assert module.group_cascaded_grants(doc, doc["deletion"]["resources"]) == set()


class GrantCloud:
    def __init__(self, items):
        self.present = {GROUP.lower()} | {row["id"].lower() for row, _ in items}
        self.deleted = []

    def verify_identity(self):
        pass

    def list_resources(self, scope):
        return []

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        key = resource_id.lower()
        if method == "DELETE":
            self.deleted.append(resource_id)
            self.present = {value for value in self.present if value != key and not value.startswith(key + "/")}
            return 202, {}, None
        return (200, {}, {"id": resource_id}) if key in self.present else (404, {}, None)


def test_the_stage_deletes_other_grants_then_the_group_and_records_its_own_grants_with_it(monkeypatch):
    module = fl.factory_deletion_module()
    items = (OWN_ADMIN, OTHER, OWN_CONTRIBUTOR)
    doc = document(*items)
    cloud = GrantCloud(items)
    monkeypatch.setattr(module, "teardown_order", lambda document, rows: list(rows))
    monkeypatch.setattr(module, "assert_connectivity_group_allowed", lambda *args: None)
    monkeypatch.setattr(module, "verify_permissions", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.fl, "assert_deletion_group_allowed", lambda *args: None)
    monkeypatch.setattr(module.fl, "verify_project_inventory", lambda *args, **kwargs: {})
    receipt = {}
    module.delete_rows(cloud, Mock(spec=module.fl.BlobLocks), doc, receipt, Mock(),
                       doc["deletion"]["resources"] + [GROUP_ROW], lambda _: None)
    assert cloud.deleted == [OTHER[0]["id"], GROUP]
    assert {value.lower() for value in receipt["deleted_resources"]} == {
        GROUP.lower(), *(row["id"].lower() for row, _ in items)}


def test_a_remaining_child_that_is_not_an_own_grant_still_blocks_the_group(monkeypatch):
    module = fl.factory_deletion_module()
    items = (OWN_ADMIN, OTHER)
    doc = document(*items)
    cloud = GrantCloud(items)
    monkeypatch.setattr(module, "teardown_order", lambda document, rows: [GROUP_ROW])
    monkeypatch.setattr(module, "assert_connectivity_group_allowed", lambda *args: None)
    monkeypatch.setattr(module, "verify_permissions", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.fl, "assert_deletion_group_allowed", lambda *args: None)
    monkeypatch.setattr(module.fl, "verify_project_inventory", lambda *args, **kwargs: {})
    with pytest.raises(module.fl.Blocked, match="factory-delete-project-rg-shortcut-forbidden"):
        module.delete_rows(cloud, Mock(spec=module.fl.BlobLocks), doc, {}, Mock(),
                           doc["deletion"]["resources"] + [GROUP_ROW], lambda _: None)
    assert not cloud.deleted
