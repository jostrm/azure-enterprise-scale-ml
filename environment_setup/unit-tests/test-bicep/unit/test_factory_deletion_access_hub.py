"""Factory-owned integrated access hub teardown (factory-owned-access-hub-v1), offline only.

The fixture mirrors a factory whose integrated access-hub bootstrap placed an untagged VPN
gateway, Bastion, private DNS zone, private runner VM and its deployment identity inside the
factory's own common resource group. Catalog bootstrap records, never names or tags, prove
ownership; shared or foreign-linked hubs keep blocking.
"""

import copy
import json

import pytest

from .test_factory_lifecycle import fl, GROUP, COMMON, OWNER, RESOURCE, SUB, seal, workspace, no_real_services
from .test_selective_project_deletion import PROJECT, ProjectCloud, VAULT, prepared, tagged


CORE = {key: value for key, value in OWNER.items() if key != "project_id"}
DEPLOYMENT = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
NET = COMMON + "/providers/Microsoft.Network"
VNET = NET + "/virtualNetworks/vnt-esmlcmn"
GATEWAY_SUBNET = VNET + "/subnets/GatewaySubnet"
BASTION_SUBNET = VNET + "/subnets/AzureBastionSubnet"
RUNNER_SUBNET = VNET + "/subnets/snet-runner"
GATEWAY = NET + "/virtualNetworkGateways/vpngw-874678d6611d"
GATEWAY_IP = NET + "/publicIPAddresses/vpngw-874678d6611d"
BASTION = NET + "/bastionHosts/bastion-14a012b6349d"
BASTION_IP = NET + "/publicIPAddresses/bastion-14a012b6349d"
ZONE = NET + "/privateDnsZones/privatelink.vaultcore.azure.net"
LINK = ZONE + "/virtualNetworkLinks/link-vnt-esmlcmn"
NIC = NET + "/networkInterfaces/runner-gha-nic"
RUNNER = COMMON + "/providers/Microsoft.Compute/virtualMachines/runner-gha-sdc-dev-001"
DISK = COMMON + "/providers/Microsoft.Compute/disks/runner-gha-sdc-dev-001-osdisk"
IDENTITY_ID = COMMON + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/afwriter-dev"
COMMON_IP = NET + "/publicIPAddresses/common-ip"
FOREIGN_VNET = (f"/subscriptions/{SUB}/resourceGroups/aifactory-connectivity"
                "/providers/Microsoft.Network/virtualNetworks/vnet-connectivity")
# A reusable connectivity hub in its own subscription, peered and DNS-linked to several factories.
SHARED_HUB_SUB = "/subscriptions/99999999-9999-4999-8999-999999999999"
SHARED_HUB_VNET = (SHARED_HUB_SUB + "/resourceGroups/aifactory-connectivity"
                   "/providers/Microsoft.Network/virtualNetworks/vnet-aifactory-access-hub-sdc-001")
HUB_ROOTS = [VNET, GATEWAY, GATEWAY_IP, BASTION, BASTION_IP, ZONE, NIC, RUNNER, DISK, IDENTITY_ID]
TYPES = {
    "microsoft.network": ["publicIPAddresses", "virtualNetworks", "virtualNetworks/subnets",
                          "virtualNetworks/virtualNetworkPeerings", "networkSecurityGroups",
                          "networkSecurityGroups/securityRules", "virtualNetworkGateways", "bastionHosts",
                          "privateDnsZones", "privateDnsZones/virtualNetworkLinks", "networkInterfaces",
                          "connections"],
    "microsoft.compute": ["virtualMachines", "disks"],
    "microsoft.managedidentity": ["userAssignedIdentities"],
    "microsoft.keyvault": ["vaults"],
}


def untagged(identifier, kind, properties=None, **extra):
    return {"id": identifier, "type": kind, "etag": '"original"', "tags": None, "properties": properties or {}, **extra}


class HubCloud(ProjectCloud):
    """aif-118 shape: bootstrap hub resources carry no AI Factory tags at all."""

    def __init__(self):
        super().__init__()
        self.bodies = {
            GROUP.lower(): tagged(GROUP, "Microsoft.Resources/resourceGroups", OWNER),
            RESOURCE.lower(): tagged(RESOURCE, "Microsoft.Network/publicIPAddresses", OWNER),
            VAULT.lower(): tagged(VAULT, "Microsoft.KeyVault/vaults", OWNER),
            COMMON.lower(): tagged(COMMON, "Microsoft.Resources/resourceGroups", CORE),
            COMMON_IP.lower(): tagged(COMMON_IP, "Microsoft.Network/publicIPAddresses", CORE),
        }
        subnets = [untagged(value, "Microsoft.Network/virtualNetworks/subnets")
                   for value in (GATEWAY_SUBNET, BASTION_SUBNET, RUNNER_SUBNET)]
        project_subnet = tagged(PROJECT_SUBNET, "Microsoft.Network/virtualNetworks/subnets", OWNER)
        for body in [*subnets, project_subnet]:
            self.bodies[body["id"].lower()] = body
        self.bodies[VNET.lower()] = untagged(VNET, "Microsoft.Network/virtualNetworks",
                                             {"subnets": copy.deepcopy([*subnets, project_subnet]),
                                              "virtualNetworkPeerings": []})
        for identifier, kind, properties in (
                (GATEWAY_IP, "Microsoft.Network/publicIPAddresses",
                 {"ipConfiguration": {"id": GATEWAY + "/ipConfigurations/default"}}),
                (BASTION_IP, "Microsoft.Network/publicIPAddresses", {}),
                (GATEWAY, "Microsoft.Network/virtualNetworkGateways", {"gatewayType": "Vpn", "ipConfigurations": [
                    {"id": GATEWAY + "/ipConfigurations/default", "properties": {
                        "subnet": {"id": GATEWAY_SUBNET}, "publicIPAddress": {"id": GATEWAY_IP}}}],
                    "vpnClientConfiguration": {"vpnClientAddressPool": {"addressPrefixes": ["172.31.240.0/24"]}}}),
                (BASTION, "Microsoft.Network/bastionHosts", {"ipConfigurations": [{"properties": {
                    "subnet": {"id": BASTION_SUBNET}, "publicIPAddress": {"id": BASTION_IP}}}]}),
                (ZONE, "Microsoft.Network/privateDnsZones", {}),
                (LINK, "Microsoft.Network/privateDnsZones/virtualNetworkLinks", {"virtualNetwork": {"id": VNET}}),
                (NIC, "Microsoft.Network/networkInterfaces", {"ipConfigurations": [
                    {"properties": {"subnet": {"id": RUNNER_SUBNET}}}], "virtualMachine": {"id": RUNNER}}),
                (IDENTITY_ID, "Microsoft.ManagedIdentity/userAssignedIdentities", {"principalId": DEPLOYMENT})):
            self.bodies[identifier.lower()] = untagged(identifier, kind, properties)
        self.bodies[DISK.lower()] = untagged(DISK, "Microsoft.Compute/disks", {"osType": "Linux"}, managedBy=RUNNER)
        self.bodies[RUNNER.lower()] = untagged(
            RUNNER, "Microsoft.Compute/virtualMachines", {"networkProfile": {"networkInterfaces": [{"id": NIC}]},
                                                          "storageProfile": {"osDisk": {"managedDisk": {"id": DISK}}}},
            identity={"type": "UserAssigned", "userAssignedIdentities": {IDENTITY_ID: {"principalId": DEPLOYMENT}}})

    def provider_schema(self, namespace):
        return {"resourceTypes": [{"resourceType": kind, "apiVersions": ["2024-05-01"]}
                                  for kind in TYPES.get(namespace.lower(), [])]}

    def list_resources(self, scope):
        return [copy.deepcopy(body) for key, body in sorted(self.bodies.items())
                if fl.arm_scope(key) == scope.lower() and "/providers/" in key
                and len(key.rsplit("/providers/", 1)[-1].split("/")) == 3]

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        result = super().arm(method, resource_id, api_version, allowed, headers)
        if method == "DELETE":
            # Like ARM, a deleted dependent disappears from its dependencies' back-references.
            gone = resource_id.lower()
            for body in self.bodies.values():
                properties = body.get("properties") or {}
                for holder, field in ((body, "managedBy"), (properties, "virtualMachine"),
                                      (properties, "ipConfiguration")):
                    value = holder.get(field)
                    reference = value.get("id") if isinstance(value, dict) else value
                    if isinstance(reference, str) and (reference.lower() == gone
                                                       or reference.lower().startswith(gone + "/")):
                        holder.pop(field)
        return result

    def collection(self, path, api_version, extension=False):
        if extension:
            return [], None
        prefix = path.lower() + "/"
        return [copy.deepcopy(body) for key, body in sorted(self.bodies.items())
                if key.startswith(prefix) and "/" not in key[len(prefix):]], None


PROJECT_SUBNET = VNET + "/subnets/project-subnet"


def hub_proof(document, roots=None, **changes):
    proof = {"contract": "factory-owned-access-hub-v1", "factory_id": document["target"]["factory_id"],
             "scaleset_id": document["target"]["scaleset_id"], "subscription_id": SUB, "mode": "integrated",
             "resource_group_ids": [COMMON.lower()],
             "resource_ids": sorted(value.lower() for value in (HUB_ROOTS if roots is None else roots)),
             "factory_resource_groups": sorted({GROUP.lower(), COMMON.lower()}),
             "evidence": {"contract": "consumed-bootstrap-stage-evidence-v1",
                          "workflow_id": "12345678-1234-4234-8234-123456789abc", "record_hash": "d" * 64}}
    proof.update(changes)
    return proof


def hub_document(cloud=None, proof=True, roots=None, **changes):
    """A whole-factory manifest whose writable scopes are the project and common groups."""
    document, _ = prepared(True, True)
    for key in ("deletion_scope", "reviewed_scope", "deletion"):
        document.pop(key, None)
    cloud = cloud or HubCloud()
    for scope in (GROUP, COMMON):
        cloud.enrollment["scopes"][scope.lower()] = {
            **copy.deepcopy(cloud.enrollment["scopes"][GROUP.lower()]), "common_dependencies": [],
            "target": {key: document["target"][key] for key in (
                "factory_id", "scaleset_id", "environment", "tenant_id", "subscription_id", "prefix", "region", "suffix")}}
    document["route"].update(scoped_contract=1, auth_namespace="factory-stage",
                             runner={"kind": "self-hosted", "os": "linux", "pool": "aifactory-private"})
    document["identity"]["deployment_object_id"] = DEPLOYMENT
    cloud.enrollment["writers"]["writer-a"].update(
        auth_namespace=document["route"]["auth_namespace"], runner=document["route"]["runner"],
        deployment_object_id=DEPLOYMENT)
    document["locks"]["coordination_hash"] = fl.digest(cloud.enrollment)
    if proof:
        document["access_hub_ownership"] = hub_proof(document, roots, **changes)
    return document, cloud


def projects():
    return [{"project_id": PROJECT, "project_number": "017", "registered_resource_ids": [GROUP, PROJECT_SUBNET]}]


def freeze(document, cloud):
    document["deletion"] = fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects())
    return seal(document)


def rows(document):
    data = document["deletion"]
    return {row["id"].lower(): row for row in data["resource_groups"] + data["resources"]}


def test_capability_names_the_factory_owned_access_hub_contract():
    assert fl.capabilities()["factory_deletion_access_hub"] == "factory-owned-access-hub-v1"


def test_without_bootstrap_hub_proof_the_untagged_hub_is_never_deleted():
    cloud = HubCloud()
    cloud.bodies[IDENTITY_ID.lower()]["properties"].pop("principalId")
    cloud.bodies[RUNNER.lower()].pop("identity")
    document, cloud = hub_document(cloud, proof=False)
    entries = rows(freeze(document, cloud))
    assert entries[GATEWAY.lower()]["delete"] is False
    assert entries[COMMON.lower()]["delete"] is False
    assert not cloud.deleted


def test_bootstrap_proven_hub_runner_and_common_group_freeze_for_deletion():
    document, cloud = hub_document()
    fl.validate_manifest(freeze(document, cloud))
    entries = rows(document)
    for identifier in [*HUB_ROOTS, LINK, GATEWAY_SUBNET, COMMON, COMMON_IP]:
        assert entries[identifier.lower()]["delete"] is True, identifier
    for identifier in (GATEWAY, BASTION, ZONE, RUNNER, IDENTITY_ID):
        row = entries[identifier.lower()]
        assert row["ownership_source"] == "access-hub-bootstrap-record"
        assert row["owner"] == CORE and row["project_number"] is None
    assert entries[PROJECT_SUBNET.lower()]["project_number"] == "017"
    assert not cloud.deleted


def test_a_hub_resource_missing_from_the_bootstrap_record_stays_retained():
    document, cloud = hub_document(roots=[root for root in HUB_ROOTS if root != GATEWAY])
    entries = rows(freeze(document, cloud))
    assert entries[GATEWAY.lower()]["delete"] is False
    assert entries[COMMON.lower()]["delete"] is False


def test_a_shared_connectivity_hub_in_another_subscription_is_never_deletion_scope():
    # Deleting one factory never deletes the shared hub that other factories still use.
    cloud = HubCloud()
    cloud.bodies[IDENTITY_ID.lower()]["properties"].pop("principalId")
    cloud.bodies[RUNNER.lower()].pop("identity")
    peering = VNET + "/virtualNetworkPeerings/to-shared-hub"
    cloud.bodies[peering.lower()] = untagged(
        peering, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
        {"remoteVirtualNetwork": {"id": SHARED_HUB_VNET}})
    document, cloud = hub_document(cloud, proof=False)
    entries = rows(freeze(document, cloud))
    assert not any(identifier.startswith(SHARED_HUB_SUB) for identifier in entries)
    for identifier in (peering, VNET, GATEWAY):
        assert entries[identifier.lower()]["delete"] is False, identifier
    assert not cloud.deleted


@pytest.mark.parametrize("defect,code", [
    ("foreign-zone-link", "factory-delete-access-hub-foreign-link"),
    ("foreign-peering", "factory-delete-access-hub-foreign-link"),
    ("shared-hub-zone-link", "factory-delete-access-hub-foreign-link"),
    ("shared-hub-peering", "factory-delete-access-hub-foreign-link"),
    ("site-connection", "factory-delete-access-hub-external-connection"),
    ("shared-tag", "factory-delete-access-hub-marked-protected"),
    ("foreign-owner-tag", "factory-delete-access-hub-owner-conflict"),
    ("other-factory-proof", "factory-delete-access-hub-proof-invalid"),
    ("proof-outside-writable", "factory-delete-access-hub-proof-invalid"),
    ("proof-group-not-writable", "factory-delete-access-hub-proof-invalid"),
    ("link-target-group-unregistered", "factory-delete-access-hub-proof-invalid"),
    ("external-mode-gateway", "factory-delete-access-hub-proof-invalid"),
    ("operator-is-runner", "executing-identity-in-deletion-scope"),
    ("worker-on-project-resource", "executing-identity-in-deletion-scope"),
])
def test_shared_foreign_or_self_hosting_hubs_block(defect, code):
    cloud = HubCloud()
    changes = {}
    if defect == "foreign-zone-link":
        cloud.bodies[LINK.lower()]["properties"]["virtualNetwork"]["id"] = FOREIGN_VNET
    elif defect == "foreign-peering":
        peering = VNET + "/virtualNetworkPeerings/to-connectivity"
        cloud.bodies[peering.lower()] = untagged(
            peering, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
            {"remoteVirtualNetwork": {"id": FOREIGN_VNET}})
    elif defect == "shared-hub-zone-link":
        cloud.bodies[LINK.lower()]["properties"]["virtualNetwork"]["id"] = SHARED_HUB_VNET
    elif defect == "shared-hub-peering":
        peering = VNET + "/virtualNetworkPeerings/to-shared-hub"
        cloud.bodies[peering.lower()] = untagged(
            peering, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
            {"remoteVirtualNetwork": {"id": SHARED_HUB_VNET}})
    elif defect == "site-connection":
        connection = NET + "/connections/onprem"
        cloud.bodies[connection.lower()] = untagged(connection, "Microsoft.Network/connections",
                                                    {"virtualNetworkGateway1": {"id": GATEWAY}})
    elif defect == "shared-tag":
        cloud.bodies[GATEWAY.lower()]["tags"] = {"aifactory.shared": "true"}
    elif defect == "foreign-owner-tag":
        cloud.bodies[BASTION.lower()]["tags"] = {fl.TAG_KEYS["factory_id"]: "factory-b",
                                                 fl.TAG_KEYS["scaleset_id"]: "Stage001"}
    elif defect == "other-factory-proof":
        changes["factory_id"] = "factory-b"
    elif defect == "proof-outside-writable":
        changes["resource_ids"] = sorted([*hub_proof({"target": {"factory_id": "", "scaleset_id": ""}})["resource_ids"],
                                          FOREIGN_VNET.lower()])
    elif defect == "proof-group-not-writable":
        changes["resource_group_ids"] = [COMMON.lower(), FOREIGN_VNET.lower().split("/providers/")[0]]
    elif defect == "link-target-group-unregistered":
        changes["factory_resource_groups"] = [COMMON.lower()]
    elif defect == "external-mode-gateway":
        changes["mode"] = "external"
    document, cloud = hub_document(cloud, **changes)
    if defect == "operator-is-runner":
        document["identity"]["object_id"] = DEPLOYMENT
    elif defect == "worker-on-project-resource":
        cloud.bodies[RESOURCE.lower()]["identity"] = {"principalId": DEPLOYMENT}
    with pytest.raises(fl.Blocked, match=code):
        fl.freeze_factory_deletion_pipeline(cloud, document, {}, projects())
    assert not cloud.deleted


@pytest.mark.parametrize("tamper", ["drop-gateway-from-proof", "drop-proof", "foreign-link-body"])
def test_frozen_hub_inventory_cannot_be_reused_with_a_changed_proof(tamper):
    document, cloud = hub_document()
    freeze(document, cloud)
    if tamper == "drop-gateway-from-proof":
        document["access_hub_ownership"]["resource_ids"].remove(GATEWAY.lower())
    elif tamper == "drop-proof":
        document.pop("access_hub_ownership")
    else:
        body = document["deletion"]["bodies"][LINK.lower()]
        body["properties"]["virtualNetwork"]["id"] = FOREIGN_VNET
        next(row for row in document["deletion"]["resources"] if row["id"].lower() == LINK.lower())[
            "body_hash"] = fl.digest(body)
        document["deletion"]["inventory_hash"] = fl.digest(document["deletion"]["resources"])
    with pytest.raises(fl.Blocked):
        fl.validate_manifest(seal(document))


def test_operator_tears_down_hub_and_runner_last_after_every_project_pipeline(workspace, monkeypatch):
    document, cloud = hub_document()
    freeze(document, cloud)
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
        # The project pipeline (possibly on the private runner) never touches the runner or the hub.
        assert RUNNER.lower() in cloud.bodies and GATEWAY.lower() in cloud.bodies
        receipt["remote_terminal"] = True

    monkeypatch.setattr(fl, "ado_scoped", dispatch)
    run = workspace / "execution"
    result = fl.execute_factory_deletion_cohort([document], source, run, run / "receipt.json",
                                                cloud_factory=lambda _: cloud)
    assert result["status"] == "succeeded", result
    assert {value.lower() for value in worker_deleted} == {GROUP.lower(), RESOURCE.lower(), VAULT.lower(),
                                                          PROJECT_SUBNET.lower()}
    common = [value.lower() for value in cloud.deleted[len(worker_deleted):]]
    late = {value.lower() for value in [*HUB_ROOTS, LINK, GATEWAY_SUBNET, BASTION_SUBNET, RUNNER_SUBNET]}
    assert common.index(COMMON_IP.lower()) < min(common.index(value) for value in late if value in common)
    assert common.index(RUNNER.lower()) < min(common.index(NIC.lower()), common.index(DISK.lower()))
    assert common.index(GATEWAY.lower()) < common.index(GATEWAY_IP.lower())
    assert common[-1] == COMMON.lower()
    assert not cloud.bodies and not cloud.leases
