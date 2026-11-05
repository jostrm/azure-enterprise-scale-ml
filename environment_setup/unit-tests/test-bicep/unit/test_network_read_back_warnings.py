"""B (Joakim, 2026-11-05: "warn, keep core"): after the network write, a property Azure sets by itself on a created
subnet, NSG or VNet (read-only, never written by the plan) is logged as a read-back warning with its observed value,
and the stage continues. A property the plan wrote, or a core network property (address ranges, NSG, route table,
NAT gateway, service endpoints, network policies, delegations, NSG rules, peerings, DNS, DDoS), still blocks: those
are the network-security and address-planning guarantees of preserve-v1, and a Modify policy there would leave a
network nobody reviewed."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("network_preservation_cases", Path(__file__).with_name(
    "test_common_network_preservation.py"))
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)
net = cases.net


@pytest.fixture
def created():
    compiled = cases.compiled.__wrapped__()
    intent = cases.desired()
    intent["reused_resource_ids"] = []
    before = cases.inventory({}, intent)
    planned = cases.plan({}, intent)
    state, _ = cases.apply_native_arm({}, planned, compiled)
    expected = net.expected_resource_bodies(compiled, planned)
    return state, intent, before, planned, expected


def sync(state):
    for index, subnet in enumerate(state[cases.VNET]["properties"]["subnets"]):
        state[cases.VNET]["properties"]["subnets"][index] = copy.deepcopy(state[subnet["id"]])


def verify(created_case, state):
    _, intent, before, planned, expected = created_case
    return net.verify_common_network(planned, before=before, after=cases.inventory(state, intent),
                                     expected_resources=expected)


def test_no_platform_property_means_no_warnings(created):
    state = created[0]
    result = verify(created, state)
    assert result["preserved"] and "read_back_warnings" not in result


@pytest.mark.parametrize("target,prop,value", [
    ("subnet", "purpose", "PrivateEndpoints"),
    ("subnet", "platformManagedTag", {"a": 1}),
    ("nsg", "platformAnnotation", "x"),
    ("vnet", "privateEndpointVNetPolicies", "Disabled"),
])
def test_a_platform_set_property_warns_with_its_value_and_continues(created, target, prop, value):
    state = created[0]
    identifier = {"subnet": cases.VNET + "/subnets/snet-one", "nsg": cases.NSG + "nsg-snet-one",
                  "vnet": cases.VNET}[target]
    state[identifier]["properties"][prop] = copy.deepcopy(value)
    sync(state)
    result = verify(created, state)
    assert result["preserved"] is True
    assert {"resource_id": identifier.lower(), "property": prop, "observed": value,
            "code": "created-network-platform-property"} in result["read_back_warnings"]


@pytest.mark.parametrize("prop,value", [
    ("routeTable", {"id": "/subscriptions/x/resourcegroups/y/providers/microsoft.network/routetables/policy"}),
    ("natGateway", {"id": "/subscriptions/x/resourcegroups/y/providers/microsoft.network/natgateways/policy"}),
    ("serviceEndpointPolicies", [{"id": "policy"}]),
])
def test_a_core_property_the_platform_adds_still_blocks(created, prop, value):
    state = created[0]
    state[cases.VNET + "/subnets/snet-one"]["properties"][prop] = copy.deepcopy(value)
    sync(state)
    with pytest.raises(net.PreservationError, match="created-network-write-properties-mismatch"):
        verify(created, state)


def test_a_written_property_that_differs_still_blocks(created):
    state = created[0]
    state[cases.VNET + "/subnets/snet-one"]["properties"]["addressPrefix"] = "10.1.8.0/26"
    sync(state)
    with pytest.raises(net.PreservationError, match="created-network-write-properties-mismatch"):
        verify(created, state)


def test_a_vnet_core_property_the_platform_adds_still_blocks(created):
    state = created[0]
    state[cases.VNET]["properties"]["ddosProtectionPlan"] = {"id": "/subscriptions/x/ddos/plan"}
    with pytest.raises(net.PreservationError, match="created-network-write-properties-mismatch"):
        verify(created, state)


def test_execution_evidence_carries_the_warnings():
    source = (Path(net.__file__)).read_text(encoding="utf-8")
    assert "read_back_warnings" in source
