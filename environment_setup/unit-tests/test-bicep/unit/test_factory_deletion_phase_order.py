"""Whole-factory deletion phases: a private endpoint may outlive the service it connects to.

aif-138 (2026-11-01): the factory deletion freeze refused with factory-delete-phase-dependency-conflict. The common
group's private endpoints (network, phase 3) reference their Key Vault, storage account or registry (phase 2), so
"dependent no later than its dependency" contradicted "services before network". Deleting the service only
disconnects its endpoint; the endpoint still leaves in the network phase.
"""

import pytest

from .test_factory_lifecycle import fl, COMMON


VAULT = COMMON + "/providers/Microsoft.KeyVault/vaults/kv-cmn"
CONNECTION = VAULT + "/privateEndpointConnections/pend-kv"
ENDPOINT = COMMON + "/providers/Microsoft.Network/privateEndpoints/pend-kv"
PROXY = ENDPOINT + "/privateLinkServiceProxies/pend-kv.proxy"
NIC = COMMON + "/providers/Microsoft.Network/networkInterfaces/runner-nic"
VM = COMMON + "/providers/Microsoft.Compute/virtualMachines/runner"


def row(identifier, depends_on=()):
    return {"id": identifier, "type": fl.resource_type_from_id(identifier), "delete": True, "depends_on": list(depends_on)}


def test_a_private_endpoint_leaves_after_the_service_it_connects_to():
    ordered = fl.factory_deletion_module().ordered_resources(
        [row(VAULT), row(CONNECTION), row(ENDPOINT, [VAULT]), row(PROXY, [CONNECTION])])
    order = [item["id"] for item in ordered]
    assert order.index(VAULT) < order.index(ENDPOINT) and order.index(CONNECTION) < order.index(PROXY)


def test_any_other_network_resource_that_needs_a_later_service_still_conflicts():
    with pytest.raises(fl.Blocked, match="^factory-delete-phase-dependency-conflict$"):
        fl.factory_deletion_module().ordered_resources([row(VM), row(NIC, [VM])])
