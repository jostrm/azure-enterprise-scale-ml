"""Offline: a whole-group deletion resumes after an interrupted run already removed one of its groups.

aif-138 (2026-11-01): the scale-set 002 deletion deleted the common group and then stopped on a provider read. The
next deletion's inventory read that group's resource list, ARM answered 404 and prepare refused with
remote-request-failed-404, so the project group could never be deleted through the product.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("factory_lifecycle_resumed_base",
                                              Path(__file__).with_name("test_factory_lifecycle.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
fl = base.fl
workspace = base.workspace
ABSENT = base.GROUP + "-gone"


class ResumedCloud(base.CohortCloud):
    def __init__(self, code="ResourceGroupNotFound"):
        super().__init__()
        self.code, self.group_deletes = code, []

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if resource_id.lower() == ABSENT.lower() and ABSENT.lower() not in self.bodies:
            if method == "DELETE":
                self.group_deletes.append(resource_id)
            assert method == "GET" and 404 in allowed, (method, resource_id)
            return 404, {}, {"error": {"code": self.code, "message": "Resource group could not be found."}}
        if method == "DELETE" and fl.RG_ID.fullmatch(resource_id):
            self.group_deletes.append(resource_id)
        return super().arm(method, resource_id, api_version, allowed, headers)

    def gone(self, scope):
        # ARM answers 404 for every read under a deleted group, as in the aif-138 execution.
        fl.require(scope.lower() != ABSENT.lower() or ABSENT.lower() in self.bodies, "remote-request-failed-404")

    def assert_no_active_deployments(self, scope):
        self.gone(scope)
        return super().assert_no_active_deployments(scope)

    def list_resources(self, scope):
        self.gone(scope)
        return super().list_resources(scope)


def resumed(code="ResourceGroupNotFound"):
    cloud = ResumedCloud(code)
    document = base.manifest()
    document["locks"]["scopes"] = [base.GROUP, ABSENT]
    binding = dict(cloud.enrollment["scopes"][base.GROUP.lower()])
    cloud.enrollment["scopes"][ABSENT.lower()] = binding
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    return cloud, document


def locks(cloud):
    return SimpleNamespace(authorize=lambda value: None, assert_held=lambda: None, enrollment=cloud.enrollment)


def test_a_group_an_interrupted_deletion_removed_is_recorded_absent_and_never_deleted_again():
    cloud, document = resumed()
    document["deletion"] = fl.freeze_deletion_inventory(cloud, document, {})
    groups = {group["id"]: group for group in document["deletion"]["resource_groups"]}
    assert set(groups) == {base.GROUP, ABSENT}
    assert groups[ABSENT]["already_absent"] is True and groups[ABSENT]["delete"] is True
    assert groups[ABSENT]["owner"] == base.CORE_OWNER and "already_absent" not in groups[base.GROUP]
    assert ABSENT.lower() not in document["deletion"]["closure"]["groups"]
    receipt = {"deleted_resources": []}
    fl.delete_owned_groups(cloud, locks(cloud), document, receipt, lambda: None, sleep=lambda _: None)
    assert cloud.group_deletes == [base.GROUP]
    assert ABSENT in receipt["deleted_resources"] and base.GROUP in receipt["deleted_resources"]
    assert len(receipt["deleted_resources"]) == len(set(receipt["deleted_resources"]))


def test_an_absent_group_that_reappears_blocks_before_any_delete():
    cloud, document = resumed()
    document["deletion"] = fl.freeze_deletion_inventory(cloud, document, {})
    cloud.bodies[ABSENT.lower()] = {**cloud.bodies[base.GROUP.lower()], "id": ABSENT, "name": "reviewed-gone"}
    with pytest.raises(fl.Blocked, match="^absent-resource-group-reappeared$"):
        fl.delete_owned_groups(cloud, locks(cloud), document, {"deleted_resources": []}, lambda: None,
                               sleep=lambda _: None)
    assert cloud.group_deletes == []


def test_only_resource_group_not_found_proves_a_group_absent():
    cloud, document = resumed(code="AuthorizationFailed")
    with pytest.raises(fl.Blocked, match="^resource-group-absence-unverified$"):
        fl.freeze_deletion_inventory(cloud, document, {})


def test_a_resumed_cohort_executes_without_reading_the_absent_group(monkeypatch, workspace):
    cloud, document = resumed()
    document["deletion"] = fl.freeze_deletion_inventory(cloud, document, {})
    base.seal(document)
    cloud.calls.clear()
    source, execution, path = base.setup_execute(monkeypatch, workspace)
    result = fl.execute_cohort([document], source, execution, path, cloud_factory=lambda value: cloud)
    assert result["status"] == "succeeded" and not result["lock_retained"], result.get("error_code")
    assert cloud.group_deletes == [base.GROUP]
    assert ABSENT in result["children"][0]["deleted_resources"]
