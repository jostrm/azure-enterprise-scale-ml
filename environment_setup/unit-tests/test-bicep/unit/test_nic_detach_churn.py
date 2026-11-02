"""Offline: a NIC's VM-attachment state follows its VM; detaching it never blocks.

aif-138 (2026-11-02, run19): the factory deletion's common stage deleted the runner VM. Network RP then left out the
runner NIC's properties.primary and added properties.enableGuestRdma false, and the retained-parent check stopped with
project-retained-parent-changed. IP configurations, subnet and NSG still count.
"""

from .test_factory_lifecycle import fl

NIC = ("/subscriptions/f0fe8b33-73bf-41e4-9997-e3920d793c06/resourceGroups/aif-138-esml-common-sdc-dev-001"
       "/providers/Microsoft.Network/networkInterfaces/runner-gha-sdc-dev-001-nic")


def nic(attached=True, address="10.0.0.4"):
    properties = {"ipConfigurations": [{"id": NIC + "/ipConfigurations/ipconfig1",
                                        "properties": {"privateIPAddress": address}}]}
    properties.update({"primary": True} if attached else {"enableGuestRdma": False})
    return {"id": NIC, "type": "Microsoft.Network/networkInterfaces", "properties": properties}


def test_a_nic_detached_from_its_deleted_vm_keeps_its_fingerprint():
    assert fl.resource_digest(nic(attached=False)) == fl.resource_digest(nic())


def test_a_changed_address_still_changes_the_fingerprint():
    assert fl.resource_digest(nic(address="10.0.0.9")) != fl.resource_digest(nic())
