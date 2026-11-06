"""Deletion ownership: the network interface Azure manages for a private endpoint is owned through that endpoint.

aif-145 Scenario 6 (2026-11-04): two private endpoints (the hand-made seed vault endpoint and a project's Cosmos DB
endpoint) were tagged after the fact, but Azure refuses any write to their NICs (CannotModifyNicAttachedToPrivateEndpoint),
so the NICs stay untagged and delete-factory refused them as untagged top-level resources. Azure creates, owns and
deletes such a NIC with its endpoint: a NIC whose properties.privateEndpoint names an endpoint in its own group, which
lists the NIC back, is owned through that endpoint. Any other untagged NIC is still never adopted.
"""

import copy

import pytest

from .test_factory_lifecycle import fl, GROUP, OWNER
from .test_factory_deletion_pipeline import factory_prepared
from .test_selective_project_deletion import tagged


PE = GROUP + "/providers/Microsoft.Network/privateEndpoints/cosmos-pend"
NIC = GROUP + "/providers/Microsoft.Network/networkInterfaces/cosmos-pend.nic.40076cdc"
IPCONFIG = NIC + "/ipConfigurations/privateEndpointIpConfig.a49125ae"


def with_endpoint(nic_endpoint=PE, listed=True):
    document, cloud, projects = factory_prepared()
    cloud.bodies[PE.lower()] = tagged(PE, "Microsoft.Network/privateEndpoints", OWNER,
                                      {"networkInterfaces": [{"id": NIC}] if listed else []})
    cloud.bodies[NIC.lower()] = {"id": NIC, "type": "Microsoft.Network/networkInterfaces", "etag": '"n"',
                                 "properties": {"privateEndpoint": {"id": nic_endpoint} if nic_endpoint else None,
                                                "ipConfigurations": [{"id": IPCONFIG}]}}
    cloud.bodies[IPCONFIG.lower()] = {"id": IPCONFIG, "type": "Microsoft.Network/networkInterfaces/ipConfigurations",
                                      "etag": '"n"', "properties": {"privateIPAddress": "10.0.0.4"}}
    schema, collection = cloud.provider_schema, cloud.collection

    def provider_schema(namespace):
        value = schema(namespace)
        if namespace.lower() == "microsoft.network":
            value = {"resourceTypes": [*value["resourceTypes"], *[
                {"resourceType": kind, "apiVersions": ["2024-05-01"]}
                for kind in ("privateEndpoints", "networkInterfaces", "networkInterfaces/ipConfigurations")]]}
        return value

    def child_collection(path, api_version, extension=False):
        if path.lower().endswith("/ipconfigurations"):
            return [copy.deepcopy(body) for key, body in cloud.bodies.items() if key.startswith(path.lower() + "/")], None
        return collection(path, api_version, extension)
    cloud.provider_schema, cloud.collection = provider_schema, child_collection
    unsealed = copy.deepcopy(document)
    unsealed.pop("deletion")
    return unsealed, cloud, projects


def test_a_private_endpoints_managed_nic_is_owned_through_the_endpoint():
    document, cloud, projects = with_endpoint()
    data = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)
    rows = {item["id"].lower(): item for item in data["resources"]}
    nic = rows[NIC.lower()]
    assert nic["ownership_source"] == "managed-parent" and nic["managed_parent_id"] == PE.lower()
    assert nic["owner"] == OWNER and nic["delete"] is True
    assert rows[IPCONFIG.lower()]["managed_parent_id"] == NIC.lower()


@pytest.mark.parametrize("nic_endpoint, listed", [
    (None, True),                                                             # a plain untagged NIC
    (PE, False),                                                              # the endpoint does not list it back
    (PE.replace(GROUP, GROUP + "-other"), True),                              # an endpoint in another group
])
def test_any_other_untagged_nic_is_never_adopted(nic_endpoint, listed):
    document, cloud, projects = with_endpoint(nic_endpoint, listed)
    with pytest.raises(fl.Blocked):
        fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects)


def test_the_scale_set_freeze_owns_the_managed_nic_through_its_endpoint():
    bodies = {PE.lower(): tagged(PE, "Microsoft.Network/privateEndpoints", OWNER, {"networkInterfaces": [{"id": NIC}]}),
              NIC.lower(): {"id": NIC, "type": "Microsoft.Network/networkInterfaces",
                            "properties": {"privateEndpoint": {"id": PE}}}}
    assert fl.managed_parent_id(NIC, bodies, OWNER) == PE.lower()
