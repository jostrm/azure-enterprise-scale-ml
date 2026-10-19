"""Shared-hub link cleanup for whole-factory deletion (shared-hub-spoke-links-v1), offline only.

Shape: dc-batman4. A hub-connected factory whose Full bootstrap peered its common VNet with,
and DNS-linked it from, the shared connectivity hub aifactory-connectivity in another
subscription that also serves spider. The bootstrap recorded the hub-side peering and DNS
links it created (aif-<hash>). Whole-factory deletion removes only those recorded links whose
remote is a VNet this cohort deletes, and only after that VNet is gone; the hub VNet, zones,
the hub group, spider's links and any unrecorded link always stay.
"""

import copy
import json

import pytest

from .test_factory_lifecycle import fl, GROUP, COMMON, OWNER, RESOURCE, SUB, seal, workspace, no_real_services
from .test_factory_deletion_access_hub import (
    HubCloud, untagged, CORE, VNET, GATEWAY, GATEWAY_IP, GATEWAY_SUBNET, BASTION, BASTION_IP, BASTION_SUBNET,
    ZONE, LINK, NIC, RUNNER, RUNNER_SUBNET, DISK, IDENTITY_ID, PROJECT_SUBNET, hub_document, projects,
)
from .test_selective_project_deletion import VAULT


HUB_SUB = "abababab-abab-4bab-8bab-abababababab"
HUB = f"/subscriptions/{HUB_SUB}/resourceGroups/aifactory-connectivity"
HUB_NET = HUB + "/providers/Microsoft.Network"
HUB_VNET = HUB_NET + "/virtualNetworks/vnet-aifactory-access-hub-sdc-001"
BLOB_ZONE = HUB_NET + "/privateDnsZones/privatelink.blob.core.windows.net"
VAULT_ZONE = HUB_NET + "/privateDnsZones/privatelink.vaultcore.azure.net"
SPIDER_VNET = (f"/subscriptions/{SUB}/resourceGroups/spider-esml-common-sdc-dev-001"
               "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001")
OWN_BLOB_LINK = BLOB_ZONE + "/virtualNetworkLinks/aif-4d8896b66f23"
OWN_VAULT_LINK = VAULT_ZONE + "/virtualNetworkLinks/aif-4d8896b66f23"
OWN_PEERING = HUB_VNET + "/virtualNetworkPeerings/aif-4d8896b66f23"
HUB_SELF_LINK = BLOB_ZONE + "/virtualNetworkLinks/aif-0c0ffee0b0b0"
MANUAL_LINK = VAULT_ZONE + "/virtualNetworkLinks/manual-batman"
SPIDER_LINK = BLOB_ZONE + "/virtualNetworkLinks/aif-5b1de5b1de5b"
SPIDER_PEERING = HUB_VNET + "/virtualNetworkPeerings/aif-5b1de5b1de5b"
SPOKE_PEERING = VNET + "/virtualNetworkPeerings/aif-5eb3f21fdde8"
DNS_LINK_TYPE = "microsoft.network/privatednszones/virtualnetworklinks"
PEERING_TYPE = "microsoft.network/virtualnetworks/virtualnetworkpeerings"
OWN_LINKS = [OWN_BLOB_LINK, OWN_VAULT_LINK, OWN_PEERING]
# A hub-connected bootstrap owns its spoke VNet and private runner, never a VPN gateway or Bastion.
SPOKE_ROOTS = [VNET, NIC, RUNNER, DISK, IDENTITY_ID]


class SharedHubCloud(HubCloud):
    """Factory groups plus a shared connectivity hub that the factory may only unlink from."""

    def __init__(self):
        super().__init__()
        for identifier in (GATEWAY, GATEWAY_IP, GATEWAY_SUBNET, BASTION, BASTION_IP, BASTION_SUBNET, ZONE, LINK):
            self.bodies.pop(identifier.lower())
        spoke = untagged(SPOKE_PEERING, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
                         {"remoteVirtualNetwork": {"id": HUB_VNET}, "peeringState": "Connected"})
        self.bodies[SPOKE_PEERING.lower()] = spoke
        properties = self.bodies[VNET.lower()]["properties"]
        properties["subnets"] = [row for row in properties["subnets"]
                                 if row["id"].lower() in (RUNNER_SUBNET.lower(), PROJECT_SUBNET.lower())]
        properties["virtualNetworkPeerings"] = [copy.deepcopy(spoke)]
        self.bodies[HUB.lower()] = untagged(HUB, "Microsoft.Resources/resourceGroups")
        self.bodies[HUB_VNET.lower()] = untagged(HUB_VNET, "Microsoft.Network/virtualNetworks",
                                                 {"subnets": [], "virtualNetworkPeerings": []})
        for zone in (BLOB_ZONE, VAULT_ZONE):
            self.bodies[zone.lower()] = untagged(zone, "Microsoft.Network/privateDnsZones")
        for identifier, remote in ((OWN_BLOB_LINK, VNET), (OWN_VAULT_LINK, VNET), (HUB_SELF_LINK, HUB_VNET),
                                   (MANUAL_LINK, VNET), (SPIDER_LINK, SPIDER_VNET)):
            self.bodies[identifier.lower()] = untagged(identifier, "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                                                       {"virtualNetwork": {"id": remote}})
        for identifier, remote in ((OWN_PEERING, VNET), (SPIDER_PEERING, SPIDER_VNET)):
            self.bodies[identifier.lower()] = untagged(
                identifier, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
                {"remoteVirtualNetwork": {"id": remote}, "peeringState": "Connected"})
        self.unsupported = set()

    def collection(self, path, api_version, extension=False):
        if path.lower() in self.unsupported:
            return [], "unsupported"
        return super().collection(path, api_version, extension)

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        result = super().arm(method, resource_id, api_version, allowed, headers)
        if method == "DELETE":
            # Like ARM, a deleted peering leaves its VNet's inline peering list.
            for body in self.bodies.values():
                peerings = (body.get("properties") or {}).get("virtualNetworkPeerings")
                if isinstance(peerings, list):
                    body["properties"]["virtualNetworkPeerings"] = [
                        row for row in peerings if row["id"].lower() != resource_id.lower()]
        return result


def link_proof(document, links=None, **changes):
    """What the catalog builds from the consumed bootstrap stage records of this scale set."""
    rows = [{"id": OWN_BLOB_LINK.lower(), "type": DNS_LINK_TYPE, "remote_virtual_network_id": VNET.lower()},
            {"id": OWN_VAULT_LINK.lower(), "type": DNS_LINK_TYPE, "remote_virtual_network_id": VNET.lower()},
            {"id": OWN_PEERING.lower(), "type": PEERING_TYPE, "remote_virtual_network_id": VNET.lower()}]
    proof = {"contract": "shared-hub-spoke-links-v1", "factory_id": document["target"]["factory_id"],
             "scaleset_id": document["target"]["scaleset_id"], "subscription_id": SUB,
             "hub_resource_group_ids": [HUB.lower()],
             "links": sorted(rows if links is None else links, key=lambda row: row["id"]),
             "evidence": {"contract": "consumed-bootstrap-stage-evidence-v1",
                          "workflow_id": "12345678-1234-4234-8234-123456789abc", "record_hash": "d" * 64}}
    proof.update(changes)
    return proof


def batman(cloud=None, with_links=True, roots=SPOKE_ROOTS, **changes):
    document, cloud = hub_document(cloud or SharedHubCloud(), roots=roots, mode="external")
    # The catalog always passes the configured connectivity hub groups as explicit protection.
    document["protected_resource_ids"] = [HUB]
    if with_links:
        document["shared_hub_links"] = link_proof(document, **changes)
    return document, cloud


def freeze(document, cloud):
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects())
    return seal(document)


def rows(document):
    data = document["deletion"]
    return {row["id"].lower(): row for row in data["resource_groups"] + data["resources"]}


def test_capability_names_the_shared_hub_link_contract():
    assert fl.capabilities()["factory_deletion_shared_hub_links"] == "shared-hub-spoke-links-v1"


def test_recorded_hub_links_to_the_deleted_spoke_are_frozen_and_nothing_else_in_the_hub():
    document, cloud = batman()
    fl.validate_manifest(freeze(document, cloud))
    data = document["deletion"]
    assert [row["id"] for row in data["hub_links"]] == OWN_LINKS
    assert all(row["side"] == "hub" and row["remote_virtual_network_id"] == VNET.lower() for row in data["hub_links"])
    assert {row["id"]: row["api_version"] for row in data["hub_links"]} == {
        OWN_BLOB_LINK: "2024-06-01", OWN_VAULT_LINK: "2024-06-01", OWN_PEERING: "2024-05-01"}
    # A link to this factory's VNet that the bootstrap did not record is never deleted, only reported.
    assert data["retained_hub_links"] == [MANUAL_LINK]
    assert data["shared_hub_links_hash"] == fl.digest(document["shared_hub_links"])
    entries = rows(document)
    # The factory's own side of the recorded peering pair goes with its VNet.
    for identifier in (VNET, SPOKE_PEERING, COMMON):
        assert entries[identifier.lower()]["delete"] is True, identifier
    assert not any(identifier.startswith(f"/subscriptions/{HUB_SUB}") for identifier in entries)
    assert not cloud.deleted


def test_without_link_proof_a_spoke_peered_to_a_shared_hub_still_blocks():
    document, cloud = batman(with_links=False)
    with pytest.raises(fl.Blocked, match="factory-delete-access-hub-foreign-link"):
        freeze(document, cloud)
    assert not cloud.deleted


@pytest.mark.parametrize("defect,code", [
    ("recorded-link-repointed", "factory-delete-hub-link-changed"),
    ("remote-vnet-retained", "factory-delete-hub-link-remote-retained"),
    ("hub-collection-unsupported", "factory-delete-hub-inventory-incomplete"),
    ("hub-not-protected", "factory-delete-shared-hub-links-proof-invalid"),
    ("hub-is-a-deletion-scope", "factory-delete-shared-hub-links-proof-invalid"),
    ("link-to-the-hub-vnet", "factory-delete-shared-hub-links-proof-invalid"),
    ("link-outside-the-hub", "factory-delete-shared-hub-links-proof-invalid"),
    ("link-type-mismatch", "factory-delete-shared-hub-links-proof-invalid"),
    ("other-factory-proof", "factory-delete-shared-hub-links-proof-invalid"),
    ("unsorted-links", "factory-delete-shared-hub-links-proof-invalid"),
    ("hub-peering-unrecorded", "factory-delete-access-hub-foreign-link"),
])
def test_ambiguous_or_broadened_hub_links_block(defect, code):
    cloud, changes, roots = SharedHubCloud(), {}, SPOKE_ROOTS
    proof = link_proof({"target": {"factory_id": OWNER["factory_id"], "scaleset_id": OWNER["scaleset_id"]}})
    if defect == "recorded-link-repointed":
        cloud.bodies[OWN_PEERING.lower()]["properties"]["remoteVirtualNetwork"]["id"] = SPIDER_VNET
    elif defect == "remote-vnet-retained":
        # The VNet is not proven factory-owned, so it stays; its recorded hub link must too: block.
        roots = [root for root in SPOKE_ROOTS if root != VNET]
    elif defect == "hub-collection-unsupported":
        cloud.unsupported.add((VAULT_ZONE + "/virtualNetworkLinks").lower())
    elif defect == "hub-not-protected":
        pass
    elif defect == "hub-is-a-deletion-scope":
        changes["hub_resource_group_ids"] = sorted([HUB.lower(), COMMON.lower()])
    elif defect == "link-to-the-hub-vnet":
        changes["links"] = [*proof["links"], {"id": HUB_SELF_LINK.lower(), "type": DNS_LINK_TYPE,
                                              "remote_virtual_network_id": HUB_VNET.lower()}]
        changes["links"].sort(key=lambda row: row["id"])
    elif defect == "link-outside-the-hub":
        other = OWN_BLOB_LINK.lower().replace("aifactory-connectivity", "other-hub")
        changes["links"] = sorted([*proof["links"][1:], {**proof["links"][0], "id": other}], key=lambda row: row["id"])
    elif defect == "link-type-mismatch":
        changes["links"] = [{**row, "type": PEERING_TYPE} if row["type"] == DNS_LINK_TYPE else row
                            for row in proof["links"]]
    elif defect == "other-factory-proof":
        changes["factory_id"] = "factory-b"
    elif defect == "hub-peering-unrecorded":
        # Only DNS links are recorded, so the spoke's peering to the hub is not this factory's to cut.
        changes["links"] = [row for row in proof["links"] if row["type"] == DNS_LINK_TYPE]
    document, cloud = batman(cloud, roots=roots, **changes)
    if defect == "hub-not-protected":
        document["protected_resource_ids"] = []
    elif defect == "unsorted-links":
        document["shared_hub_links"]["links"].reverse()
    with pytest.raises(fl.Blocked, match=code):
        fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects())
    assert not cloud.deleted


@pytest.mark.parametrize("tamper", ["drop-proof", "add-spider-link", "repoint-frozen-link", "drop-from-proof",
                                    "unfrozen-proof", "retained-outside-hub"])
def test_frozen_hub_links_cannot_be_reused_with_a_changed_proof_or_inventory(tamper):
    document, cloud = batman()
    freeze(document, cloud)
    data = document["deletion"]
    if tamper == "drop-proof":
        document.pop("shared_hub_links")
    elif tamper == "add-spider-link":
        data["hub_links"] = sorted([*data["hub_links"], {
            "id": SPIDER_LINK, "type": DNS_LINK_TYPE, "api_version": "2024-06-01",
            "remote_virtual_network_id": SPIDER_VNET.lower(), "side": "hub"}], key=lambda row: row["id"].lower())
    elif tamper == "repoint-frozen-link":
        data["hub_links"][0]["remote_virtual_network_id"] = SPIDER_VNET.lower()
    elif tamper == "drop-from-proof":
        document["shared_hub_links"]["links"].pop(0)
        data["shared_hub_links_hash"] = fl.digest(document["shared_hub_links"])
    elif tamper == "unfrozen-proof":
        data.pop("hub_links")
    else:
        data["retained_hub_links"] = [SPIDER_VNET]
    with pytest.raises(fl.Blocked):
        fl.validate_manifest(seal(document))


def test_a_hub_link_frozen_by_two_cohort_members_blocks():
    document, _ = batman()
    document["deletion"] = {"hub_links": [{"id": OWN_PEERING}]}
    other = copy.deepcopy(document)
    other["deletion"]["hub_links"][0]["id"] = OWN_PEERING.upper()
    fl.factory_deletion_module().require_unique_hub_links([document])
    with pytest.raises(fl.Blocked, match="factory-delete-hub-link-overlap"):
        fl.factory_deletion_module().require_unique_hub_links([document, other])


def run_cohort(document, cloud, workspace, monkeypatch):
    source = workspace / "source"
    source.mkdir()
    monkeypatch.setattr(fl, "verify_source", lambda *args: source)
    monkeypatch.setattr(fl, "_verify_source", lambda *args, **kwargs: source)
    worker_deleted = []

    def dispatch(actual_cloud, locks, actual, source_root, receipt, persist):
        receipt["remote_run"] = {"kind": "ado", "pipeline_id": 8, "run_id": 44}
        persist()
        result = fl.run_deployment_worker(json.loads(fl.protected_worker_envelope(actual, locks)),
                                         source_root, actual["run_id"], actual["manifest_hash"],
                                         cloud=actual_cloud, sleep=lambda _: None)
        assert result["status"] == "succeeded", result
        worker_deleted.extend(cloud.deleted)
        # Project pipelines never touch the shared hub.
        assert all(identifier.lower() in cloud.bodies for identifier in OWN_LINKS)
        receipt["remote_terminal"] = True

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    return result, worker_deleted


def test_operator_removes_recorded_hub_links_last_after_the_spoke_vnet_is_gone(workspace, monkeypatch):
    document, cloud = batman()
    freeze(document, cloud)
    cleared = []

    def azure_clears_dns_links(identifier):
        # Azure usually removes a deleted VNet's private DNS zone links itself; hub peerings stay Disconnected.
        if identifier.lower() == VNET.lower():
            cleared.append(cloud.bodies.pop(OWN_VAULT_LINK.lower())["id"])
            cloud.bodies[OWN_PEERING.lower()]["properties"]["peeringState"] = "Disconnected"
            cloud.bodies[OWN_PEERING.lower()]["etag"] = '"disconnected"'

    cloud.after_delete = azure_clears_dns_links
    result, worker_deleted = run_cohort(document, cloud, workspace, monkeypatch)
    assert result["status"] == "succeeded", result
    assert cleared == [OWN_VAULT_LINK]
    deleted = [value.lower() for value in cloud.deleted]
    # Unlinking is the very last step: after every project pipeline and the whole common teardown.
    assert deleted[-2:] == [OWN_BLOB_LINK.lower(), OWN_PEERING.lower()]
    assert deleted.index(VNET.lower()) < deleted.index(COMMON.lower()) < deleted.index(OWN_BLOB_LINK.lower())
    child = result["children"][0]
    assert child["deleted_hub_links"] == OWN_LINKS and child["hub_unlink_complete"] is True
    assert {value.lower() for value in child["deleted_resources"]} >= {VNET.lower(), SPOKE_PEERING.lower()}
    assert not {value.lower() for value in child["deleted_resources"]} & {value.lower() for value in OWN_LINKS}
    # The shared hub, its zones, its own link, spider's links and the unrecorded link all stay.
    for identifier in (HUB, HUB_VNET, BLOB_ZONE, VAULT_ZONE, HUB_SELF_LINK, MANUAL_LINK, SPIDER_LINK, SPIDER_PEERING):
        assert identifier.lower() in cloud.bodies, identifier
    assert not any(identifier.startswith(f"/subscriptions/{HUB_SUB}") for identifier in worker_deleted)


@pytest.mark.parametrize("drift,code", [
    ("spoke-vnet-recreated", "factory-delete-hub-link-spoke-present"),
    ("hub-link-repointed", "factory-delete-hub-link-changed"),
])
def test_hub_cleanup_blocks_rather_than_cutting_a_live_network(workspace, monkeypatch, drift, code):
    document, cloud = batman()
    freeze(document, cloud)
    vnet = copy.deepcopy(cloud.bodies[VNET.lower()])

    def drift_after_common(identifier):
        if identifier.lower() != COMMON.lower():
            return
        if drift == "spoke-vnet-recreated":
            cloud.bodies[VNET.lower()] = vnet
        else:
            cloud.bodies[OWN_BLOB_LINK.lower()]["properties"]["virtualNetwork"]["id"] = SPIDER_VNET

    cloud.after_delete = drift_after_common
    result, _ = run_cohort(document, cloud, workspace, monkeypatch)
    assert result["status"] == "reconciliation-required" and result["error_code"] == code, result
    for identifier in OWN_LINKS:
        assert identifier.lower() in cloud.bodies, identifier
