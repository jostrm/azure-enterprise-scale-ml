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


def with_resolver_link(body, etag='W/"1"', linked="Microsoft.Network/dnsResolvers"):
    # aif-154 (2026-11-09, ESAF job 10657e03, catalog runs 6842cfec and 5f26c110): the own hub's DNS-resolver subnet
    # carries a serviceAssociationLink whose etag is the VNet's; each private endpoint connection the common stage deleted
    # rolled it, and the worker stopped with project-resource-instance-changed on vnt-esmlcmn-sdc-dev-001.
    subnets = body["properties"]["subnets"] if "subnets" in body["properties"] else [body]
    subnets[0]["properties"]["serviceAssociationLinks"] = [{
        "id": subnets[0]["id"] + "/serviceAssociationLinks/dnsResolverLink", "name": "dnsResolverLink", "etag": etag,
        "type": "Microsoft.Network/virtualNetworks/subnets/serviceAssociationLinks",
        "properties": {"linkedResourceType": linked, "link": "/subscriptions/x/resourceGroups/y/providers/" + linked + "/r"}}]
    return body


def test_an_etag_roll_in_a_service_association_link_leaves_the_fingerprints_unchanged():
    assert fl.resource_digest(with_resolver_link(vnet('W/"2"'), 'W/"2"')) == fl.resource_digest(with_resolver_link(vnet()))
    assert fl.resource_digest(with_resolver_link(subnet('W/"2"'), 'W/"2"')) == fl.resource_digest(with_resolver_link(subnet()))


def test_a_changed_service_association_link_still_changes_the_fingerprints():
    other = "Microsoft.Web/serverFarms"
    assert fl.resource_digest(with_resolver_link(vnet(), linked=other)) != fl.resource_digest(with_resolver_link(vnet()))
    assert fl.resource_digest(with_resolver_link(subnet(), linked=other)) != fl.resource_digest(with_resolver_link(subnet()))


def test_a_service_association_link_child_ignores_its_etag_but_not_its_link():
    # aif-154 run20 (2026-11-09, catalog run d80a0008): the VNet passed with 098b48e2, then the link itself, listed as a
    # child resource, stopped the worker with project-resource-instance-changed on the same rolled etag.
    link = with_resolver_link(subnet())["properties"]["serviceAssociationLinks"][0]
    rolled = dict(link, etag='W/"2"')
    moved = dict(link, properties=dict(link["properties"], linkedResourceType="Microsoft.Web/serverFarms"))
    assert fl.resource_digest(rolled) == fl.resource_digest(link)
    assert fl.resource_digest(moved) != fl.resource_digest(link)


def test_a_delegation_child_ignores_its_etag_but_not_its_service():
    # Listed inline from its subnet (collect_resource_closure), a delegation carries the VNet's etag too: in aif-154 run19
    # it rolled with the link's, so it would have been the next stop after the link.
    delegation = subnet()["properties"]["delegations"][0]
    rolled = dict(delegation, etag='W/"2"')
    moved = dict(delegation, properties={"serviceName": "Microsoft.Web/serverFarms"})
    assert fl.resource_digest(rolled) == fl.resource_digest(delegation)
    assert fl.resource_digest(moved) != fl.resource_digest(delegation)
