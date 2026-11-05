"""Offline: an untagged NSG in the common group that only subnets of an owned VNet use is deleted with the factory.

aif-144 (2026-11-04, delete_factory run3/run4): the project pipeline deploys each project's NSGs into the common group
untagged (aks|aca|dbx|genai|webapp-nsg-prj001-sdc-dev), and option B receipts cover only the project group. The NSGs were
unowned, so the common VNet was retained; they had to be tagged by hand. The project pipeline's full delete keeps them
(no step calls delete-subnets-for-projects.sh), so the common teardown proves them by the subnets that use them.
"""

import copy

import pytest

from .test_factory_lifecycle import fl, COMMON, OWNER, seal, no_real_services  # noqa: F401
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import SUBNET, VNET, tagged

NSG = COMMON + "/providers/Microsoft.Network/networkSecurityGroups/aks-nsg-prj017-sdc-dev"
CORE = {key: value for key, value in OWNER.items() if key != "project_id"}


def frozen(vnet_owned=True, subnets=(SUBNET,)):
    document, cloud, projects = factory_prepared()
    cloud.bodies[NSG.lower()] = {"id": NSG, "type": "Microsoft.Network/networkSecurityGroups", "etag": '"nsg"',
                                 "properties": {"subnets": [{"id": value} for value in subnets]}}
    cloud.bodies[SUBNET.lower()]["properties"]["networkSecurityGroup"] = {"id": NSG}
    if not vnet_owned:
        cloud.bodies[VNET.lower()].pop("tags")
    unsealed = dict(document)
    unsealed["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, unsealed, {}, projects)
    return seal(unsealed)


def nsg_row(document):
    return next(row for row in document["deletion"]["resources"] if row["id"].lower() == NSG.lower())


def test_an_nsg_only_owned_subnets_use_is_deleted_with_the_common_group():
    document = frozen()
    fl.validate_manifest(document)
    row = nsg_row(document)
    assert row["delete"] is True
    assert row["ownership_source"] == "attached-subnets"
    assert row["owner"] == CORE
    assert row["attached_virtual_network_ids"] == [VNET.lower()]


def test_an_nsg_without_subnets_stays():
    row = nsg_row(frozen(subnets=()))
    assert row["delete"] is False


def test_an_nsg_a_subnet_of_an_unowned_vnet_uses_stays():
    row = nsg_row(frozen(vnet_owned=False))
    assert row["delete"] is False


def test_validation_refuses_an_attached_subnets_proof_that_no_longer_holds():
    document = frozen()
    document = copy.deepcopy(document)
    data = document["deletion"]
    body = data["bodies"][NSG.lower()]
    body["properties"]["subnets"] = []
    nsg_row(document)["body_hash"] = data["closure"]["resources"][NSG.lower()]["body_hash"] = fl.resource_digest(body)
    data["inventory_hash"], data["closure_hash"] = fl.digest(data["resources"]), fl.digest(data["closure"])
    with pytest.raises(fl.Blocked, match="^factory-delete-attached-subnets-proof-invalid$"):
        fl.validate_manifest(seal(document))
