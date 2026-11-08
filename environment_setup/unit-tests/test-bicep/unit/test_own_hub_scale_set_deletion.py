"""Deleting an added scale set that joined the factory's own access hub (own-hub-spoke-attachments-v1), offline only.

Shape: aif-154 (contract own-hub-added-scale-set, 2026-11-08). A Standalone factory with its own hub: the bootstrap
scale set DEV001 holds the hub in its common group aif-154-esml-common-sdc-dev-001 (VNet vnt-esmlcmn-sdc-dev-001,
VPN gateway, every private DNS zone). The added scale set DEV002 joined it (purple 75887c83): its common VNet - the same
name, another group - peers to the hub VNet, its private endpoints' zone groups name the hub group's zones, and the hub
side holds a peering and zone links to the spoke VNet.

ESAF Scenario 5 (delete-scale-set DEV002) froze every cross-group reference as a dependency and refused the hub's VNet
and zones as unknown-resource-dependency. Now a reference of an attachment kind into a group that live tags prove a
sibling scale set of the same factory is an own-hub attachment: not a blocker. The deletion then removes only the hub
side's peerings and links that target the deleted spoke VNet, after the spoke is gone (Azure clears a deleted VNet's
zone links itself and leaves the hub peering Disconnected). The hub VNet, gateway, zones and every other network's
links stay; every other cross-group reference keeps refusing.

Microsoft Learn (checked 2026-11-08): deleting a VNet clears its private DNS zone links (dns-faq-private, "What
happens when we delete a linked virtual network"); deleting one peering link leaves the other Disconnected
(virtual-networks-faq); a policy exemption is removed with its parent scope (policy exemption-structure).
"""

import copy

import pytest

from .test_factory_lifecycle import fl, manifest, seal, setup_execute, GROUP, SUB, workspace, no_real_services
from .test_selective_project_deletion import ProjectCloud, tagged


FACTORY = "aif-154"
SPOKE_OWNER = {"factory_id": FACTORY, "scaleset_id": "DEV002"}
HUB_OWNER = {"factory_id": FACTORY, "scaleset_id": "DEV001"}
DEPLOYMENT = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
SPOKE_RG = f"/subscriptions/{SUB}/resourceGroups/aif-154-esml-common-sdc-dev-002"
HUB_RG = f"/subscriptions/{SUB}/resourceGroups/aif-154-esml-common-sdc-dev-001"
SPOKE_NET, HUB_NET = SPOKE_RG + "/providers/Microsoft.Network", HUB_RG + "/providers/Microsoft.Network"
SPOKE_VNET = SPOKE_NET + "/virtualNetworks/vnt-esmlcmn-sdc-dev-001"
HUB_VNET = HUB_NET + "/virtualNetworks/vnt-esmlcmn-sdc-dev-001"
OTHER_VNET = (f"/subscriptions/{SUB}/resourceGroups/aif-777-esml-common-sdc-dev-001"
              "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001")
SPOKE_SUBNET = SPOKE_VNET + "/subnets/snet-esml-cmn-001"
SPOKE_PEERING = SPOKE_VNET + "/virtualNetworkPeerings/peer-vnt-esmlcmn-sdc-dev-001-hub"
ENDPOINT = SPOKE_NET + "/privateEndpoints/pend-kv-cmn-002"
ZONE_GROUP = ENDPOINT + "/privateDnsZoneGroups/default"
GATEWAY = HUB_NET + "/virtualNetworkGateways/vpngw-aif-154"
HUB_PEERING = HUB_VNET + "/virtualNetworkPeerings/peer-vnt-esmlcmn-sdc-dev-001-3f2a9c1d"
OTHER_PEERING = HUB_VNET + "/virtualNetworkPeerings/peer-other-factory"
VAULT_ZONE = HUB_NET + "/privateDnsZones/privatelink.vaultcore.azure.net"
BLOB_ZONE = HUB_NET + "/privateDnsZones/privatelink.blob.core.windows.net"
VAULT_HUB_LINK = VAULT_ZONE + "/virtualNetworkLinks/link-hub"
VAULT_SPOKE_LINK = VAULT_ZONE + "/virtualNetworkLinks/link-spoke-002"
BLOB_SPOKE_LINK = BLOB_ZONE + "/virtualNetworkLinks/link-spoke-002"
BLOB_OTHER_LINK = BLOB_ZONE + "/virtualNetworkLinks/link-other-factory"
SPOKE_LINKS = sorted(value.lower() for value in (HUB_PEERING, VAULT_SPOKE_LINK, BLOB_SPOKE_LINK))
EXEMPTION = SPOKE_RG + "/providers/Microsoft.Authorization/policyExemptions/aif-dns-0123456789abcdef0123456789abcdef"
TYPES = {"microsoft.network": ["virtualNetworks", "virtualNetworks/subnets", "virtualNetworks/virtualNetworkPeerings",
                               "privateEndpoints", "privateEndpoints/privateDnsZoneGroups", "privateDnsZones",
                               "privateDnsZones/virtualNetworkLinks", "virtualNetworkGateways"],
         "microsoft.authorization": ["roleAssignments", "policyExemptions"]}


def untagged(identifier, kind, properties=None):
    return {"id": identifier, "type": kind, "etag": '"original"', "tags": None, "properties": properties or {}}


def peering(identifier, remote):
    return untagged(identifier, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
                    {"remoteVirtualNetwork": {"id": remote}, "peeringState": "Connected",
                     "allowForwardedTraffic": True})


def link(identifier, remote):
    return untagged(identifier, "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                    {"virtualNetwork": {"id": remote}, "registrationEnabled": False})


class OwnHubCloud(ProjectCloud):
    """Both scale sets' common groups; only DEV002's group is in the deletion's scopes."""

    def __init__(self, hub_tags=HUB_OWNER, exemption=None):
        super().__init__()
        self.auto_clear_links = True
        subnet = untagged(SPOKE_SUBNET, "Microsoft.Network/virtualNetworks/subnets", {"addressPrefix": "10.2.0.0/24"})
        spoke = peering(SPOKE_PEERING, HUB_VNET)
        spoke["properties"]["useRemoteGateways"] = True
        hub_side = [peering(HUB_PEERING, SPOKE_VNET), peering(OTHER_PEERING, OTHER_VNET)]
        self.bodies = {
            SPOKE_RG.lower(): tagged(SPOKE_RG, "Microsoft.Resources/resourceGroups", SPOKE_OWNER),
            SPOKE_VNET.lower(): tagged(SPOKE_VNET, "Microsoft.Network/virtualNetworks", SPOKE_OWNER, {
                "subnets": [copy.deepcopy(subnet)], "virtualNetworkPeerings": [copy.deepcopy(spoke)]}),
            SPOKE_SUBNET.lower(): subnet,
            SPOKE_PEERING.lower(): spoke,
            ENDPOINT.lower(): tagged(ENDPOINT, "Microsoft.Network/privateEndpoints", SPOKE_OWNER,
                                     {"subnet": {"id": SPOKE_SUBNET}}),
            ZONE_GROUP.lower(): untagged(ZONE_GROUP, "Microsoft.Network/privateEndpoints/privateDnsZoneGroups", {
                "privateDnsZoneConfigs": [{"name": "privatelink-vaultcore-azure-net",
                                           "properties": {"privateDnsZoneId": VAULT_ZONE}}]}),
            HUB_RG.lower(): ({"id": HUB_RG, "type": "Microsoft.Resources/resourceGroups", "tags": None, "properties": {}}
                             if hub_tags is None else tagged(HUB_RG, "Microsoft.Resources/resourceGroups", hub_tags)),
            HUB_VNET.lower(): untagged(HUB_VNET, "Microsoft.Network/virtualNetworks", {
                "subnets": [], "virtualNetworkPeerings": copy.deepcopy(hub_side)}),
            GATEWAY.lower(): untagged(GATEWAY, "Microsoft.Network/virtualNetworkGateways", {"gatewayType": "Vpn"}),
            VAULT_ZONE.lower(): untagged(VAULT_ZONE, "Microsoft.Network/privateDnsZones"),
            BLOB_ZONE.lower(): untagged(BLOB_ZONE, "Microsoft.Network/privateDnsZones"),
        }
        for body in hub_side:
            self.bodies[body["id"].lower()] = body
        for identifier, remote in ((VAULT_HUB_LINK, HUB_VNET), (VAULT_SPOKE_LINK, SPOKE_VNET),
                                   (BLOB_SPOKE_LINK, SPOKE_VNET), (BLOB_OTHER_LINK, OTHER_VNET)):
            self.bodies[identifier.lower()] = link(identifier, remote)
        if exemption is not None:
            self.bodies[EXEMPTION.lower()] = {
                "id": EXEMPTION, "type": "Microsoft.Authorization/policyExemptions", "properties": {
                    "policyAssignmentId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyAssignments/dns",
                    "exemptionCategory": "Waiver", "metadata": exemption}}

    def provider_schema(self, namespace):
        types = TYPES.get(namespace.lower(), [])
        return {"resourceTypes": [{"resourceType": kind, "apiVersions": ["2024-05-01"]} for kind in types]}

    def collection(self, path, api_version, extension=False):
        prefix = path.lower() + "/"
        rows = [copy.deepcopy(body) for key, body in sorted(self.bodies.items())
                if key.startswith(prefix) and "/" not in key[len(prefix):]]
        assert not extension or path.lower().endswith("/providers/microsoft.authorization/policyexemptions") or not rows
        return rows, None

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        before = set(self.bodies)
        result = super().arm(method, resource_id, api_version, allowed, headers)
        if method == "DELETE":
            gone = before - set(self.bodies)
            for key, body in list(self.bodies.items()):
                properties = body.get("properties") or {}
                remote = str((properties.get("virtualNetwork") or {}).get("id", "")).lower()
                if self.auto_clear_links and remote in gone:
                    del self.bodies[key]  # Azure clears a deleted VNet's zone links
                peers = properties.get("virtualNetworkPeerings")
                if isinstance(peers, list):
                    properties["virtualNetworkPeerings"] = [row for row in peers if row["id"].lower() in self.bodies]
                if str((properties.get("remoteVirtualNetwork") or {}).get("id", "")).lower() in gone:
                    properties["peeringState"] = "Disconnected"
        return result


def spoke_manifest(cloud):
    """The delete-scale-set manifest pink prepares for DEV002: its one enrolled common group, no projects."""
    document = manifest()
    document.pop("deletion")
    document["target"].update(factory_id=FACTORY, scaleset_id="DEV002", environment="dev", suffix="002",
                              project_ids=[])
    document["locks"]["scopes"] = [SPOKE_RG]
    document["locks"]["common_dependencies"] = []
    cloud.enrollment["scopes"][SPOKE_RG.lower()] = {
        **copy.deepcopy(cloud.enrollment["scopes"][GROUP.lower()]),
        "common_dependencies": [],
        "target": {key: document["target"][key] for key in (
            "factory_id", "scaleset_id", "environment", "tenant_id", "subscription_id", "prefix", "region", "suffix")}}
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    return document


def frozen(cloud=None, **changes):
    cloud = cloud or OwnHubCloud(**changes)
    document = spoke_manifest(cloud)
    document["deletion"] = fl.freeze_deletion_inventory(cloud, document, {})
    return seal(document), cloud


def locks(cloud):
    return type("Locks", (), {"authorize": lambda self, value: None, "assert_held": lambda self: None,
                              "enrollment": cloud.enrollment})()


def delete(document, cloud):
    receipt = {"deleted_resources": []}
    fl.delete_owned_groups(cloud, locks(cloud), document, receipt, lambda: None, sleep=lambda _: None)
    return receipt


HUB_KEPT = [HUB_RG, HUB_VNET, GATEWAY, VAULT_ZONE, BLOB_ZONE, VAULT_HUB_LINK, OTHER_PEERING, BLOB_OTHER_LINK]


def test_own_hub_attachments_do_not_block_freezing_the_spoke_scale_set():
    document, cloud = frozen()
    fl.validate_manifest(document)
    data = document["deletion"]
    assert data["own_hub"] == {
        "contract": "own-hub-spoke-attachments-v1", "resource_group_ids": [HUB_RG.lower()],
        "attachments": sorted([HUB_VNET.lower(), VAULT_ZONE.lower()]),
        "links": [{"id": identifier, "type": fl.resource_type_from_id(identifier),
                   "api_version": "2024-05-01" if "/virtualnetworkpeerings/" in identifier else "2024-06-01",
                   "remote_virtual_network_id": SPOKE_VNET.lower()} for identifier in SPOKE_LINKS]}
    # Only DEV002's group is inventoried for deletion; nothing of the hub group is.
    assert {row["id"].lower() for row in data["resources"]} == {
        value.lower() for value in (SPOKE_VNET, SPOKE_SUBNET, SPOKE_PEERING, ENDPOINT, ZONE_GROUP)}
    assert all(row["delete"] for row in data["resources"] + data["resource_groups"])
    assert not cloud.deleted


def test_delete_scale_set_removes_only_the_hub_side_links_to_the_spoke_after_the_spoke():
    document, cloud = frozen()
    receipt = delete(document, cloud)
    # The spoke group goes first; then only the hub peering is left to cut - Azure cleared the zone links.
    assert cloud.deleted == [SPOKE_RG, HUB_PEERING.lower()]
    assert receipt["deleted_hub_links"] == SPOKE_LINKS and receipt["hub_unlink_complete"] is True
    assert {value.lower() for value in receipt["deleted_resources"]} == {
        value.lower() for value in (SPOKE_RG, SPOKE_VNET, SPOKE_SUBNET, SPOKE_PEERING, ENDPOINT, ZONE_GROUP)}
    for identifier in HUB_KEPT:
        assert identifier.lower() in cloud.bodies, identifier
    assert [row["id"] for row in cloud.bodies[HUB_VNET.lower()]["properties"]["virtualNetworkPeerings"]] == [
        OTHER_PEERING]


def test_zone_links_azure_did_not_clear_are_deleted_too():
    cloud = OwnHubCloud()
    cloud.auto_clear_links = False
    document, cloud = frozen(cloud)
    receipt = delete(document, cloud)
    assert cloud.deleted == [SPOKE_RG, *SPOKE_LINKS]
    assert receipt["deleted_hub_links"] == SPOKE_LINKS
    for identifier in HUB_KEPT:
        assert identifier.lower() in cloud.bodies, identifier


def test_the_runtime_cohort_deletes_the_spoke_and_unlinks_the_hub(monkeypatch, workspace):
    document, cloud = frozen()
    cloud.calls.clear()
    source, execution, path = setup_execute(monkeypatch, workspace)
    result = fl.execute_cohort([document], source, execution, path, cloud_factory=lambda value: cloud)
    assert result["status"] == "succeeded" and not result["lock_retained"], result.get("error_code")
    assert result["children"][0]["deleted_hub_links"] == SPOKE_LINKS
    assert cloud.deleted == [SPOKE_RG, HUB_PEERING.lower()]


@pytest.mark.parametrize("hub_tags", [
    None,                                                   # untagged: no proof the hub group is the factory's
    {"factory_id": "aif-999", "scaleset_id": "DEV001"},     # another factory's hub
    {"factory_id": FACTORY, "scaleset_id": "DEV002"},       # not a sibling scale set
    {**HUB_OWNER, "project_id": "001"},                     # a project's group, never a hub
], ids=["untagged", "other-factory", "same-scale-set", "project-group"])
def test_references_into_an_unproven_group_still_block(hub_tags):
    with pytest.raises(fl.Blocked, match="^unknown-resource-dependency$"):
        frozen(hub_tags=hub_tags)


def test_a_shared_hub_group_still_blocks():
    cloud = OwnHubCloud()
    cloud.bodies[HUB_RG.lower()]["tags"]["aifactory.shared"] = "true"
    with pytest.raises(fl.Blocked, match="^unknown-resource-dependency$"):
        frozen(cloud)


def test_a_non_attachment_reference_into_the_hub_group_still_blocks():
    cloud = OwnHubCloud()
    # A private endpoint in the hub VNet's subnet is no own-hub attachment kind.
    cloud.bodies[ENDPOINT.lower()]["properties"]["subnet"] = {"id": HUB_VNET + "/subnets/snet-hub"}
    with pytest.raises(fl.Blocked, match="^unknown-resource-dependency$"):
        frozen(cloud)


def tamper_remote(hub):
    hub["links"][0]["remote_virtual_network_id"] = OTHER_VNET.lower()


def tamper_outside(hub):
    hub["links"][0]["id"] = OTHER_VNET.lower() + "/virtualnetworkpeerings/peer-x"


def tamper_attachment(hub):
    hub["attachments"] = sorted([*hub["attachments"], BLOB_ZONE.lower()])


def tamper_group(hub):
    hub["resource_group_ids"] = [SPOKE_RG.lower()]


def tamper_type(hub):
    hub["links"][0]["type"] = "microsoft.network/virtualnetworks"


@pytest.mark.parametrize("tamper", [tamper_remote, tamper_outside, tamper_attachment, tamper_group, tamper_type])
def test_a_tampered_own_hub_plan_is_refused(tamper):
    document, cloud = frozen()
    tamper(document["deletion"]["own_hub"])
    with pytest.raises(fl.Blocked, match="^own-hub-attachments-invalid$"):
        fl.validate_manifest(seal(document))


def test_dropping_the_own_hub_plan_restores_the_refusal():
    document, cloud = frozen()
    document["deletion"].pop("own_hub")
    with pytest.raises(fl.Blocked, match="^unknown-resource-dependency$"):
        fl.validate_manifest(seal(document))


def test_hub_group_ownership_change_blocks_before_any_delete():
    document, cloud = frozen()
    cloud.bodies[HUB_RG.lower()]["tags"]["aifactory.factory_id"] = "aif-999"
    with pytest.raises(fl.Blocked, match="^own-hub-group-ownership-changed$"):
        delete(document, cloud)
    assert not cloud.deleted


def test_missing_peering_delete_permission_blocks_the_freeze():
    cloud = OwnHubCloud()
    cloud.permissions = False
    with pytest.raises(fl.Blocked, match="^project-delete-permission-required$"):
        frozen(cloud)


def test_a_hub_link_that_changed_its_remote_is_not_deleted():
    document, cloud = frozen()
    cloud.bodies[HUB_PEERING.lower()]["properties"]["remoteVirtualNetwork"]["id"] = OTHER_VNET
    with pytest.raises(fl.Blocked, match="^own-hub-link-changed$"):
        delete(document, cloud)
    assert cloud.deleted == [SPOKE_RG]


def test_a_scale_set_without_hub_references_freezes_as_before():
    cloud = OwnHubCloud()
    spoke = cloud.bodies[SPOKE_VNET.lower()]["properties"]
    spoke["virtualNetworkPeerings"] = []
    del cloud.bodies[SPOKE_PEERING.lower()]
    cloud.bodies[ZONE_GROUP.lower()]["properties"]["privateDnsZoneConfigs"] = []
    document, cloud = frozen(cloud)
    assert "own_hub" not in document["deletion"]
    receipt = delete(document, cloud)
    assert cloud.deleted == [SPOKE_RG] and "deleted_hub_links" not in receipt


DNS_EXEMPTION = {"contract": "aifactory-dns-policy-exemption-v1", "factory_id": FACTORY, "scale_set_id": "DEV002"}


def test_the_scale_sets_dns_policy_exemption_leaves_with_its_group():
    document, cloud = frozen(exemption=DNS_EXEMPTION)
    rows = {row["id"].lower(): row for row in document["deletion"]["resources"]}
    row = rows[EXEMPTION.lower()]
    assert row["delete"] is True and row["ownership_source"] == "managed-parent"
    assert row["managed_parent_id"] == SPOKE_RG.lower()
    receipt = delete(document, cloud)
    assert cloud.deleted == [SPOKE_RG, HUB_PEERING.lower()]
    assert EXEMPTION.lower() in {value.lower() for value in receipt["deleted_resources"]}


@pytest.mark.parametrize("metadata", [
    {**DNS_EXEMPTION, "scale_set_id": "DEV001"},
    {**DNS_EXEMPTION, "factory_id": "aif-999"},
    {**DNS_EXEMPTION, "contract": "someone-elses-waiver"},
    None,
], ids=["other-scale-set", "other-factory", "other-contract", "no-metadata"])
def test_any_other_policy_exemption_still_needs_an_ownership_record(metadata):
    with pytest.raises(fl.Blocked, match="^known-child-ownership-record-required$"):
        frozen(exemption=metadata if metadata is not None else {})


def test_whole_factory_deletion_accepts_the_spokes_cross_scale_references():
    """Scenario 6, the DEV002 stage: its peering and zone groups name the hub group, which DEV001's stage deletes."""
    cloud = OwnHubCloud(exemption=DNS_EXEMPTION)
    document = spoke_manifest(cloud)
    document["route"].update(scoped_contract=1, auth_namespace="factory-dev",
                             runner={"kind": "self-hosted", "os": "linux", "pool": "aifactory-private"})
    document["identity"]["deployment_object_id"] = DEPLOYMENT
    cloud.enrollment["writers"]["writer-a"].update(
        auth_namespace="factory-dev", runner=document["route"]["runner"], deployment_object_id=DEPLOYMENT)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, [])
    fl.validate_manifest(seal(document))
    rows = {row["id"].lower(): row for row in document["deletion"]["resources"] + document["deletion"]["resource_groups"]}
    assert all(rows[value.lower()]["delete"] for value in (
        SPOKE_RG, SPOKE_VNET, SPOKE_PEERING, ENDPOINT, ZONE_GROUP, EXEMPTION)), {
        key: row.get("retention_reason") for key, row in rows.items() if not row["delete"]}
    assert not any(key.startswith(HUB_RG.lower()) for key in rows)


def test_the_own_hubs_links_to_a_joined_spoke_are_not_foreign_to_the_factory():
    """Scenario 6, the DEV001 stage: the hub VNet's peering and zone links name DEV002's VNet, a factory group."""
    cloud = OwnHubCloud()
    hub = {"resource_group_ids": [HUB_RG.lower()], "factory_resource_groups": sorted([HUB_RG.lower(), SPOKE_RG.lower()])}
    bodies = {key: body for key, body in cloud.bodies.items()
              if key.startswith(HUB_RG.lower()) and key not in (OTHER_PEERING.lower(), BLOB_OTHER_LINK.lower())}
    fl.factory_deletion_module().verify_access_hub_network(hub, bodies)
    with pytest.raises(fl.Blocked, match="^factory-delete-access-hub-foreign-link$"):
        fl.factory_deletion_module().verify_access_hub_network({**hub, "factory_resource_groups": [HUB_RG.lower()]},
                                                               bodies)
