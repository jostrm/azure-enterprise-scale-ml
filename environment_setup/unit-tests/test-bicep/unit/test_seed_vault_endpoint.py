"""Seeding Key Vault private endpoint as a planned network-foundation effect; offline, no Azure calls."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("common_network_preservation", ROOT / "bootstrap/lib/common_network_preservation.py")
net = importlib.util.module_from_spec(spec)
spec.loader.exec_module(net)
SUB = "11111111-1111-1111-1111-111111111111"
RG = f"/subscriptions/{SUB}/resourcegroups/aif-1-esml-common-sdc-dev-001"
VNET = RG + "/providers/microsoft.network/virtualnetworks/vnt-esmlcmn-sdc-dev-001"
SUBNET = VNET + "/subnets/snet-esml-cmn-001"
VAULT = RG + "/providers/microsoft.keyvault/vaults/aifseed01"
NAME = "pend-aifseed01-to-vnt-esmlcmn-sdc-dev-001"
ENDPOINT = RG + "/providers/microsoft.network/privateendpoints/" + NAME
TAGS = {"aifactory.factory_id": "f1", "aifactory.scaleset_id": "s1"}


def planned(existing=None):
    return net.plan_seed_vault_endpoint(vault_id=VAULT, vnet_id=VNET, subnet_name="snet-esml-cmn-001",
                                        location="swedencentral", owner_tags=TAGS, existing=existing)


def endpoint_body(nic=None, vault=VAULT, subnet=SUBNET, state="Succeeded", manual=False):
    nic = nic or RG + "/providers/microsoft.network/networkinterfaces/" + NAME + "-nic"
    connection = {"name": NAME + "-connection", "properties": {"privateLinkServiceId": vault, "groupIds": ["vault"]}}
    key = "manualPrivateLinkServiceConnections" if manual else "privateLinkServiceConnections"
    return {"id": ENDPOINT, "name": NAME, "type": "Microsoft.Network/privateEndpoints", "location": "swedencentral",
            "properties": {"provisioningState": state, "subnet": {"id": subnet}, key: [connection],
                           "networkInterfaces": [{"id": nic}]}}


class Cloud:
    def __init__(self, states):
        self.states, self.calls = list(states), []

    def arm(self, method, identifier, api_version, data=None, allowed=(200,)):
        self.calls.append((method, identifier.lower(), copy.deepcopy(data)))
        if method == "PUT":
            return 201, {}, {}
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return (404, {}, {"error": {"code": "ResourceNotFound"}}) if state is None else (200, {}, state)


def test_absent_endpoint_is_a_planned_owned_create_with_the_legacy_name():
    plan = planned()
    assert plan["resource_id"] == ENDPOINT and plan["action"] == "create"
    assert plan["nic_id"] == RG + "/providers/microsoft.network/networkinterfaces/" + NAME + "-nic"
    assert plan["body"] == {"location": "swedencentral", "tags": TAGS, "properties": {
        "subnet": {"id": SUBNET}, "customNetworkInterfaceName": NAME + "-nic",
        "privateLinkServiceConnections": [{"name": NAME + "-connection", "properties": {
            "privateLinkServiceId": VAULT, "groupIds": ["vault"]}}]}}
    assert net.seed_vault_endpoint_effect(plan) == {"kind": "create-private-endpoint", "resource_id": ENDPOINT,
                                                    "target_resource_id": VAULT, "group_id": "vault"}


def test_existing_legacy_endpoint_to_this_vault_is_reused_not_duplicated():
    nic = RG + "/providers/microsoft.network/networkinterfaces/pend-aifseed01-to-vnt-esmlcm.nic.40076cdc"
    plan = planned(endpoint_body(nic=nic, manual=True))
    assert plan["action"] == "reuse" and plan["body"] is None and plan["nic_id"] == nic.lower()
    assert net.seed_vault_endpoint_effect(plan)["kind"] == "reuse-private-endpoint"


@pytest.mark.parametrize("body", [endpoint_body(vault=RG + "/providers/microsoft.keyvault/vaults/other"),
                                  endpoint_body(subnet=VNET + "/subnets/other"),
                                  endpoint_body(state="Failed")])
def test_legacy_name_on_another_target_subnet_or_state_is_refused(body):
    with pytest.raises(net.PreservationError, match="seed-vault-endpoint-conflict"):
        planned(body)


def test_execute_creates_once_and_waits_for_success():
    cloud = Cloud([None, endpoint_body(state="Updating"), endpoint_body()])
    result = net.execute_seed_vault_endpoint(planned(), cloud=cloud, assert_lease=lambda: True, sleeper=lambda _: None)
    assert [call[0] for call in cloud.calls] == ["GET", "PUT", "GET", "GET"]
    assert cloud.calls[1][2] == planned()["body"]
    assert result == {"resource_id": ENDPOINT, "nic_id": planned()["nic_id"], "created": True}


def test_execute_reuse_and_retry_never_write():
    reused = net.execute_seed_vault_endpoint(planned(endpoint_body()), cloud=Cloud([endpoint_body()]),
                                             assert_lease=lambda: True)
    assert reused["created"] is False
    cloud = Cloud([endpoint_body()])  # an interrupted create already succeeded: idempotent, no second PUT
    assert net.execute_seed_vault_endpoint(planned(), cloud=cloud, assert_lease=lambda: True)["created"] is True
    assert [call[0] for call in cloud.calls] == ["GET"]


def test_execute_refuses_a_foreign_body_without_writing():
    cloud = Cloud([endpoint_body(vault=RG + "/providers/microsoft.keyvault/vaults/other")])
    with pytest.raises(net.PreservationError, match="seed-vault-endpoint-conflict"):
        net.execute_seed_vault_endpoint(planned(), cloud=cloud, assert_lease=lambda: True)
    assert [call[0] for call in cloud.calls] == ["GET"]


def test_only_the_planned_endpoint_associations_leave_the_subnet_body():
    plan = planned()
    ipconfig = plan["nic_id"] + "/ipconfigurations/privateendpointipconfig.1"
    body = {"id": SUBNET, "properties": {"addressPrefix": "10.1.0.0/26",
            "privateEndpoints": [{"id": ENDPOINT.replace("privateendpoints", "privateEndpoints")}, {"id": "foreign-pe"}],
            "ipConfigurations": [{"id": ipconfig}, {"id": "foreign-ipconfig"}]}}
    stripped = net.without_seed_endpoint_associations(body, plan)
    assert stripped["properties"]["privateEndpoints"] == [{"id": "foreign-pe"}]
    assert stripped["properties"]["ipConfigurations"] == [{"id": "foreign-ipconfig"}]
    only = {"id": SUBNET, "properties": {"privateEndpoints": [{"id": ENDPOINT}], "ipConfigurations": [{"id": ipconfig}]}}
    assert net.without_seed_endpoint_associations(only, plan)["properties"] == {}
    assert body["properties"]["privateEndpoints"][1] == {"id": "foreign-pe"}  # the input is not mutated
    assert net.without_seed_endpoint_associations(body, None) == body


def test_network_verification_accepts_only_the_planned_endpoint_on_the_created_common_subnet():
    base = importlib.util.spec_from_file_location("network_preservation_cases", Path(__file__).with_name(
        "test_common_network_preservation.py"))
    cases = importlib.util.module_from_spec(base)
    base.loader.exec_module(cases)
    compiled = cases.compiled.__wrapped__()
    state, intent = cases.initial(), cases.desired()
    before = cases.inventory(state, intent)
    frozen = cases.plan(state, intent)
    state, _ = cases.apply_native_arm(state, frozen, compiled)
    endpoint = cases.net.plan_seed_vault_endpoint(
        vault_id=cases.RG + "/providers/microsoft.keyvault/vaults/aifseed01", vnet_id=cases.VNET,
        subnet_name="snet-one", location="westeurope", owner_tags=TAGS)
    common = cases.VNET + "/subnets/snet-one"
    references = {"privateEndpoints": [{"id": endpoint["resource_id"]}],
                  "ipConfigurations": [{"id": endpoint["nic_id"] + "/ipconfigurations/privateendpointipconfig.1"}]}
    state[common]["properties"].update(copy.deepcopy(references))
    for row in state[cases.VNET]["properties"]["subnets"]:
        if row["id"] == common:
            row["properties"].update(copy.deepcopy(references))
    after = cases.inventory(state, intent)
    expected = cases.net.expected_resource_bodies(compiled, frozen)
    with pytest.raises(cases.net.PreservationError, match="unexpected-new-subnet-association"):
        cases.net.verify_common_network(frozen, before=before, after=after, expected_resources=expected)
    assert cases.net.verify_common_network(frozen, before=before, after=after, expected_resources=expected,
                                           seed_vault_endpoint=endpoint)["preserved"] is True
    state[common]["properties"]["privateEndpoints"].append({"id": "foreign-pe"})
    with pytest.raises(cases.net.PreservationError, match="unexpected-new-subnet-association"):
        cases.net.verify_common_network(frozen, before=before, after=cases.inventory(state, intent),
                                        expected_resources=expected, seed_vault_endpoint=endpoint)


# aif-146 (2026-11-05, Standalone + public, Scenario 1): once the seed endpoint exists, Azure also sets the subnet's
# read-only purpose "PrivateEndpoints"; finalization refused created-network-write-properties-mismatch on the common subnet.
def test_the_planned_endpoint_also_takes_the_purpose_it_caused():
    plan = planned()
    ipconfig = plan["nic_id"] + "/ipconfigurations/privateendpointipconfig.1"
    only = {"id": SUBNET, "properties": {"privateEndpoints": [{"id": ENDPOINT}], "ipConfigurations": [{"id": ipconfig}],
                                         "purpose": "PrivateEndpoints"}}
    assert net.without_seed_endpoint_associations(only, plan)["properties"] == {}
    shared = copy.deepcopy(only)
    shared["properties"]["privateEndpoints"].append({"id": "foreign-pe"})
    assert net.without_seed_endpoint_associations(shared, plan)["properties"]["purpose"] == "PrivateEndpoints"
    other = copy.deepcopy(only)
    other["properties"]["purpose"] = "SomethingElse"
    assert net.without_seed_endpoint_associations(other, plan)["properties"] == {"purpose": "SomethingElse"}
    unrelated = {"id": SUBNET, "properties": {"purpose": "PrivateEndpoints"}}
    assert net.without_seed_endpoint_associations(unrelated, plan)["properties"] == {"purpose": "PrivateEndpoints"}


def test_network_verification_accepts_the_purpose_azure_sets_for_the_planned_endpoint():
    base = importlib.util.spec_from_file_location("network_preservation_cases", Path(__file__).with_name(
        "test_common_network_preservation.py"))
    cases = importlib.util.module_from_spec(base)
    base.loader.exec_module(cases)
    compiled = cases.compiled.__wrapped__()
    state, intent = cases.initial(), cases.desired()
    before = cases.inventory(state, intent)
    frozen = cases.plan(state, intent)
    state, _ = cases.apply_native_arm(state, frozen, compiled)
    endpoint = cases.net.plan_seed_vault_endpoint(
        vault_id=cases.RG + "/providers/microsoft.keyvault/vaults/aifseed01", vnet_id=cases.VNET,
        subnet_name="snet-one", location="westeurope", owner_tags=TAGS)
    common = cases.VNET + "/subnets/snet-one"
    references = {"privateEndpoints": [{"id": endpoint["resource_id"]}],
                  "ipConfigurations": [{"id": endpoint["nic_id"] + "/ipconfigurations/privateendpointipconfig.1"}],
                  "purpose": "PrivateEndpoints"}
    state[common]["properties"].update(copy.deepcopy(references))
    for row in state[cases.VNET]["properties"]["subnets"]:
        if row["id"] == common:
            row["properties"].update(copy.deepcopy(references))
    after = cases.inventory(state, intent)
    expected = cases.net.expected_resource_bodies(compiled, frozen)
    assert cases.net.verify_common_network(frozen, before=before, after=after, expected_resources=expected,
                                           seed_vault_endpoint=endpoint)["preserved"] is True
