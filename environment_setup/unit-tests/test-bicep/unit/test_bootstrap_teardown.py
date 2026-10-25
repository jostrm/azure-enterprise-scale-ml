"""Operator teardown of a never-enrolled, bootstrap-only factory (bootstrap-operator-teardown-v1), offline.

Shape: dc-batman4 / aif-118. The factory's own groups hold bootstrap-built resources (runner,
identity, Bastion, VNet) and tagged NSGs; its VNet is peered with, and DNS-linked from, a shared
connectivity hub in another subscription that also serves spider. Only this factory's own hub
links may go; the shared hub and spider's links always stay.
"""

import copy
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from .test_factory_lifecycle import fl, GROUP, COMMON, OWNER, RESOURCE, SUB, TENANT, IDENTITY, workspace, no_real_services
from .test_factory_deletion_access_hub import (
    HubCloud, untagged, CORE, VNET, GATEWAY, BASTION, RUNNER, NIC, DISK, IDENTITY_ID, ZONE, LINK, HUB_ROOTS,
    COMMON_IP, PROJECT_SUBNET, GATEWAY_SUBNET, RUNNER_SUBNET,
)
from .test_selective_project_deletion import VAULT, tagged


HUB_SUB = "abababab-abab-4bab-8bab-abababababab"
HUB = f"/subscriptions/{HUB_SUB}/resourceGroups/aifactory-connectivity"
HUB_NET = HUB + "/providers/Microsoft.Network"
HUB_VNET = HUB_NET + "/virtualNetworks/vnet-aifactory-access-hub-sdc-001"
HUB_ZONE = HUB_NET + "/privateDnsZones/privatelink.blob.core.windows.net"
SPIDER_VNET = (f"/subscriptions/{SUB}/resourceGroups/spider-esml-common-sdc-dev-001"
               "/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-sdc-dev-001")
OWN_HUB_LINK = HUB_ZONE + "/virtualNetworkLinks/aif-4d8896b66f23"
SPIDER_HUB_LINK = HUB_ZONE + "/virtualNetworkLinks/hub-to-spider"
OWN_PEERING = HUB_VNET + "/virtualNetworkPeerings/aif-4d8896b66f23"
SPIDER_PEERING = HUB_VNET + "/virtualNetworkPeerings/hub-to-spider-dev-001"
SPOKE_PEERING = VNET + "/virtualNetworkPeerings/aif-5eb3f21fdde8"
WORKFLOW = "12345678-1234-4234-8234-123456789abc"
DEPLOYMENT_PRINCIPAL = "31f7a62d-75c5-4dc3-89cb-7ea52829be9b"
NSG = COMMON + "/providers/Microsoft.Network/networkSecurityGroups/nsg-snet-esml-cmn-001"
NSG_RULE = NSG + "/securityRules/allow_vnet_inbound"
ROLE = COMMON + "/providers/Microsoft.Authorization/roleAssignments/5fc13df3-76b7-539e-8d42-af87d71d1f61"
RUNNER_NSG = COMMON + "/providers/Microsoft.Network/networkSecurityGroups/runner-gha-sdc-dev-001-nsg"


class TeardownCloud(HubCloud):
    """Factory groups plus a shared connectivity hub that the factory may only unlink from."""

    def __init__(self):
        super().__init__()
        # A bootstrap-only factory has no project resources yet; its project group is empty.
        for key in (RESOURCE.lower(), VAULT.lower(), PROJECT_SUBNET.lower()):
            self.bodies.pop(key)
        self.bodies[VNET.lower()]["properties"]["subnets"] = [
            row for row in self.bodies[VNET.lower()]["properties"]["subnets"]
            if row["id"].lower() != PROJECT_SUBNET.lower()]
        self.bodies[HUB.lower()] = untagged(HUB, "Microsoft.Resources/resourceGroups")
        self.bodies[HUB_VNET.lower()] = untagged(HUB_VNET, "Microsoft.Network/virtualNetworks",
                                                 {"subnets": [], "virtualNetworkPeerings": []})
        self.bodies[HUB_ZONE.lower()] = untagged(HUB_ZONE, "Microsoft.Network/privateDnsZones")
        for identifier, kind, field, remote in (
                (OWN_HUB_LINK, "Microsoft.Network/privateDnsZones/virtualNetworkLinks", "virtualNetwork", VNET),
                (SPIDER_HUB_LINK, "Microsoft.Network/privateDnsZones/virtualNetworkLinks", "virtualNetwork", SPIDER_VNET),
                (OWN_PEERING, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings", "remoteVirtualNetwork", VNET),
                (SPIDER_PEERING, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings", "remoteVirtualNetwork",
                 SPIDER_VNET)):
            self.bodies[identifier.lower()] = untagged(identifier, kind, {field: {"id": remote}})
        spoke = untagged(SPOKE_PEERING, "Microsoft.Network/virtualNetworks/virtualNetworkPeerings",
                         {"remoteVirtualNetwork": {"id": HUB_VNET}, "peeringState": "Connected"})
        self.bodies[SPOKE_PEERING.lower()] = spoke
        self.bodies[VNET.lower()]["properties"]["virtualNetworkPeerings"] = [copy.deepcopy(spoke)]
        # A factory-tagged NSG's untagged rules and the recorded deployment principal's RG role.
        self.bodies[NSG.lower()] = tagged(NSG, "Microsoft.Network/networkSecurityGroups", CORE)
        self.bodies[NSG_RULE.lower()] = untagged(NSG_RULE, "Microsoft.Network/networkSecurityGroups/securityRules",
                                                 {"access": "Allow"})
        self.bodies[ROLE.lower()] = untagged(ROLE, "Microsoft.Authorization/roleAssignments",
                                             {"principalId": DEPLOYMENT_PRINCIPAL, "scope": COMMON})
        # Real ARM back-references: the runner NSG lists its NIC, the gateway subnet lists the
        # gateway's IP configuration, while both of those point forward at the NSG/subnet.
        self.bodies[RUNNER_NSG.lower()] = tagged(RUNNER_NSG, "Microsoft.Network/networkSecurityGroups", CORE,
                                                 {"networkInterfaces": [{"id": NIC}]})
        self.bodies[NIC.lower()]["properties"]["networkSecurityGroup"] = {"id": RUNNER_NSG}
        self.bodies[GATEWAY_SUBNET.lower()]["properties"]["ipConfigurations"] = [
            {"id": GATEWAY + "/ipConfigurations/default"}]
        # The runner subnet uses the factory NSG, which lists it back; the VNet repeats its subnets inline.
        self.bodies[RUNNER_SUBNET.lower()]["properties"]["networkSecurityGroup"] = {"id": NSG}
        self.bodies[NSG.lower()]["properties"] = {"subnets": [{"id": RUNNER_SUBNET}]}
        self.bodies[VNET.lower()]["properties"]["subnets"] = [
            copy.deepcopy(self.bodies[row["id"].lower()]) for row in self.bodies[VNET.lower()]["properties"]["subnets"]]

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "DELETE":
            # Like ARM, a resource still referenced by a surviving one is in use and cannot go.
            gone = resource_id.lower()
            for key, body in self.bodies.items():
                if not (key == gone or key.startswith(gone + "/")):
                    fl.require(not any(ref == gone or ref.startswith(gone + "/")
                                       for ref in fl.project_resource_dependencies(body)), "resource-in-use")
        result = super().arm(method, resource_id, api_version, allowed, headers)
        if method == "DELETE":
            # Like ARM, a deleted dependent leaves the back-reference lists that named it.
            gone = resource_id.lower()
            for body in self.bodies.values():
                properties = body.get("properties") or {}
                for field in ("virtualNetworkPeerings", "networkInterfaces", "ipConfigurations"):
                    rows = properties.get(field)
                    if isinstance(rows, list) and not (field == "ipConfigurations"
                                                       and "/subnets/" not in body["id"].lower()):
                        properties[field] = [row for row in rows if not (
                            row.get("id", "").lower() == gone or row.get("id", "").lower().startswith(gone + "/"))]
        return result


def stamp(seconds):
    return datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat()


def request(roots=HUB_ROOTS, **changes):
    document = {
        "schema": 1, "contract": "bootstrap-operator-teardown-v1", "run_id": str(uuid4()),
        "prepared_at": stamp(-5), "expires_at": stamp(1800), "source": {"commit": "a" * 40},
        "target": {"factory_id": OWNER["factory_id"], "scaleset_id": OWNER["scaleset_id"], "environment": "stage",
                   "tenant_id": TENANT, "subscription_id": SUB},
        "identity": {"object_id": IDENTITY},
        "scopes": sorted([GROUP.lower(), COMMON.lower()]),
        "bootstrap_record": {"contract": "consumed-bootstrap-stage-evidence-v1", "workflow_id": WORKFLOW,
                             "record_hash": "d" * 64, "groups": sorted([GROUP.lower(), COMMON.lower()]),
                             "resources": sorted(value.lower() for value in roots),
                             "principal_ids": [DEPLOYMENT_PRINCIPAL]},
        "hub_scopes": [HUB.lower()], "protected_resource_ids": [HUB.lower()],
    }
    document.update(changes)
    return document


def frozen(cloud=None, **changes):
    cloud = cloud or TeardownCloud()
    document = request(**changes)
    document["deletion"] = fl.freeze_bootstrap_teardown(cloud, document)
    document["manifest_hash"] = fl.teardown_digest(document)
    return document, cloud


def test_capability_names_the_operator_teardown_contract():
    assert fl.capabilities()["bootstrap_operator_teardown"] == "bootstrap-operator-teardown-v1"


def test_freeze_selects_whole_factory_groups_and_only_this_factorys_hub_links():
    document, cloud = frozen()
    fl.validate_bootstrap_teardown(document)
    data = document["deletion"]
    rows = {row["id"].lower(): row for row in data["resource_groups"] + data["resources"]}
    assert all(row["delete"] for row in rows.values())
    assert {GROUP.lower(), COMMON.lower(), RUNNER.lower(), BASTION.lower(), GATEWAY.lower(), VNET.lower(),
            COMMON_IP.lower()} <= set(rows)
    assert rows[RUNNER.lower()]["ownership_source"] == "bootstrap-record"
    assert rows[COMMON_IP.lower()]["ownership_source"] == "tags"
    assert rows[NSG_RULE.lower()]["ownership_source"] == "parent"
    assert rows[ROLE.lower()]["ownership_source"] == "bootstrap-principal"
    assert [row["id"] for row in data["hub_links"]] == sorted([OWN_HUB_LINK, OWN_PEERING, SPOKE_PEERING],
                                                              key=str.lower)
    assert {row["side"] for row in data["hub_links"]} == {"hub", "factory"}
    assert not any(key.startswith(HUB.lower()) for key in rows)
    assert not cloud.deleted


@pytest.mark.parametrize("defect,code", [
    ("unowned", "bootstrap-teardown-unowned-resource"),
    ("foreign-owner", "bootstrap-teardown-owner-conflict"),
    ("shared-tag", "bootstrap-teardown-protected-resource"),
    ("tagged-vpn-without-record", "bootstrap-teardown-protected-resource"),
    ("site-connection", "bootstrap-teardown-protected-resource"),
    ("tagged-resolver-without-record", "bootstrap-teardown-protected-resource"),
    ("project-resource", "bootstrap-teardown-project-resources-require-pipelines"),
    ("foreign-principal-role", "bootstrap-teardown-unowned-resource"),
    ("rule-under-foreign-nsg", "bootstrap-teardown-owner-conflict"),
    ("operator-on-runner", "executing-identity-in-deletion-scope"),
    ("scope-is-connectivity-hub", "bootstrap-teardown-request-invalid"),
    ("record-other-groups", "bootstrap-teardown-request-invalid"),
    ("hub-scope-deleted", "bootstrap-teardown-request-invalid"),
])
def test_unowned_shared_or_unsafe_scopes_block_before_any_change(defect, code):
    cloud = TeardownCloud()
    changes = {}
    roots = HUB_ROOTS
    if defect == "unowned":
        stray = COMMON + "/providers/Microsoft.Network/publicIPAddresses/stray"
        cloud.bodies[stray.lower()] = untagged(stray, "Microsoft.Network/publicIPAddresses")
    elif defect == "foreign-owner":
        cloud.bodies[COMMON_IP.lower()]["tags"][fl.TAG_KEYS["factory_id"]] = "factory-b"
    elif defect == "shared-tag":
        cloud.bodies[BASTION.lower()]["tags"] = {"aifactory.shared": "true"}
    elif defect == "tagged-vpn-without-record":
        roots = [root for root in HUB_ROOTS if root != GATEWAY]
        cloud.bodies[GATEWAY.lower()]["tags"] = {fl.TAG_KEYS[key]: value for key, value in CORE.items()}
    elif defect == "site-connection":
        connection = COMMON + "/providers/Microsoft.Network/connections/onprem"
        cloud.bodies[connection.lower()] = tagged(connection, "Microsoft.Network/connections", CORE)
    elif defect == "tagged-resolver-without-record":
        # The DNS private resolver is connectivity: tags alone never authorize deleting it.
        resolver = COMMON + "/providers/Microsoft.Network/dnsResolvers/dnspr-874678d6611d"
        cloud.bodies[resolver.lower()] = tagged(resolver, "Microsoft.Network/dnsResolvers", CORE)
    elif defect == "foreign-principal-role":
        cloud.bodies[ROLE.lower()]["properties"]["principalId"] = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    elif defect == "rule-under-foreign-nsg":
        cloud.bodies[NSG.lower()]["tags"][fl.TAG_KEYS["factory_id"]] = "factory-b"
    elif defect == "project-resource":
        cloud.bodies[RESOURCE.lower()] = tagged(RESOURCE, "Microsoft.Network/publicIPAddresses", OWNER)
    elif defect == "operator-on-runner":
        cloud.bodies[IDENTITY_ID.lower()]["properties"]["principalId"] = IDENTITY
    elif defect == "scope-is-connectivity-hub":
        changes["protected_resource_ids"] = sorted([HUB.lower(), COMMON.lower()])
    elif defect == "record-other-groups":
        changes["scopes"] = [COMMON.lower()]
    elif defect == "hub-scope-deleted":
        changes["hub_scopes"] = [COMMON.lower()]
    with pytest.raises(fl.Blocked, match=code):
        frozen(cloud, roots=roots, **changes)
    assert not cloud.deleted


@pytest.mark.parametrize("tamper", ["hash", "hub-link-foreign", "expired"])
def test_frozen_teardown_cannot_be_changed_or_reused(tamper):
    document, cloud = frozen()
    if tamper == "hash":
        document["scopes"].append((GROUP + "-other").lower())
    elif tamper == "hub-link-foreign":
        document["deletion"]["hub_links"][0]["remote_virtual_network_id"] = SPIDER_VNET.lower()
        document["manifest_hash"] = fl.teardown_digest(document)
    else:
        document["expires_at"] = stamp(-1)
        document["manifest_hash"] = fl.teardown_digest(document)
    with pytest.raises(fl.Blocked):
        fl.validate_bootstrap_teardown(document, require_unexpired=True)


def test_operator_unlinks_its_hub_links_first_then_deletes_groups_last(workspace):
    document, cloud = frozen()
    run = workspace / "teardown"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "succeeded", (receipt.get("error_code"), receipt.get("pending_resource"), cloud.deleted)
    deleted = [value.lower() for value in cloud.deleted]
    assert deleted[:3] == sorted([OWN_HUB_LINK.lower(), OWN_PEERING.lower(), SPOKE_PEERING.lower()])
    assert deleted[-1] in (GROUP.lower(), COMMON.lower()) and deleted[-2] in (GROUP.lower(), COMMON.lower())
    assert deleted.index(RUNNER.lower()) < deleted.index(NIC.lower())
    assert deleted.index(NIC.lower()) < deleted.index(RUNNER_NSG.lower())
    # The gateway subnet goes with its VNet, after the gateway that used it.
    assert deleted.index(GATEWAY.lower()) < deleted.index(VNET.lower())
    assert {SPIDER_HUB_LINK.lower(), SPIDER_PEERING.lower(), HUB_ZONE.lower(), HUB_VNET.lower(), HUB.lower()} <= set(cloud.bodies)
    assert not any(key.startswith((COMMON.lower(), GROUP.lower())) for key in cloud.bodies)
    assert json.loads((run / "receipt.json").read_text()) == receipt
    assert set(receipt["deleted_hub_links"]) == {OWN_HUB_LINK, OWN_PEERING, SPOKE_PEERING}


def test_child_resources_go_with_their_parent_which_keeps_their_order(workspace):
    document, cloud = frozen()
    rows = {row["id"].lower(): row for row in document["deletion"]["resources"]}
    assert rows[NSG_RULE.lower()]["delete_via_parent"] == NSG.lower()
    assert rows[RUNNER_SUBNET.lower()]["delete_via_parent"] == VNET.lower()
    assert rows[LINK.lower()]["delete_via_parent"] == ZONE.lower()
    # Extension resources and hub peerings are still deleted one by one.
    assert "delete_via_parent" not in rows[ROLE.lower()]
    assert "delete_via_parent" not in rows[SPOKE_PEERING.lower()]
    run = workspace / "teardown"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "succeeded", (receipt.get("error_code"), receipt.get("pending_resource"), cloud.deleted)
    deleted = [value.lower() for value in cloud.deleted]
    assert not {NSG_RULE.lower(), RUNNER_SUBNET.lower(), GATEWAY_SUBNET.lower(), LINK.lower()} & set(deleted)
    # The runner subnet used the NSG, so its VNet goes first; the zone link pointed at the VNet.
    assert deleted.index(VNET.lower()) < deleted.index(NSG.lower())
    assert deleted.index(ZONE.lower()) < deleted.index(VNET.lower())
    assert {NSG_RULE, RUNNER_SUBNET, GATEWAY_SUBNET, LINK} <= set(receipt["deleted_resources"])


def test_execution_checks_each_delete_without_reinventorying_every_group(workspace, monkeypatch):
    document, cloud = frozen()
    inventories = []
    collect = fl.collect_resource_closure
    monkeypatch.setattr(fl, "collect_resource_closure",
                        lambda *args, **kwargs: inventories.append(1) or collect(*args, **kwargs))
    run = workspace / "teardown"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "succeeded", (receipt.get("error_code"), receipt.get("pending_resource"))
    # One complete inventory before the first change and one after the last, not one per delete.
    assert len(inventories) == 2


@pytest.mark.parametrize("change,code", [
    ("new-dependency", "bootstrap-teardown-resource-changed"),
    ("owner-tag", "bootstrap-teardown-resource-changed"),
    ("deployment-started", "active-or-unknown-deployment"),
])
def test_resource_changed_during_the_run_stops_before_its_delete(workspace, change, code):
    document, cloud = frozen()

    def drift(identifier):
        if change == "new-dependency":
            cloud.bodies[RUNNER.lower()]["properties"]["availabilitySet"] = {
                "id": COMMON + "/providers/Microsoft.Compute/availabilitySets/added-after-review"}
        elif change == "owner-tag":
            cloud.bodies[RUNNER.lower()]["tags"] = {fl.TAG_KEYS["factory_id"]: OWNER["factory_id"],
                                                    fl.TAG_KEYS["scaleset_id"]: "other-scale-set"}
        else:
            cloud.active = True

    cloud.after_delete = drift
    run = workspace / "teardown"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "reconciliation-required" and receipt["error_code"] == code
    assert RUNNER not in cloud.deleted


def test_inventory_drift_after_review_blocks_before_any_deletion(workspace):
    document, cloud = frozen()
    stray = COMMON + "/providers/Microsoft.Network/publicIPAddresses/added-after-review"
    cloud.bodies[stray.lower()] = tagged(stray, "Microsoft.Network/publicIPAddresses", CORE)
    run = workspace / "teardown"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "blocked" and receipt["mutation_started"] is False
    assert not cloud.deleted


@pytest.mark.parametrize("url,code", [
    ("https://graph.microsoft.com/v1.0/groups/retained", "entra-mutations-forbidden"),
    ("https://lockstore.blob.core.windows.net/x", "untrusted-service-endpoint"),
])
def test_operator_teardown_cloud_trusts_only_arm_without_any_lease_store(url, code):
    # A never-enrolled factory has no lease store: no blob host is trusted and Entra writes stay forbidden.
    cloud = fl.Cloud(request(), opener=object(), command_runner=lambda *args, **kwargs: pytest.fail("No auth"))
    with pytest.raises(fl.Blocked, match=code):
        cloud.request("DELETE", url, "https://graph.microsoft.com")


def test_operator_teardown_cloud_reaches_arm_without_locks():
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            raise OSError("offline")

    cloud = fl.Cloud(request(), opener=Opener(), command_runner=lambda *args, **kwargs: pytest.fail("No auth"))
    cloud.token = lambda audience: "token"
    with pytest.raises(fl.Blocked):
        cloud.request("GET", "https://management.azure.com" + COMMON + "?api-version=2022-09-01",
                      "https://management.azure.com/")
    assert calls and calls[0].startswith("https://management.azure.com/")


class AbsentGroupsCloud(TeardownCloud):
    """aif-130 (2026-10-25): the operator removed the factory's groups with `az group delete` before teardown.

    Like ARM, a deleted group answers 404 ResourceGroupNotFound on its exact id, and anything listed
    or read beneath it fails with remote-request-failed-404 unless the caller allows a 404.
    """

    def __init__(self, gone, status=404, error_code="ResourceGroupNotFound"):
        super().__init__()
        self.gone = {value.lower() for value in gone}
        self.status, self.error_code = status, error_code
        self.bodies = {key: body for key, body in self.bodies.items()
                       if not any(key == group or key.startswith(group + "/") for group in self.gone)}

    def _missing(self, resource_id):
        key = resource_id.lower()
        return next((group for group in self.gone if key == group or key.startswith(group + "/")), None)

    def assert_no_active_deployments(self, scope):
        fl.require(not self._missing(scope), "remote-request-failed-404")
        super().assert_no_active_deployments(scope)

    def list_resources(self, scope):
        fl.require(not self._missing(scope), "remote-request-failed-404")
        return super().list_resources(scope)

    def arm(self, method, resource_id, api_version, allowed=(200,), headers=None):
        if method == "GET" and self._missing(resource_id):
            fl.require(self.status in allowed, "remote-request-failed-" + str(self.status))
            error = {"code": self.error_code, "message": "Resource group could not be found."}
            return self.status, {}, ({"error": error} if self.error_code else None)
        return super().arm(method, resource_id, api_version, allowed, headers)


def test_groups_already_deleted_outside_the_teardown_leave_nothing_to_delete(workspace):
    cloud = AbsentGroupsCloud([GROUP, COMMON])
    document, cloud = frozen(cloud)
    fl.validate_bootstrap_teardown(document)
    data = document["deletion"]
    assert data["resource_groups"] == [] and data["resources"] == []
    assert data["absent_resource_groups"] == sorted([GROUP.lower(), COMMON.lower()])
    # The factory's own hub DNS link still points at its recorded, now deleted VNet: it is still unlinked.
    assert data["factory_virtual_networks"] == [VNET.lower()]
    assert [row["id"] for row in data["hub_links"]] == sorted([OWN_HUB_LINK, OWN_PEERING], key=str.lower)
    run = workspace / "teardown-absent"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "succeeded", receipt.get("error_code")
    assert receipt["absent_resource_groups"] == data["absent_resource_groups"]
    assert receipt["deleted_resources"] == []
    assert sorted(value.lower() for value in cloud.deleted) == sorted([OWN_HUB_LINK.lower(), OWN_PEERING.lower()])
    assert {SPIDER_HUB_LINK.lower(), SPIDER_PEERING.lower(), HUB_ZONE.lower(), HUB_VNET.lower()} <= set(cloud.bodies)


def test_one_group_already_deleted_still_tears_down_the_other(workspace):
    cloud = AbsentGroupsCloud([GROUP])
    document, cloud = frozen(cloud)
    data = document["deletion"]
    assert data["absent_resource_groups"] == [GROUP.lower()]
    assert [row["id"].lower() for row in data["resource_groups"]] == [COMMON.lower()]
    run = workspace / "teardown-partial"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "succeeded", receipt.get("error_code")
    assert COMMON.lower() in [value.lower() for value in cloud.deleted]
    assert not any(key.startswith(COMMON.lower()) for key in cloud.bodies)


@pytest.mark.parametrize("status,error_code,code", [
    (403, "AuthorizationFailed", "remote-request-failed-403"),
    (404, "SubscriptionNotFound", "bootstrap-teardown-group-absence-unverified"),
    (404, "ResourceNotFound", "bootstrap-teardown-group-absence-unverified"),
    (404, None, "bootstrap-teardown-group-absence-unverified"),
])
def test_group_absence_must_be_proven_not_inferred_from_an_error(status, error_code, code):
    cloud = AbsentGroupsCloud([GROUP], status=status, error_code=error_code)
    with pytest.raises(fl.Blocked, match=code):
        frozen(cloud)
    assert not cloud.deleted


def test_a_recorded_group_that_reappears_after_review_blocks_before_any_change(workspace):
    cloud = AbsentGroupsCloud([GROUP, COMMON])
    document, cloud = frozen(cloud)
    cloud.gone.discard(GROUP.lower())
    cloud.bodies[GROUP.lower()] = untagged(GROUP, "Microsoft.Resources/resourceGroups")
    run = workspace / "teardown-reappeared"
    run.mkdir()
    receipt = fl.execute_bootstrap_teardown(document, run / "receipt.json", cloud=cloud, sleep=lambda _: None)
    assert receipt["status"] == "blocked"
    assert receipt["error_code"] == "bootstrap-teardown-absent-group-reappeared"
    assert not cloud.deleted


def test_absent_groups_cannot_be_added_to_a_frozen_review():
    cloud = AbsentGroupsCloud([GROUP])
    document, _ = frozen(cloud)
    document["deletion"]["absent_resource_groups"] = sorted([GROUP.lower(), COMMON.lower()])
    with pytest.raises(fl.Blocked):
        fl.validate_bootstrap_teardown(document)
