"""Offline: a VNet's embedded subnets drop back-references to deleted dependents, as subnet resources already do.

aif-138 (2026-11-02, run17): the factory deletion's common stage deleted the registry's private endpoint (its NIC went
with it). The VNet body's subnets[].properties.ipConfigurations then no longer named that NIC's IP configuration, and
the retained-parent check stopped with project-resource-instance-changed. REVERSE_LINKS covered subnet resources only.
"""

from .test_factory_lifecycle import fl

RG = "/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/AIF-138-ESML-COMMON-SDC-DEV-001"
VNET = RG + "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001"
NIC = RG + "/providers/Microsoft.Network/networkInterfaces/PEND-ACR-NIC"
OTHER_NIC = RG + "/providers/Microsoft.Network/networkInterfaces/PEND-KV-NIC"
PE = RG + "/providers/Microsoft.Network/privateEndpoints/pend-acr"


def vnet(*nics, prefix="10.0.0.0/24", endpoints=(PE,)):
    subnet = {"id": VNET + "/subnets/snet-esml-cmn-001", "name": "snet-esml-cmn-001",
              "properties": {"addressPrefix": prefix,
                             "ipConfigurations": [{"id": nic + "/ipConfigurations/PRIVATEENDPOINTIPCONFIG.1"} for nic in nics],
                             "privateEndpoints": [{"id": endpoint} for endpoint in endpoints]}}
    return {"id": VNET, "type": "Microsoft.Network/virtualNetworks", "properties": {"subnets": [subnet]}}


def compare(live, frozen, removed):
    gone = {value.lower() for value in removed}
    return (fl.fingerprint_body(fl._without_deleted_children(fl._without_removed_backlinks(live, gone), gone))
            == fl.fingerprint_body(fl._without_deleted_children(fl._without_removed_backlinks(frozen, gone), gone)))


def test_an_embedded_subnet_that_lost_a_deleted_nic_and_endpoint_matches():
    assert compare(vnet(OTHER_NIC, endpoints=()), vnet(NIC, OTHER_NIC), {NIC, PE})


def test_a_back_reference_to_a_resource_still_present_or_a_changed_subnet_still_counts():
    assert not compare(vnet(endpoints=()), vnet(NIC, OTHER_NIC), {NIC, PE})
    assert not compare(vnet(OTHER_NIC, prefix="10.0.9.0/24", endpoints=()), vnet(NIC, OTHER_NIC), {NIC, PE})
