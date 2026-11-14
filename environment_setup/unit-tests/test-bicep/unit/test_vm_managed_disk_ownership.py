"""Deletion ownership: a managed disk Azure created for a virtual machine is owned through that machine.

aif-160 (2026-11-14, video 10, ESAF job a517897e): the data science VM dsvm-cmn-sdc-dev-001 in the common group carried
the factory's tags, but the two disks Azure created with it (..._OsDisk_1_..., ..._disk2_...) carry no tags and no
deployment receipt. delete-factory retained both as outside-registered-ownership and refused the whole-group common
teardown ("whole-resource-group execution cannot honor selective retention"). Azure sets managedBy on a disk only
while a machine has it attached: a disk whose managedBy names a machine in its own group, which lists the disk back in
its storage profile, is owned through that machine. Any other untagged disk is still never adopted.
"""

import copy

import pytest

from .test_factory_lifecycle import fl, COMMON, OWNER
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import tagged


CORE = {key: value for key, value in OWNER.items() if key != "project_id"}
VM = COMMON + "/providers/Microsoft.Compute/virtualMachines/dsvm-cmn-sdc-dev-001"
OS_DISK = COMMON + "/providers/Microsoft.Compute/disks/dsvm-cmn-sdc-dev-001_OsDisk_1_0f4c1a2b3c4d4e5f8a9b0c1d2e3f4a5b"
DATA_DISK = COMMON + "/providers/Microsoft.Compute/disks/dsvm-cmn-sdc-dev-001_disk2_6a7b8c9d0e1f4a2b9c3d4e5f6a7b8c9d"


def disk(identifier, managed_by):
    body = {"id": identifier, "type": "Microsoft.Compute/disks", "etag": '"d"',
            "properties": {"diskState": "Attached" if managed_by else "Unattached", "diskSizeGB": 128}}
    if managed_by:
        body["managedBy"] = managed_by
    return body


def storage_profile(os_disk=OS_DISK, data_disks=(DATA_DISK,)):
    return {"storageProfile": {"osDisk": {"name": "os", "managedDisk": {"id": os_disk}},
                               "dataDisks": [{"lun": index, "managedDisk": {"id": value}}
                                             for index, value in enumerate(data_disks)]}}


def with_machine(managed_by=VM, data_disks=(DATA_DISK,), vm_owner=CORE):
    document, cloud, projects = factory_prepared()
    cloud.bodies[VM.lower()] = tagged(VM, "Microsoft.Compute/virtualMachines", vm_owner, storage_profile(data_disks=data_disks))
    cloud.bodies[OS_DISK.lower()] = disk(OS_DISK, VM)
    cloud.bodies[DATA_DISK.lower()] = disk(DATA_DISK, managed_by)
    schema = cloud.provider_schema

    def provider_schema(namespace):
        if namespace.lower() == "microsoft.compute":
            return {"resourceTypes": [{"resourceType": kind, "apiVersions": ["2024-05-01"]}
                                      for kind in ("virtualMachines", "disks")]}
        return schema(namespace)
    cloud.provider_schema = provider_schema
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    return unsealed, cloud, projects


def test_the_disks_azure_created_for_an_owned_machine_are_owned_through_it():
    document, cloud, projects = with_machine()
    data = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    rows = {item["id"].lower(): item for item in data["resources"]}
    for identifier in (OS_DISK, DATA_DISK):
        row = rows[identifier.lower()]
        assert row["ownership_source"] == "managed-parent" and row["managed_parent_id"] == VM.lower()
        assert row["owner"] == CORE and row["delete"] is True and "retention_reason" not in row
    assert not [item["id"] for item in data["resources"] if item.get("retention_reason") == "outside-registered-ownership"]


@pytest.mark.parametrize("managed_by, data_disks", [
    (None, (DATA_DISK,)),                                                     # an unattached untagged disk
    (VM, ()),                                                                 # the machine does not list it back
    (VM.replace(COMMON, COMMON + "-other"), (DATA_DISK,)),                    # a machine in another group
    (COMMON + "/providers/Microsoft.Compute/virtualMachineScaleSets/pool", (DATA_DISK,)),   # not a virtual machine
])
def test_any_other_untagged_disk_is_never_adopted(managed_by, data_disks):
    document, cloud, projects = with_machine(managed_by, data_disks)
    data = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    row = next(item for item in data["resources"] if item["id"].lower() == DATA_DISK.lower())
    assert row["delete"] is False and row["retention_reason"] == "outside-registered-ownership"
    assert row.get("ownership_source") != "managed-parent"


def test_a_disk_of_another_factorys_machine_is_not_this_factorys():
    document, cloud, projects = with_machine(vm_owner={**CORE, "factory_id": "factory-b"})
    data = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    row = next(item for item in data["resources"] if item["id"].lower() == DATA_DISK.lower())
    assert row["delete"] is False and row["owner"]["factory_id"] == "factory-b"


def test_the_scale_set_freeze_owns_the_disk_through_its_machine():
    bodies = {VM.lower(): tagged(VM, "Microsoft.Compute/virtualMachines", CORE, storage_profile()),
              DATA_DISK.lower(): disk(DATA_DISK, VM)}
    assert fl.managed_parent_id(DATA_DISK, bodies, CORE) == VM.lower()
    bodies[VM.lower()]["properties"] = storage_profile(data_disks=())
    with pytest.raises(fl.Blocked, match="^known-child-ownership-record-required$"):
        fl.managed_parent_id(DATA_DISK, bodies, CORE)
