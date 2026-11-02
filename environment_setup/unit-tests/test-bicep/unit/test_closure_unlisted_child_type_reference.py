"""Offline: a reference to a child type the provider schema leaves out is read at its parent type's api-version.

aif-138 (2026-11-02): Microsoft.KeyVault lists no vaults/privateEndpointConnections type. A vault's own connections are
read at the vault's version, but after the resumed factory deletion deleted kv-cmnadmdev's connection, the private
endpoint's privateLinkServiceProxies still named it. The walk reached it from Microsoft.Network, had no same-namespace
parent version and stopped the next prepare with resource-api-version-not-discoverable.
"""

import pytest

from .test_resource_closure_parallel_reads import API, InventoryCloud, collect, fl


@pytest.fixture
def unlisted(monkeypatch):
    # The provider's operations still read the type (so it is a resource); only its schema leaves it out, as Key Vault's.
    original = InventoryCloud.provider_schema

    def schema(self, namespace):
        result = original(self, namespace)
        result["resourceTypes"] = [row for row in result["resourceTypes"]
                                   if row["resourceType"].lower() != "vaults/privateendpointconnections"]
        return result

    monkeypatch.setattr(InventoryCloud, "provider_schema", schema)


@pytest.mark.parametrize("workers", [None, 8])
def test_a_cross_namespace_reference_to_an_unlisted_child_type_uses_its_parent_type_version(unlisted, workers):
    cloud = InventoryCloud(workers=workers)
    first = cloud.groups[0]
    vault = first + "/providers/Microsoft.KeyVault/vaults/kv-cmnadmdev"
    cloud.add(vault)
    gone = vault + "/privateEndpointConnections/pend-kv-cmnadmdev"
    proxy_holder = first + "/providers/Microsoft.Network/networkInterfaces/pend-kv-cmnadmdev-nic"
    cloud.add(proxy_holder, {"privateLinkServiceConnection": {"id": gone}})
    closure, bodies = collect(cloud)
    assert gone.lower() not in bodies and gone.lower() in closure["references"][proxy_holder.lower()]
    assert [call[2] for call in cloud.calls if call[:2] == ("arm", gone.lower())] == [API["microsoft.keyvault/vaults"]]


def test_an_unlisted_type_with_no_listed_parent_type_still_blocks(monkeypatch):
    original = InventoryCloud.provider_schema

    def schema(self, namespace):
        result = original(self, namespace)
        if namespace.lower() == "microsoft.keyvault":
            result["resourceTypes"] = [row for row in result["resourceTypes"] if "/" not in row["resourceType"]
                                       and row["resourceType"].lower() != "vaults"]
        return result

    monkeypatch.setattr(InventoryCloud, "provider_schema", schema)
    cloud = InventoryCloud()
    first = cloud.groups[0]
    gone = first + "/providers/Microsoft.KeyVault/vaults/kv-cmnadmdev/privateEndpointConnections/pend-kv"
    holder = first + "/providers/Microsoft.Network/networkInterfaces/nic-unknown"
    cloud.add(holder, {"ref": {"id": gone}})
    with pytest.raises(fl.Blocked, match="resource-api-version-not-discoverable"):
        collect(cloud)
