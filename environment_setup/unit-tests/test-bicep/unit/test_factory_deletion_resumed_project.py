"""Offline: a factory deletion prepared again after its project stage already deleted the project group.

aif-138 (2026-11-02): the factory deletion's GitHub project stage deleted project001-rg, then the local common stage
stopped on a provider state read before it deleted anything. The next delete_factory's freeze read the project
group's closure, ARM answered 404 and prepare refused with remote-request-failed-404, so the common group could never
be deleted through the product. The scale-set deletion already records such a group as already absent
(fl.freeze_deletion_inventory); the factory deletion now does the same for a registered project's group.
"""

import copy
import json

import pytest

from .test_factory_lifecycle import fl, GROUP, COMMON, RESOURCE, seal, workspace, no_real_services  # noqa: F401
from .test_selective_project_deletion import PROJECT, SUBNET, SHARED_SUBNET, VNET, VAULT
from .test_factory_deletion_pipeline import factory_prepared


def project_stage_done(cloud):
    """What a succeeded project stage leaves: the project group, its resources and its subnet are gone."""
    for key in [GROUP.lower(), RESOURCE.lower(), VAULT.lower(), SUBNET.lower()]:
        cloud.bodies.pop(key, None)
    vnet = cloud.bodies[VNET.lower()]
    vnet["properties"]["subnets"] = [copy.deepcopy(cloud.bodies[SHARED_SUBNET.lower()])]
    read = cloud.arm

    def arm(method, resource_id, api_version, allowed=(200,), headers=None):
        if fl.RG_ID.fullmatch(resource_id) and resource_id.lower() not in cloud.bodies:
            assert method == "GET", (method, resource_id)
            fl.require(404 in allowed, "remote-request-failed-404")  # as the real Cloud.request
            return 404, {}, {"error": {"code": "ResourceGroupNotFound", "message": "Resource group could not be found."}}
        return read(method, resource_id, api_version, allowed, headers)

    cloud.arm = arm
    return cloud


def refrozen():
    document, cloud, projects = factory_prepared()
    project_stage_done(cloud)
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    unsealed["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    return seal(unsealed), cloud, projects


def test_a_project_group_its_stage_already_deleted_is_frozen_as_already_absent():
    document, _, _ = refrozen()
    fl.validate_manifest(document)
    data = document["deletion"]
    groups = {row["id"].lower(): row for row in data["resource_groups"]}
    assert groups[GROUP.lower()]["already_absent"] is True and groups[GROUP.lower()]["delete"] is True
    assert groups[GROUP.lower()]["project_number"] == "017" and GROUP.lower() not in data["bodies"]
    assert groups[COMMON.lower()].get("already_absent") is None
    assert data["projects"][0]["resource_group_id"] == GROUP.lower()
    assert not any(row["id"].lower().startswith(GROUP.lower() + "/") for row in data["resources"])


def test_the_resumed_factory_deletion_deletes_the_common_resources_and_never_the_absent_group(workspace, monkeypatch):
    document, cloud, _ = refrozen()
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)

    def dispatch(actual_cloud, locks, actual, source_root, receipt, persist):
        receipt["remote_run"] = {"kind": "ado", "pipeline_id": 8, "run_id": 44}
        persist()
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(actual, locks)),
                                         source_root, actual["run_id"], actual["manifest_hash"],
                                         cloud=actual_cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        assert [value.lower() for value in result["deleted_resources"]] == [GROUP.lower()]
        receipt["remote_terminal"] = True

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "succeeded", result
    assert cloud.deleted[-1].endswith("/common-ip")
    assert GROUP not in cloud.deleted and GROUP.lower() not in {value.lower() for value in cloud.deleted}


def test_an_absent_group_that_is_no_registered_project_group_blocks_the_freeze():
    document, cloud, projects = factory_prepared()
    project_stage_done(cloud)
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    other = [{**projects[0], "registered_resource_ids": [SUBNET]}]
    with pytest.raises(fl.Blocked, match="factory-delete-exact-project-group-required"):
        fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, other)


@pytest.mark.parametrize("tamper", ["body-hash", "kept", "other-project", "body-added"])
def test_an_already_absent_row_is_validated_exactly(tamper):
    document, _, _ = refrozen()
    data = document["deletion"]
    row = next(row for row in data["resource_groups"] if row.get("already_absent"))
    if tamper == "body-hash":
        row["body_hash"] = "0" * 64
    elif tamper == "kept":
        row["delete"] = False
    elif tamper == "other-project":
        row["project_number"] = None
    else:
        data["bodies"][GROUP.lower()] = {"id": GROUP}
    data["inventory_hash"] = fl.digest(data["resources"])
    with pytest.raises(fl.Blocked):
        fl.validate_manifest(seal(document))
