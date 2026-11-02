"""Offline: a NIC's IP configurations carry the NIC's etag, which rolls on its own; a changed resource is named.

aif-138 (2026-11-01): the whole-factory deletion's project stage stopped with project-resource-instance-changed
after its first deletion. The only drift between the frozen review and the live closure was the runner NIC's
etag, copied into the NIC body's ipConfigurations[].etag and into the ipConfigurations child resource; the NIC's
own etag was already left out. The receipt named no resource, so the drift took a field-level diff to find.
"""

import pytest

from .test_factory_lifecycle import fl
from .test_resource_fingerprint_churn import NIC, nic
from .test_selective_project_deletion import prepared


def ipconfig(etag='W/"1"', subnet="snet-esml-cmn-001"):
    return {"id": NIC + "/ipConfigurations/private", "name": "private", "etag": etag,
            "type": "Microsoft.Network/networkInterfaces/ipConfigurations",
            "properties": {"privateIPAllocationMethod": "Dynamic", "privateIPAddress": "10.0.0.4",
                           "subnet": {"id": "/subnets/" + subnet}}}


def nic_with(etag):
    body = nic(etag=etag)
    body["properties"]["ipConfigurations"][0].update({"id": NIC + "/ipConfigurations/private", "etag": etag})
    return body


def test_an_etag_roll_leaves_the_nic_and_its_ip_configuration_fingerprints_unchanged():
    assert fl.resource_digest(nic_with('W/"2"')) == fl.resource_digest(nic_with('W/"1"'))
    assert fl.resource_digest(ipconfig('W/"2"')) == fl.resource_digest(ipconfig())
    assert fl.resource_etag(ipconfig(), {"ETag": 'W/"1"'}) is None


def test_a_new_subnet_still_changes_the_ip_configuration_fingerprint():
    assert fl.resource_digest(ipconfig(subnet="snet-other")) != fl.resource_digest(ipconfig())
    moved = nic_with('W/"1"')
    moved["properties"]["ipConfigurations"][0]["properties"]["subnet"]["id"] += "-other"
    assert fl.resource_digest(moved) != fl.resource_digest(nic_with('W/"1"'))


def test_a_changed_project_resource_is_named_in_the_error():
    document, cloud = prepared(True, True)
    # A deletion already ran (an unrelated id), so the per-resource comparison decides rather than the whole closure.
    removed = "/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/gone/providers/a.b/c/d"
    vault = next(key for key in cloud.bodies if key.endswith("/vaults/project-vault"))
    cloud.bodies[vault]["properties"] = {"changed": True}
    with pytest.raises(fl.Blocked, match="^project-resource-instance-changed$") as raised:
        fl.verify_project_inventory(cloud, document, {removed})
    assert raised.value.error_diagnostic == {"resource_id": vault, "failed_comparisons": ["body_hash"]}
