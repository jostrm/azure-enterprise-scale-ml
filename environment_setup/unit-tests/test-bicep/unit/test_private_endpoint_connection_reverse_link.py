"""A resource's privateEndpointConnections name the endpoints that connect to it: dependents, never dependencies.

aif-145 (2026-11-04): a common resource (storage, Key Vault, registry) that a project's private endpoint connects to
listed that endpoint in properties.privateEndpointConnections[].properties.privateEndpoint. Dependency planning read it
as a dependency of the common resource, so the factory deletion freeze refused with
factory-delete-common-before-project-dependency, although the endpoint is deleted first (with its project).
"""

from .test_factory_lifecycle import fl

SUB = "/subscriptions/11111111-1111-1111-1111-111111111111/resourcegroups/"
VAULT = SUB + "common/providers/microsoft.keyvault/vaults/kv-common"
ENDPOINT = SUB + "project001/providers/microsoft.network/privateendpoints/pend-kv-common"
SUBNET = SUB + "common/providers/microsoft.network/virtualnetworks/vnet/subnets/snet"


def body(**properties):
    return {"id": VAULT, "type": "Microsoft.KeyVault/vaults", "properties": properties}


def test_a_connected_endpoint_is_not_a_dependency_of_the_resource_it_connects_to():
    connection = {"id": VAULT + "/privateEndpointConnections/pend-kv-common.1",
                  "properties": {"privateEndpoint": {"id": ENDPOINT},
                                 "privateLinkServiceConnectionState": {"status": "Approved"}}}
    assert fl.project_resource_dependencies(body(privateEndpointConnections=[connection])) == []


def test_other_references_of_the_same_resource_stay_dependencies():
    rule = {"id": SUBNET}
    value = body(privateEndpointConnections=[{"id": VAULT + "/privateEndpointConnections/x",
                                              "properties": {"privateEndpoint": {"id": ENDPOINT}}}],
                 networkAcls={"virtualNetworkRules": [rule]})
    assert fl.project_resource_dependencies(value) == [SUBNET]


DASHBOARD = SUB + "common/providers/microsoft.portal/dashboards/aifactory-aif-145-sdc-001-dash-01"
FOUNDRY = SUB + "project001/providers/microsoft.cognitiveservices/accounts/aif2-p001"


def test_a_portal_dashboard_tile_never_makes_a_shown_resource_a_dependency():
    # aif-145 (2026-11-04): the factory dashboard in the common group charts project resources; that read as
    # factory-delete-common-before-project-dependency. A tile is a display link, deleted or dangling either way.
    dashboard = {"id": DASHBOARD, "type": "Microsoft.Portal/dashboards", "properties": {"lenses": [{"parts": [
        {"metadata": {"inputs": [{"name": "ResourceId", "value": FOUNDRY}]}}]}]}}
    assert fl.project_resource_dependencies(dashboard) == []
    other = {"id": VAULT, "type": "Microsoft.KeyVault/vaults", "properties": {"note": {"id": FOUNDRY}}}
    assert fl.project_resource_dependencies(other) == [FOUNDRY]
