"""Offline: a VNet copies its etag into every subnet, delegation and peering it embeds, and the subnet children carry it.

aif-138 (2026-11-02): the resumed factory deletion's common stage deleted three role assignments and the registry's
private endpoint connection, then stopped with project-resource-instance-changed on vnt-esmlcmn-sdc-dev-001. The only
drift between the frozen review and the live VNet was its etag and the copies in subnets[].etag and
subnets[].properties.delegations[].etag; every address, subnet and delegation setting was unchanged.
"""

from .test_factory_lifecycle import fl

VNET = ("/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"
        "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001")


def subnet(etag='W/"1"', prefix="10.0.1.0/24", service="Microsoft.App/environments"):
    return {"id": VNET + "/subnets/snt-prj001-aca-002", "name": "snt-prj001-aca-002", "etag": etag,
            "type": "Microsoft.Network/virtualNetworks/subnets",
            "properties": {"addressPrefix": prefix, "delegations": [{
                "id": VNET + "/subnets/snt-prj001-aca-002/delegations/aca", "name": "aca", "etag": etag,
                "type": "Microsoft.Network/virtualNetworks/subnets/delegations",
                "properties": {"serviceName": service}}]}}


def vnet(etag='W/"1"', **changes):
    return {"id": VNET, "name": "vnt-esmlcmn-sdc-dev-001", "etag": etag, "type": "Microsoft.Network/virtualNetworks",
            "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                           "subnets": [subnet(etag, **changes)],
                           "virtualNetworkPeerings": [{"id": VNET + "/virtualNetworkPeerings/hub", "name": "hub",
                                                       "etag": etag, "properties": {"allowForwardedTraffic": True}}]}}


def test_an_etag_roll_leaves_the_vnet_and_its_subnet_fingerprints_unchanged():
    assert fl.resource_digest(vnet('W/"2"')) == fl.resource_digest(vnet())
    assert fl.resource_digest(subnet('W/"2"')) == fl.resource_digest(subnet())


def test_a_changed_subnet_or_delegation_still_changes_the_fingerprints():
    assert fl.resource_digest(vnet(prefix="10.0.2.0/24")) != fl.resource_digest(vnet())
    assert fl.resource_digest(vnet(service="Microsoft.Web/serverFarms")) != fl.resource_digest(vnet())
    assert fl.resource_digest(subnet(prefix="10.0.2.0/24")) != fl.resource_digest(subnet())
    assert fl.resource_digest(subnet(service="Microsoft.Web/serverFarms")) != fl.resource_digest(subnet())
