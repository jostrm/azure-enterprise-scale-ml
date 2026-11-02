"""Offline: a DELETE is conditioned on the resource's etag only where that etag is stable.

aif-138 (2026-11-02, run16): the factory deletion's common stage deleted the registry's private endpoint with
If-Match on the etag it had just read. The endpoint's etag rolls while the platform tears it down (its proxy and
connection state change), so the asynchronous delete ended Failed with PreconditionFailed and the run stopped with
delete-completion-unverified. Kinds whose etag is volatile (fl.VOLATILE_FIELDS) are deleted without If-Match.
"""

from unittest.mock import Mock

import pytest

from .test_factory_lifecycle import fl

RG = "/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"
PE = RG + "/providers/Microsoft.Network/privateEndpoints/pend-acr"
VAULT = RG + "/providers/Microsoft.KeyVault/vaults/kv-seed"


@pytest.mark.parametrize("identifier, kind, condition", [
    (PE, "Microsoft.Network/privateEndpoints", None),
    (RG + "/providers/Microsoft.Network/networkInterfaces/nic", "Microsoft.Network/networkInterfaces", None),
    (VAULT, "Microsoft.KeyVault/vaults", {"If-Match": 'W/"7"'}),
])
def test_only_a_stable_etag_conditions_the_delete(identifier, kind, condition):
    module = fl.factory_deletion_module()
    assert module.delete_condition({"id": identifier, "type": kind, "etag": 'W/"7"'}) == condition
    assert module.delete_condition({"id": identifier, "type": kind}) is None


class DeleteCloud:
    def __init__(self, kind):
        self.kind, self.present, self.headers = kind, True, []

    def verify_identity(self):
        pass

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "DELETE":
            self.headers.append(headers)
            self.present = False
            return 202, {}, None
        return (200, {}, {"id": resource_id, "type": self.kind, "etag": 'W/"7"'}) if self.present else (404, {}, None)


@pytest.mark.parametrize("identifier, kind, sent", [(PE, "Microsoft.Network/privateEndpoints", None),
                                                     (VAULT, "Microsoft.KeyVault/vaults", {"If-Match": 'W/"7"'})])
def test_the_common_stage_sends_if_match_only_for_a_stable_etag(monkeypatch, identifier, kind, sent):
    module = fl.factory_deletion_module()
    row = {"id": identifier, "type": kind.lower(), "api_version": "2024-05-01", "delete": True, "depends_on": []}
    document = {"identity": {"object_id": "4e6f97b5-7140-40eb-b030-c31d73072197"},
                "deletion": {"flags": dict.fromkeys(module.DELETE_FLAGS, True), "inventory_mode": module.CONTRACT,
                             "resources": [row], "resource_groups": [], "bodies": {}}}
    cloud = DeleteCloud(kind)
    for name in ("assert_connectivity_group_allowed", "verify_permissions"):
        monkeypatch.setattr(module, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "teardown_order", lambda document, rows: list(rows))
    monkeypatch.setattr(module.fl, "assert_deletion_group_allowed", lambda *args: None)
    monkeypatch.setattr(module.fl, "verify_project_inventory", lambda *args, **kwargs: {})
    monkeypatch.setattr(module.fl, "wait_absent", lambda *args, **kwargs: None)
    module.delete_rows(cloud, Mock(spec=module.fl.BlobLocks), document, {}, Mock(), [row], lambda _: None)
    assert cloud.headers == [sent]
