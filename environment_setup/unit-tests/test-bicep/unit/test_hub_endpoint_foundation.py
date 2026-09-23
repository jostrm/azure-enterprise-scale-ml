"""Retained shared-hub endpoint allocation uses exact reviewed child operations."""

import copy
import ipaddress

import pytest

from unit.test_registered_prerequisites import (
    COMMON_VNET, FACTORY, OWNED, VAULT, FoundationRuntime, HUB, HUB_RG, Runtime, core,
    execute, external_arguments, foundation as foundation_core, no_live,
    provision_foundation, workspace,
)


SUBNET = HUB + "/subnets/snet-aifactory-private-endpoints"
CIDR = ipaddress.ip_network("10.40.0.0/24")


def subnet(identifier, prefix, **properties):
    return {"id": identifier, "properties": {
        "addressPrefix": prefix, "provisioningState": "Succeeded", **properties}}


def prepare_network(runtime, parent, *, reserve=True):
    builder = core.Builder(runtime)
    bindings = {}
    core._hub_private_endpoint_subnet(builder, HUB, CIDR, parent, bindings,
                                     reserve_access_subnets=reserve)
    return builder, bindings


def test_new_retained_hub_subnet_needs_no_factory_network_or_adls():
    builder, bindings = prepare_network(Runtime(), None)
    assert bindings["hub_private_endpoint_subnet_id"] == SUBNET
    assert builder.effects == [{"kind": "arm-create", "id": SUBNET, "api": core.NETWORK_API,
        "body": {"properties": {"addressPrefix": "10.40.0.0/27", "privateEndpointNetworkPolicies": "Disabled"}},
        "ownership": "external-retain-never-enroll-or-delete"}]


def test_allocates_inside_approved_space_without_overlapping_existing_or_planned_children():
    parent = {"properties": {"subnets": [subnet(HUB + "/subnets/unrelated", "10.40.0.0/25")]}}
    before = copy.deepcopy(parent)
    builder, _ = prepare_network(Runtime(), parent)
    assert builder.effects[0]["body"]["properties"]["addressPrefix"] == "10.40.0.128/27"
    assert parent == before
    assert all(effect["id"] != HUB for effect in builder.effects)


def test_existing_shared_subnet_is_retained_without_reconciliation():
    value = subnet(SUBNET, "10.40.0.32/27", privateEndpointNetworkPolicies="Enabled",
                   networkSecurityGroup={"id": HUB_RG + "/providers/microsoft.network/networksecuritygroups/retained"})
    runtime = Runtime()
    runtime.resources[SUBNET] = value
    builder, bindings = prepare_network(runtime, {"properties": {"subnets": [value]}})
    assert not builder.effects
    assert bindings["hub_private_endpoint_subnet_id"] == SUBNET
    assert runtime.resources[SUBNET] == value


@pytest.mark.parametrize("parent", [{}, {"properties": {"subnets": None}},
                                  {"properties": {"subnets": [subnet(SUBNET, "10.40.0.0/27")]}}])
def test_partial_or_changed_inventory_fails_closed(parent):
    with pytest.raises(core.PrerequisiteError, match="inventory"):
        prepare_network(Runtime(), parent)


@pytest.mark.parametrize("change", [
    {"delegations": [{"name": "dns", "properties": {"serviceName": "Microsoft.Network/dnsResolvers"}}]},
    {"provisioningState": "Updating"}, {"addressPrefix": "10.41.0.0/27"},
])
def test_incompatible_existing_private_subnet_is_not_overwritten(change):
    value = subnet(SUBNET, "10.40.0.32/27", **change)
    runtime = Runtime()
    runtime.resources[SUBNET] = value
    with pytest.raises(core.PrerequisiteError, match="incompatible"):
        prepare_network(runtime, {"properties": {"subnets": [value]}})
    assert not runtime.writes


def test_reserved_gateway_and_resolver_space_is_not_used_when_other_space_is_full():
    parent = {"properties": {"subnets": [
        subnet(HUB + "/subnets/first", "10.40.0.0/25"),
        subnet(HUB + "/subnets/second", "10.40.0.128/26"),
        subnet(HUB + "/subnets/third", "10.40.0.192/28")]}}
    builder, bindings = prepare_network(Runtime(), parent)
    assert builder.blockers and not builder.effects
    assert "hub_private_endpoint_subnet_id" not in bindings


def test_shared_hub_graph_produces_retained_binding_with_and_without_vpn(workspace):
    for setup in (False, True):
        foundation_runtime = FoundationRuntime()
        foundation = provision_foundation(workspace, foundation_runtime, HUB_RG)
        runtime = Runtime()
        runtime.resources.update(copy.deepcopy(foundation_runtime.resources))
        args = external_arguments(workspace, setup=setup)
        args["context"]["coordination_mode"] = "connectivity-hub"
        args["context"]["hub_resource_group_id"] = HUB_RG
        args["context"]["coordination"] = foundation["coordination"]
        plan = core.prepare(**args, runtime=runtime)
        assert plan["can_execute"], plan["blockers"]
        assert plan["bindings"]["hub_private_endpoint_subnet_id"] == SUBNET
        assert plan["bindings"]["network"]["owned"] is False
        assert HUB_RG not in plan["context"]["owned_resource_group_ids"]
        result = execute(plan, workspace, runtime)
        assert result["status"] == "succeeded"
        assert result["bindings"]["hub_private_endpoint_subnet_id"] == SUBNET
        assert runtime.resources[SUBNET]["properties"]["provisioningState"] == "Succeeded"


def shared_arguments(workspace, runtime, *, setup=False):
    initial = FoundationRuntime()
    receipt = provision_foundation(workspace, initial, HUB_RG)
    runtime.resources.update(copy.deepcopy(initial.resources))
    args = external_arguments(workspace, setup=setup)
    args["context"].update(coordination_mode="connectivity-hub", hub_resource_group_id=HUB_RG,
                           coordination=receipt["coordination"])
    return args


class LeasedHubRuntime(Runtime):
    def arm(self, method, identifier, *args, **kwargs):
        if method != "GET" and identifier.lower().startswith(HUB_RG + "/"):
            assert foundation_core.lock_blob(HUB_RG) in self.leases
        return super().arm(method, identifier, *args, **kwargs)


def test_second_factory_another_region_reuses_retained_subnet_under_same_physical_hub_lease(workspace):
    runtime = LeasedHubRuntime()
    args = shared_arguments(workspace, runtime)
    first_plan = core.prepare(**args, runtime=runtime)
    first = execute(first_plan, workspace, runtime)
    assert first["status"] == "succeeded", first
    shared_before = copy.deepcopy(runtime.resources[SUBNET])
    hub_before = copy.deepcopy(runtime.resources[HUB])
    writes_before = len(runtime.writes)
    second_factory, second_scale = "55555555-5555-5555-5555-555555555555", "66666666-6666-6666-6666-666666666666"
    register = workspace[0] / "azurefactory" / "register.json"
    document = core.enrollment.parse_json(register.read_bytes())
    document["factories"][0].update(id=second_factory, region="northeurope")
    document["factories"][0]["scale_sets"][0]["id"] = second_scale
    register.write_bytes(core.canonical(document))
    second_group, second_vnet = OWNED + "-second", COMMON_VNET.replace("/common/", "/common-second/")
    runtime.resources[second_group] = {"id": second_group, "location": "northeurope", "tags": {
        "aifactory.factory_id": second_factory, "aifactory.scaleset_id": second_scale}}
    runtime.resources[second_vnet] = {"id": second_vnet, "location": "northeurope", "properties": {
        "addressSpace": {"addressPrefixes": ["172.16.16.0/20"]}}}
    args["scope"].update(factory_id=second_factory, scale_set_id=second_scale)
    args["bootstrap_config"]["dev_vnet_cidr"] = "172.16.16.0/20"
    args["context"].update(owned_resource_group_ids=[second_group], integrated_vnet_id=second_vnet,
                           integrated_vnet_cidr="172.16.16.0/20",
                           seeding_keyvault_id=VAULT.replace("/common/", "/common-second/"))
    second_plan = core.prepare(**args, runtime=runtime)
    assert second_plan["can_execute"], second_plan["blockers"]
    assert second_plan["bindings"]["hub_private_endpoint_subnet_id"] == SUBNET
    assert HUB_RG in second_plan["lock_scopes"]
    assert not any(effect.get("id") in (SUBNET, HUB) for effect in second_plan["effects"])
    second = execute(second_plan, workspace, runtime)
    assert second["status"] == "succeeded", second
    assert runtime.resources[SUBNET] == shared_before and runtime.resources[HUB] == hub_before
    assert second["bindings"]["network"]["owned"] is False
    assert second["bindings"]["hub_private_endpoint_subnet_id"] == first["bindings"]["hub_private_endpoint_subnet_id"]
    assert all(write[2] not in (SUBNET, HUB) for write in runtime.writes[writes_before:])
    assert not runtime.leases


def test_access_children_stay_in_reused_hub_region_without_moving_factory_network(workspace):
    runtime = LeasedHubRuntime()
    args = shared_arguments(workspace, runtime, setup=True)
    runtime.resources[HUB] = {"id": HUB, "location": "westeurope", "properties": {
        "addressSpace": {"addressPrefixes": [str(CIDR)]}, "subnets": []}}
    plan = core.prepare(**args, runtime=runtime)
    assert plan["can_execute"], plan["blockers"]
    assert not any(effect.get("id") == HUB and effect["kind"] == "arm-create" for effect in plan["effects"])
    hub_children = [effect for effect in plan["effects"]
                    if effect.get("id", "").startswith(HUB_RG + "/")
                    and effect.get("body", {}).get("location") not in (None, "global")]
    assert len(hub_children) == 4
    assert all(effect["body"]["location"] == "westeurope" for effect in hub_children)
    bastion = next(effect for effect in plan["effects"] if "/bastionHosts/" in effect.get("id", ""))
    assert bastion["body"]["location"] == "swedencentral"
    result = execute(plan, workspace, runtime)
    assert result["status"] == "succeeded", result
    assert runtime.resources[HUB]["location"] == "westeurope"
    assert runtime.resources[COMMON_VNET]["location"] == "swedencentral"


def test_hub_subnet_inventory_drift_during_lock_acquisition_prevents_all_network_writes(workspace):
    runtime = LeasedHubRuntime()
    args = shared_arguments(workspace, runtime)
    runtime.resources[HUB] = {"id": HUB, "location": "swedencentral", "properties": {
        "addressSpace": {"addressPrefixes": [str(CIDR)]}, "subnets": []}}
    plan = core.prepare(**args, runtime=runtime)
    runtime.on_acquire = lambda: runtime.resources[HUB]["properties"]["subnets"].append(
        subnet(HUB + "/subnets/concurrently-added", "10.40.0.0/27"))
    result = execute(plan, workspace, runtime)
    assert result["status"] == "uncertain" and result["error"] == "prerequisites-changed-before-lock"
    assert not runtime.writes and SUBNET not in runtime.resources
    assert foundation_core.lock_blob(HUB_RG) in runtime.leases


@pytest.mark.parametrize("tag", ["aifactory.factory_id", "AIFactory.ScaleSet_ID"])
def test_shared_hub_cannot_adopt_a_factory_owned_vnet(workspace, tag):
    runtime = Runtime()
    args = shared_arguments(workspace, runtime)
    runtime.resources[HUB] = {"id": HUB, "location": "swedencentral", "tags": {tag: FACTORY},
                              "properties": {"addressSpace": {"addressPrefixes": [str(CIDR)]}, "subnets": []}}
    with pytest.raises(core.PrerequisiteError, match="shared-hub-vnet-has-factory-ownership"):
        core.prepare(**args, runtime=runtime)
    assert not runtime.writes


def test_integrated_shared_coordination_remains_blocked_without_retention_contract(workspace):
    runtime = Runtime()
    args = shared_arguments(workspace, runtime, setup=True)
    args["bootstrap_config"]["access_hub_mode"] = "integrated"
    before = copy.deepcopy(args)
    with pytest.raises(core.PrerequisiteError, match="shared-coordination-requires-explicit-external-hub"):
        core.prepare(**args, runtime=runtime)
    assert args == before and not runtime.writes
