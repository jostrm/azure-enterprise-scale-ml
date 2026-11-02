"""Offline: deleting a service's private endpoint connection disconnects the endpoint; that state never blocks.

aif-138 (2026-11-02): the resumed factory deletion's common stage deleted the registry's private endpoint connection.
The platform then set the endpoint's connection state to Disconnected (with new etag copies) and cleared its NIC's
privateLinkConnectionProperties.fqdns, so the next inventory check would stop on project-resource-instance-changed.
An NSG copies its etag into its rules the same way a VNet does into its subnets. Identity, the target service, group
ids, subnet, addresses and rule settings still count.
"""

import copy

from .test_factory_lifecycle import fl

RG = "/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"
PE = RG + "/providers/Microsoft.Network/privateEndpoints/pend-acr-cmnsdc-containerreg-to-vnt-esmlcmn"
NIC = RG + "/providers/Microsoft.Network/networkInterfaces/pend-acr-cmnsdc-containerreg-to-vnt-esmlcmn-nic"
NSG = RG + "/providers/Microsoft.Network/networkSecurityGroups/nsg-common"
ACR = RG + "/providers/Microsoft.ContainerRegistry/registries/acrcommon6hc2hsdc001dev"


def endpoint(etag='W/"1"', status="Approved", target=ACR, manual=False):
    connection = {"id": PE + "/privateLinkServiceConnections/acr", "name": "acr", "etag": etag,
                  "properties": {"privateLinkServiceId": target, "groupIds": ["registry"],
                                 "privateLinkServiceConnectionState": {"status": status, "description": "",
                                                                       "actionsRequired": "None"}}}
    return {"id": PE, "name": "pend-acr", "etag": etag, "type": "Microsoft.Network/privateEndpoints",
            "properties": {"subnet": {"id": RG + "/providers/Microsoft.Network/virtualNetworks/v/subnets/s"},
                           "privateLinkServiceConnections": [] if manual else [connection],
                           "manualPrivateLinkServiceConnections": [connection] if manual else []}}


def nic(fqdns=("acrcommon6hc2hsdc001dev.azurecr.io",), address="10.0.0.5"):
    return {"id": NIC, "name": "nic", "etag": 'W/"1"', "type": "Microsoft.Network/networkInterfaces",
            "properties": {"ipConfigurations": [{
                "id": NIC + "/ipConfigurations/ip", "name": "ip", "etag": 'W/"1"',
                "properties": {"privateIPAddress": address,
                               "privateLinkConnectionProperties": {"groupId": "registry",
                                                                   "requiredMemberName": "registry",
                                                                   "fqdns": list(fqdns)}}}]}}


def nsg(etag='W/"1"', port="443"):
    rule = {"id": NSG + "/securityRules/https", "name": "https", "etag": etag,
            "type": "Microsoft.Network/networkSecurityGroups/securityRules",
            "properties": {"destinationPortRange": port, "access": "Allow"}}
    default = {"id": NSG + "/defaultSecurityRules/AllowVnetInBound", "name": "AllowVnetInBound", "etag": etag,
               "type": "Microsoft.Network/networkSecurityGroups/defaultSecurityRules",
               "properties": {"access": "Allow"}}
    return {"id": NSG, "name": "nsg-common", "etag": etag, "type": "Microsoft.Network/networkSecurityGroups",
            "properties": {"securityRules": [rule], "defaultSecurityRules": [default]}}, rule, default


def test_a_disconnected_private_endpoint_keeps_its_fingerprint():
    assert fl.resource_digest(endpoint('W/"2"', "Disconnected")) == fl.resource_digest(endpoint())
    assert fl.resource_digest(endpoint('W/"2"', "Disconnected", manual=True)) == fl.resource_digest(endpoint(manual=True))


def test_a_private_endpoint_to_another_service_still_changes_its_fingerprint():
    assert fl.resource_digest(endpoint(target=ACR + "-other")) != fl.resource_digest(endpoint())
    moved = endpoint()
    moved["properties"]["subnet"]["id"] += "-other"
    assert fl.resource_digest(moved) != fl.resource_digest(endpoint())


def test_a_nic_whose_private_link_fqdns_were_cleared_keeps_its_fingerprint():
    assert fl.resource_digest(nic(fqdns=())) == fl.resource_digest(nic())
    assert fl.resource_digest(nic(address="10.0.0.6")) != fl.resource_digest(nic())


def test_an_nsg_etag_roll_leaves_the_nsg_and_rule_fingerprints_unchanged():
    old, rule, default = nsg()
    new, new_rule, new_default = nsg('W/"2"')
    assert fl.resource_digest(new) == fl.resource_digest(old)
    assert fl.resource_digest(new_rule) == fl.resource_digest(rule)
    assert fl.resource_digest(new_default) == fl.resource_digest(default)
    opened, opened_rule, _ = nsg(port="22")
    assert fl.resource_digest(opened) != fl.resource_digest(old)
    assert fl.resource_digest(opened_rule) != fl.resource_digest(rule)


def test_the_fingerprint_never_changes_the_body_it_reads():
    body = endpoint('W/"2"', "Disconnected")
    before = copy.deepcopy(body)
    fl.resource_digest(body)
    assert body == before


def test_the_nic_ip_configuration_child_whose_private_link_fqdns_were_cleared_keeps_its_fingerprint():
    # aif-138 2026-11-02 (attempt jj): the child resource carries the same privateLinkConnectionProperties as the NIC body.
    child = nic()["properties"]["ipConfigurations"][0]
    child["type"] = "Microsoft.Network/networkInterfaces/ipConfigurations"
    cleared = copy.deepcopy(child)
    cleared["properties"]["privateLinkConnectionProperties"]["fqdns"] = []
    assert fl.resource_digest(cleared) == fl.resource_digest(child)
    moved = copy.deepcopy(child)
    moved["properties"]["privateIPAddress"] = "10.0.0.6"
    assert fl.resource_digest(moved) != fl.resource_digest(child)


def proxy(connected=True, group="vault", remote=None):
    proxy_id = PE + "/privateLinkServiceProxies/pend.proxy.e2a2b45f"
    info = {"groupId": group, "memberName": "default", "privateLinkServiceArmRegion": "" if connected else "swedencentral",
            "customerVisibleFqdns": ["kv.vaultcore.azure.net"] if connected else [],
            "internalFqdn": "kv.vault.azure.net" if connected else "", "internalFqdnType": "", "redirectMapId": ""}
    if connected:
        info["explicitDnsSettings"] = [{"aRecord": "kv", "dnsZoneName": "privatelink.vaultcore.azure.net"}]
    guid = "11111111-1111-1111-1111-111111111111" if connected else "00000000-0000-0000-0000-000000000000"
    return {"id": proxy_id, "name": "pend.proxy.e2a2b45f", "etag": 'W/"1"' if connected else 'W/"2"',
            "type": "Microsoft.Network/privateEndpoints/privateLinkServiceProxies",
            "properties": {"groupConnectivityInformation": [info], "provisioningState": "Succeeded",
                           "remotePrivateEndpointConnection": {"id": remote or ACR + "/privateEndpointConnections/c"},
                           "remotePrivateEndpointConnectionResourceGuid": guid,
                           "remotePrivateLinkServiceConnectionState": {"status": "Approved" if connected else "Disconnected"},
                           "remotePrivateLinkServiceResourceGuid": guid, "remoteRegionExpansionOrContraction": False,
                           "remoteVipAddresses": ["10.0.0.9"] if connected else []}}


def test_a_disconnected_private_link_service_proxy_keeps_its_fingerprint():
    # aif-138 2026-11-02 (attempt jj): after the vault's connection was deleted the proxy's DNS, GUIDs and VIPs reset.
    assert fl.resource_digest(proxy(connected=False)) == fl.resource_digest(proxy())


def test_a_proxy_to_another_group_or_connection_still_changes_its_fingerprint():
    assert fl.resource_digest(proxy(group="registry")) != fl.resource_digest(proxy())
    assert fl.resource_digest(proxy(remote=ACR + "/privateEndpointConnections/other")) != fl.resource_digest(proxy())
