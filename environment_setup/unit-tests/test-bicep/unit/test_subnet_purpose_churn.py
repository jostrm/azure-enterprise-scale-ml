"""Offline: a subnet's read-only purpose follows its private endpoints; it never blocks.

aif-138 (2026-11-02, run18): the factory deletion's common stage deleted the last private endpoints in
snet-esml-cmn-001; Network RP then left out the subnet's properties.purpose ("PrivateEndpoints"), in the subnet
resource and in the VNet's embedded subnet, and the retained-parent check stopped with project-retained-parent-changed.
"""

from .test_factory_lifecycle import fl

VNET = ("/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"
        "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001")


def subnet(purpose="PrivateEndpoints", prefix="10.0.0.0/24"):
    body = {"id": VNET + "/subnets/snet-esml-cmn-001", "type": "Microsoft.Network/virtualNetworks/subnets",
            "properties": {"addressPrefix": prefix}}
    if purpose:
        body["properties"]["purpose"] = purpose
    return body


def vnet(**changes):
    return {"id": VNET, "type": "Microsoft.Network/virtualNetworks", "properties": {"subnets": [subnet(**changes)]}}


def test_a_purpose_the_platform_dropped_leaves_the_subnet_and_vnet_fingerprints_unchanged():
    assert fl.resource_digest(subnet(purpose=None)) == fl.resource_digest(subnet())
    assert fl.resource_digest(vnet(purpose=None)) == fl.resource_digest(vnet())


def test_a_changed_address_still_changes_the_fingerprints():
    assert fl.resource_digest(subnet(prefix="10.0.9.0/24")) != fl.resource_digest(subnet())
    assert fl.resource_digest(vnet(prefix="10.0.9.0/24")) != fl.resource_digest(vnet())
