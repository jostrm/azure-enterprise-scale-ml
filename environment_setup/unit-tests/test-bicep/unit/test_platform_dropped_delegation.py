"""Offline: a subnet's delegation that the platform drops with its delegated service's last link may be gone.

aif-154 (2026-11-09, video 06 Scenario 6, catalog run 8d03dc78): the factory deletion deleted the own hub's DNS
resolver inbound endpoint. Azure then dropped the subnet's dnsResolverLink (a reviewed child) and also its
dns-resolver delegation, which no plan row deletes, and the worker stopped with project-retained-parent-changed after
781 deletions. A delegation whose service names the linked resource type of a removed service association link left
with it; any other delegation, and every other subnet setting, still counts.
"""

import copy

from .test_factory_lifecycle import fl

RG = "/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-154-esml-common-sdc-dev-001"
VNET = RG + "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001"
SUBNET = VNET + "/subnets/snet-aif-dns-resolver"
LINK = SUBNET + "/serviceAssociationLinks/dnsResolverLink"
DELEGATION = SUBNET + "/delegations/dns-resolver"
SERVICE = "Microsoft.Network/dnsResolvers"


def subnet(link=True, delegation=SERVICE, prefix="10.0.4.0/28"):
    props = {"addressPrefix": prefix}
    if delegation:
        props["delegations"] = [{"id": DELEGATION, "name": "dns-resolver", "properties": {"serviceName": delegation}}]
    if link:
        props["serviceAssociationLinks"] = [{"id": LINK, "name": "dnsResolverLink", "properties": {
            "linkedResourceType": SERVICE, "link": "/InboundEndpoint/d5fc878b-4edf-4ee4-bb88-243d2c1dd554"}}]
    return {"id": SUBNET, "name": "snet-aif-dns-resolver", "type": "Microsoft.Network/virtualNetworks/subnets",
            "properties": props}


def vnet(**changes):
    body = subnet(**changes)
    body.pop("type")
    return {"id": VNET, "type": "Microsoft.Network/virtualNetworks", "properties": {"subnets": [body]}}


def dropped(frozen, live, removed):
    return fl.platform_dropped_delegations({key.lower(): value for key, value in frozen.items()},
                                           {key.lower(): value for key, value in live.items()},
                                           {value.lower() for value in removed})


def test_a_delegation_that_left_with_its_removed_link_may_be_gone():
    frozen = {SUBNET: subnet(), VNET: vnet()}
    live = {SUBNET: subnet(link=False, delegation=None), VNET: vnet(link=False, delegation=None)}
    assert dropped(frozen, live, {LINK}) == {DELEGATION.lower()}


def test_a_delegation_still_present_another_service_or_a_kept_link_is_not_dropped():
    frozen = {SUBNET: subnet(), VNET: vnet()}
    assert dropped(frozen, {SUBNET: subnet(link=False), VNET: vnet(link=False)}, {LINK}) == set()
    assert dropped(frozen, {SUBNET: subnet(link=False, delegation=None)}, set()) == set()
    other = {SUBNET: subnet(delegation="Microsoft.Web/serverFarms")}
    assert dropped(other, {SUBNET: subnet(link=False, delegation=None)}, {LINK}) == set()


def compare(live, frozen, removed):
    return (fl.fingerprint_body(fl._without_deleted_children(fl._without_removed_backlinks(live, removed), removed))
            == fl.fingerprint_body(fl._without_deleted_children(fl._without_removed_backlinks(frozen, removed), removed)))


def test_the_retained_parent_comparison_passes_only_with_the_dropped_delegation():
    frozen, live = vnet(), vnet(link=False, delegation=None)
    removed = {LINK.lower()}
    assert not compare(live, frozen, removed)
    removed |= dropped({VNET: frozen}, {VNET: live}, removed)
    assert compare(live, frozen, removed)
    assert not compare(vnet(link=False, delegation=None, prefix="10.0.9.0/28"), frozen, removed)
