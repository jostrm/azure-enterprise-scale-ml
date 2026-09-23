"""Offline compiled-ARM and native-resource snapshot tests; no Azure mutations."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("common_network_preservation", ROOT / "bootstrap/lib/common_network_preservation.py")
net = importlib.util.module_from_spec(spec)
spec.loader.exec_module(net)
SUB = "11111111-1111-1111-1111-111111111111"
RG = f"/subscriptions/{SUB}/resourcegroups/shared"
VNET = RG + "/providers/microsoft.network/virtualnetworks/shared"
HUB = RG + "/providers/microsoft.network/virtualnetworks/hub"
NSG = RG + "/providers/microsoft.network/networksecuritygroups/"


def resource(identifier, props, **extra):
    return {"id": identifier, "etag": 'W/"retained-etag"', "properties": {
        "provisioningState": "Succeeded", **props}, **extra}


def subnet(name, cidr, **properties):
    return resource(VNET + "/subnets/" + name.lower(), {"addressPrefix": cidr, **properties}, name=name)


def desired(factory="one", block="1"):
    return {"factory_id": factory, "vnet_id": VNET, "approved_address_prefixes": ["10.1.0.0/20"],
            "owned_resource_ids": [], "reused_resource_ids": [VNET + "/subnets/azurebastionsubnet"],
            "parameters": {"env": "dev", "location": "westeurope", "locationSuffix": "weu",
                           "commonResourceSuffix": "-001", "vnetNameBase": "unused",
                           "vnetNameFull_param": "shared", "vnetResourceGroup_param": "shared",
                           "tags": {"factory": factory}, "common_vnet_cidr": "10.1.0.0/20",
                           "common_subnet_name": "snet-" + factory,
                           "common_pbi_subnet_name": "snet-" + factory + "-pbi",
                           "common_subnet_cidr": f"10.1.{block}.0/26",
                           "common_subnet_scoring_cidr": f"10.1.{block}.64/26",
                           "common_pbi_subnet_cidr": f"10.1.{block}.128/26",
                           "common_bastion_subnet_cidr": "10.1.0.128/26", "cidr_range": ""}}


def initial():
    children = [
        subnet("GatewaySubnet", "10.1.0.0/27", addressPrefixes=None, routeTable={"id": "external-route-table"}),
        subnet("dns-inbound", "10.1.0.32/28",
               delegations=[{"name": "resolver", "properties": {"serviceName": "Microsoft.Network/dnsResolvers"}}]),
        subnet("private-endpoints", "10.1.0.64/27",
               privateEndpoints=[{"id": "external-pe"}], privateEndpointNetworkPolicies="Disabled"),
        subnet("AzureBastionSubnet", "10.1.0.128/26", networkSecurityGroup={"id": NSG + "external-bastion"}),
    ]
    parent = resource(VNET, {"addressSpace": {"addressPrefixes": ["10.1.0.0/20"]},
                            "dhcpOptions": {"dnsServers": ["10.90.0.4", "10.90.0.5"]},
                            "subnets": children,
                            "virtualNetworkPeerings": [resource(VNET + "/virtualnetworkpeerings/retained",
                                {"remoteVirtualNetwork": {"id": HUB}, "allowForwardedTraffic": True})]},
                      location="westeurope", tags={"external": "owner"})
    return {VNET: parent, **{s["id"]: copy.deepcopy(s) for s in children}}


def inventory(state, intent):
    resources = copy.deepcopy(state)
    for identifier in net.required_resource_ids(intent):
        resources.setdefault(identifier, None)
    return {"complete": True, "resources": resources,
            "vnet_ranges": [{"id": VNET, "address_prefixes": ["10.1.0.0/20"]},
                            {"id": HUB, "address_prefixes": ["10.90.0.0/24"]}],
            "reserved_ranges": ["172.20.0.0/24"]}


def plan(state, intent):
    return net.plan_common_network(vnet=state.get(VNET), desired=intent, inventory=inventory(state, intent))


@pytest.fixture(scope="module")
def compiled():
    compiler = shutil.which("bicep")
    if not compiler:
        pytest.skip("Standalone Bicep is required for emitted ARM preservation tests")
    result = subprocess.run([compiler, "build", str(ROOT / net.ENTRYPOINT), "--stdout", "--no-restore"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def evaluate(value, parameters, index=0):
    """Small offline ARM-expression interpreter for this emitted module only."""
    if isinstance(value, dict):
        return {k: evaluate(v, parameters, index) for k, v in value.items()}
    if isinstance(value, list):
        return [evaluate(v, parameters, index) for v in value]
    if not isinstance(value, str) or not value.startswith("["):
        return value
    calls = {"parameters": lambda name: parameters[name], "copyIndex": lambda: index,
             "format": lambda text, *args: text.format(*args), "length": len}

    def walk(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Call):
            return calls[node.func.id](*[walk(arg) for arg in node.args])
        if isinstance(node, ast.Attribute):
            return walk(node.value)[node.attr]
        if isinstance(node, ast.Subscript):
            return walk(node.value)[walk(node.slice)]
        raise AssertionError("Unreviewed ARM expression: " + value)
    return copy.deepcopy(walk(ast.parse(value[1:-1], mode="eval").body))


def apply_native_arm(state, planned, compiled):
    """Model PUT replacement (not merge) using the real emitted resource bodies."""
    result = copy.deepcopy(state)
    modern = compiled["resources"][6]["properties"]["template"]
    params = {"plan": planned["deployment_parameters"]["preservationPlan"], "vnetNameFull": "shared",
              "location": "westeurope", "tags": planned["deployment_parameters"]["tags"]}
    writes = []
    for emitted in modern["resources"]:
        if "condition" in emitted and not evaluate(emitted["condition"], params):
            continue
        count = evaluate(emitted["copy"]["count"], params) if "copy" in emitted else 1
        for index in range(count):
            name = evaluate(emitted["name"], params, index)
            identifier = (VNET if emitted["type"] == "Microsoft.Network/virtualNetworks"
                          else VNET + "/subnets/" + name.split("/")[1].lower())
            assert result.get(identifier) is None, "A PUT to an existing object violates the preserve contract"
            props = evaluate(emitted["properties"], params, index)
            body = resource(identifier, props, name=name.split("/")[-1])
            if identifier == VNET:
                body.update(location=evaluate(emitted["location"], params), tags=evaluate(emitted["tags"], params))
                body["properties"].update(subnets=[], virtualNetworkPeerings=[])
            result[identifier] = body
            writes.append(identifier)
            if identifier != VNET:
                result[VNET]["properties"]["subnets"].append(copy.deepcopy(body))
    expected = net.expected_resource_bodies(compiled, planned)
    for name in params["plan"]["createNetworkSecurityGroups"]:
        identifier = NSG + name.lower()
        assert result.get(identifier) is None
        body = expected[identifier]
        result[identifier] = resource(identifier, copy.deepcopy(body["properties"]),
                                      location=body["location"], tags=copy.deepcopy(body["tags"]))
        writes.append(identifier)
    for subnet in params["plan"]["createSubnets"]:
        identifier = subnet["properties"]["networkSecurityGroup"]["id"].lower()
        result[identifier]["properties"].setdefault("subnets", []).append(
            {"id": VNET + "/subnets/" + subnet["name"].lower()})
        result[identifier]["etag"] = 'W/"association-maintained-by-network-rp"'
    return result, writes


@pytest.mark.parametrize("network_mode", ["private", "public"])
def test_compiled_repeat_and_second_factory_preserve_native_snapshots(compiled, network_mode):
    state = initial()
    original = copy.deepcopy(state)
    one = desired()
    one["network_mode"] = network_mode  # Common network entrypoint is shared by both resource access modes.
    first = plan(state, one)
    state, writes = apply_native_arm(state, first, compiled)
    assert VNET not in writes
    assert len(writes) == 6  # Three missing canonical subnets and their NSGs.
    one["owned_resource_ids"] = first["owned_resource_ids"]
    replay = plan(state, one)
    state, writes = apply_native_arm(state, replay, compiled)
    assert writes == []
    first_factory_snapshot = {identifier: copy.deepcopy(state[identifier]) for identifier in first["owned_resource_ids"]}
    two = desired("two", "2")
    second = plan(state, two)
    state, writes = apply_native_arm(state, second, compiled)
    assert len(writes) == 6 and VNET not in writes
    assert not set(first["owned_resource_ids"]) & set(second["owned_resource_ids"])
    assert first["deletion_resource_ids"] == second["deletion_resource_ids"] == []
    for identifier, value in original.items():
        if identifier != VNET:
            assert state[identifier] == value  # ALL configs and etags, not selected fields.
    parent_before, parent_after = original[VNET], copy.deepcopy(state[VNET])
    parent_after["properties"]["subnets"] = parent_before["properties"]["subnets"]
    assert parent_after == parent_before  # DNS, peerings, tags, unknown properties are unchanged.
    for identifier in first["owned_resource_ids"]:
        assert state[identifier] == first_factory_snapshot[identifier]


def test_absent_parent_created_once_then_children_only(compiled):
    intent = desired()
    intent["reused_resource_ids"] = []
    first = plan({}, intent)
    assert first["deployment_parameters"]["preservationPlan"]["createVnet"]
    state, writes = apply_native_arm({}, first, compiled)
    assert writes.count(VNET) == 1 and len(writes) == 9
    intent["owned_resource_ids"] = first["owned_resource_ids"]
    second = plan(state, intent)
    _, writes = apply_native_arm(state, second, compiled)
    assert writes == []


def test_arm_capability_and_tamper_detection(compiled):
    assert net.validate_compiled_capability(compiled)["parent_updates"] is False
    broken = copy.deepcopy(compiled)
    del broken["resources"][5]["condition"]
    with pytest.raises(net.PreservationError, match="legacy-network-not-isolated"):
        net.validate_compiled_capability(broken)
    broken = copy.deepcopy(compiled)
    del broken["resources"][6]["properties"]["template"]["resources"][0]["condition"]
    with pytest.raises(net.PreservationError, match="destructive-preservation-parent"):
        net.validate_compiled_capability(broken)
    broken = copy.deepcopy(compiled)
    broken["resources"][6]["properties"]["mode"] = "Complete"
    with pytest.raises(net.PreservationError, match="complete-deployment-forbidden"):
        net.validate_compiled_capability(broken)


@pytest.mark.parametrize("mutation", [
    "module-resource-group", "module-subscription", "scope-variable", "forwarded-vnet",
    "forwarded-plan", "forwarded-location", "forwarded-tags", "forwarded-nsg",
    "renamed-nsg", "additional-nsg", "nested-nsg-resource", "nested-child-scope",
    "nested-parent-scope", "module-copy", "outer-expression-scope",
])
def test_capability_rejects_changed_effective_scopes_names_and_mutation_sets(compiled, mutation):
    changed = copy.deepcopy(compiled)
    modules = changed["resources"]
    modern = modules[6]
    nsgs = modules[0]["properties"]["template"]["resources"]
    if mutation == "module-resource-group":
        modern["resourceGroup"] = "another-factory"
    elif mutation == "module-subscription":
        modules[0]["subscriptionId"] = "22222222-2222-2222-2222-222222222222"
    elif mutation == "scope-variable":
        changed["variables"]["vnetResourceGroupName"] = "foreign-network"
    elif mutation.startswith("forwarded-"):
        target = mutation.removeprefix("forwarded-")
        module = modules[0] if target == "nsg" else modern
        parameter = {"vnet": "vnetNameFull", "nsg": "name"}.get(target, target)
        module["properties"]["parameters"][parameter]["value"] = "foreign-resource"
    elif mutation == "renamed-nsg":
        nsgs[0]["name"] = "unrelated-security-group"
    elif mutation == "additional-nsg":
        nsgs.append({**copy.deepcopy(nsgs[0]), "name": "another-security-group"})
    elif mutation == "nested-nsg-resource":
        nsgs[0]["resources"] = [{"type": "securityRules", "name": "unreviewed", "properties": {}}]
    elif mutation == "nested-child-scope":
        modern["properties"]["template"]["resources"][1]["scope"] = "foreign-vnet"
    elif mutation == "nested-parent-scope":
        modern["properties"]["template"]["resources"][0]["resourceGroup"] = "foreign-network"
    elif mutation == "module-copy":
        modern["copy"] = {"name": "extra", "count": 2}
    else:
        modern["properties"]["expressionEvaluationOptions"]["scope"] = "outer"
    with pytest.raises(net.PreservationError):
        net.validate_compiled_capability(changed)


def test_selected_source_compiles_and_fingerprint_is_enforced(compiled):
    proof = net.assert_preservation_capability(ROOT)
    assert proof["profile"] == "preserve-v1" and proof["compiled_arm_sha256"] == net.digest(compiled)
    assert proof["published_ref_verified"] is False
    with pytest.raises(net.PreservationError, match="reviewed-network-payload-required"):
        net.assert_preservation_capability(ROOT, expected_payload_sha256="0" * 64)


@pytest.mark.parametrize("kind,error", [
    ("vnet", "live-vnet-address-overlap"), ("reserved", "reserved-routing-address-overlap"),
    ("subnet", "live-subnet-address-overlap"), ("parent", "parent-address-space-change"),
    ("canonical", "canonical-subnet-overlap"), ("outside", "subnet-outside-approved-parent"),
])
def test_rejects_overlap_before_any_mutation(kind, error):
    state, intent = initial(), desired()
    snapshot = inventory(state, intent)
    if kind == "vnet":
        snapshot["vnet_ranges"][1]["address_prefixes"] = ["10.1.0.0/24"]
    elif kind == "reserved":
        snapshot["reserved_ranges"] = ["10.1.8.0/24"]
    elif kind == "subnet":
        intent["parameters"]["common_subnet_cidr"] = "10.1.0.0/26"
    elif kind == "parent":
        intent["approved_address_prefixes"] = ["10.1.0.0/20", "10.2.0.0/20"]
    elif kind == "canonical":
        intent["parameters"]["common_subnet_scoring_cidr"] = "10.1.1.0/26"
    else:
        intent["parameters"]["common_subnet_cidr"] = "10.2.1.0/26"
    with pytest.raises(net.PreservationError, match=error):
        net.plan_common_network(vnet=state[VNET], desired=intent, inventory=snapshot)


def test_unapproved_existing_children_cannot_be_adopted():
    intent = desired()
    intent["reused_resource_ids"] = []
    with pytest.raises(net.PreservationError, match="existing-subnet-reuse-approval-required"):
        plan(initial(), intent)


def test_complete_snapshot_and_revalidation_include_dns_etags_and_peerings():
    state, intent = initial(), desired()
    snapshot = inventory(state, intent)
    planned = net.plan_common_network(vnet=state[VNET], desired=intent, inventory=snapshot)
    assert net.revalidate_common_network(planned, vnet=state[VNET], inventory=snapshot) == planned
    snapshot["resources"][VNET]["properties"]["dhcpOptions"]["dnsServers"].append("10.90.0.6")
    with pytest.raises(net.PreservationError, match="inventory-changed"):
        net.revalidate_common_network(planned, vnet=state[VNET], inventory=snapshot)
    snapshot = inventory(state, intent)
    del snapshot["resources"][net.required_resource_ids(intent)[1]]
    with pytest.raises(net.PreservationError, match="incomplete-network-inventory"):
        net.plan_common_network(vnet=state[VNET], desired=intent, inventory=snapshot)


def test_post_deployment_native_probe_checks_all_retained_configuration(compiled):
    state, intent = initial(), desired()
    before = inventory(state, intent)
    planned = plan(state, intent)
    state, _ = apply_native_arm(state, planned, compiled)
    state[VNET]["etag"] = 'W/"parent-changed-after-child-creation"'
    after = inventory(state, intent)
    expected = net.expected_resource_bodies(compiled, planned)
    assert net.verify_common_network(planned, before=before, after=after, expected_resources=expected)["preserved"] is True
    for key in ("dhcpOptions", "virtualNetworkPeerings"):
        changed = copy.deepcopy(after)
        del changed["resources"][VNET]["properties"][key]
        with pytest.raises(net.PreservationError, match="retained-vnet-configuration-changed"):
            net.verify_common_network(planned, before=before, after=changed, expected_resources=expected)
    changed = copy.deepcopy(after)
    changed["resources"][VNET + "/subnets/gatewaysubnet"]["etag"] = 'W/"unexpected-write"'
    with pytest.raises(net.PreservationError, match="retained-network-resource-changed"):
        net.verify_common_network(planned, before=before, after=changed, expected_resources=expected)


def test_existing_nsg_allows_only_planned_service_managed_reverse_associations(compiled):
    state, intent = initial(), desired()
    nsg_id = NSG + "nsg-snet-one"
    state[nsg_id] = resource(nsg_id, {"securityRules": [{"name": "retained", "properties": {"access": "Deny"}}],
                                    "subnets": [{"id": VNET + "/subnets/gatewaysubnet"}]},
                             location="westeurope", tags={"owner": "external"})
    intent["reused_resource_ids"].append(nsg_id)
    before = inventory(state, intent)
    planned = plan(state, intent)
    assert nsg_id not in planned["mutation_resource_ids"]
    state, _ = apply_native_arm(state, planned, compiled)
    expected = net.expected_resource_bodies(compiled, planned)
    after = inventory(state, intent)
    assert net.verify_common_network(planned, before=before, after=after, expected_resources=expected)["preserved"]
    for mutation in ("unplanned-association", "removed-association", "security-rule", "tags"):
        changed = copy.deepcopy(after)
        nsg = changed["resources"][nsg_id]
        if mutation == "unplanned-association":
            nsg["properties"]["subnets"].append({"id": VNET + "/subnets/unplanned"})
        elif mutation == "removed-association":
            nsg["properties"]["subnets"] = []
        elif mutation == "security-rule":
            nsg["properties"]["securityRules"][0]["properties"]["access"] = "Allow"
        else:
            nsg["tags"]["owner"] = "different"
        with pytest.raises(net.PreservationError, match="retained-network-resource-changed"):
            net.verify_common_network(planned, before=before, after=changed, expected_resources=expected)


@pytest.mark.parametrize("mutation", [
    "wrong-cidr", "missing-nsg", "wrong-nsg", "wrong-endpoint", "wrong-nsg-rule",
    "missing-nsg-rule", "wrong-parent-address-space", "unexpected-parent-dns", "unexpected-delegation",
])
def test_created_resource_ids_and_succeeded_status_do_not_mask_wrong_properties(compiled, mutation):
    intent = desired()
    intent["reused_resource_ids"] = []
    before = inventory({}, intent)
    planned = plan({}, intent)
    state, _ = apply_native_arm({}, planned, compiled)
    expected = net.expected_resource_bodies(compiled, planned)
    assert net.verify_common_network(planned, before=before, after=inventory(state, intent),
                                     expected_resources=expected)["preserved"]
    target = state[VNET + "/subnets/snet-one"]["properties"]
    if mutation == "wrong-cidr":
        target["addressPrefix"] = "10.1.8.0/26"
    elif mutation == "missing-nsg":
        del target["networkSecurityGroup"]
    elif mutation == "wrong-nsg":
        target["networkSecurityGroup"]["id"] = NSG + "unrelated"
    elif mutation == "wrong-endpoint":
        target["serviceEndpoints"][0]["service"] = "Microsoft.Sql"
    elif mutation == "wrong-nsg-rule":
        state[NSG + "nsg-snet-one"]["properties"]["securityRules"][0]["properties"]["access"] = "Deny"
    elif mutation == "missing-nsg-rule":
        state[NSG + "nsg-snet-one"]["properties"]["securityRules"] = []
    elif mutation == "wrong-parent-address-space":
        state[VNET]["properties"]["addressSpace"]["addressPrefixes"] = ["10.2.0.0/20"]
    elif mutation == "unexpected-parent-dns":
        state[VNET]["properties"]["dhcpOptions"] = {"dnsServers": ["10.90.0.6"]}
    else:
        target["delegations"] = [{"name": "unplanned", "properties": {"serviceName": "Microsoft.Web/serverFarms"}}]
    for index, subnet in enumerate(state[VNET]["properties"]["subnets"]):
        state[VNET]["properties"]["subnets"][index] = copy.deepcopy(state[subnet["id"]])
    with pytest.raises(net.PreservationError, match="created-network-write-properties-mismatch"):
        net.verify_common_network(planned, before=before, after=inventory(state, intent), expected_resources=expected)


def test_created_resources_accept_only_explicit_read_only_fields_and_defaults(compiled):
    intent = desired()
    intent["reused_resource_ids"] = []
    before = inventory({}, intent)
    planned = plan({}, intent)
    state, _ = apply_native_arm({}, planned, compiled)
    state[VNET]["properties"].update(enableDdosProtection=False, enableVmProtection=False,
                                    dhcpOptions={"dnsServers": []}, resourceGuid="generated")
    for identifier in planned["mutation_resource_ids"]:
        value = state[identifier]
        value["type"] = net.resource_type(identifier)
        if "/subnets/" in identifier:
            props = value["properties"]
            props.setdefault("privateEndpointNetworkPolicies", "Enabled")
            props.setdefault("privateLinkServiceNetworkPolicies", "Enabled")
            props.update(defaultOutboundAccess=False, serviceEndpointPolicies=[], ipConfigurations=[])
            for endpoint in props["serviceEndpoints"]:
                endpoint["provisioningState"] = "Succeeded"
            for delegation in props.get("delegations", []):
                delegation["properties"].update(provisioningState="Succeeded", actions=["Microsoft.Network/virtualNetworks/subnets/join/action"])
        elif "/networksecuritygroups/" in identifier:
            value["properties"].update(defaultSecurityRules=[], resourceGuid="generated", networkInterfaces=[], flushConnection=False)
            for rule in value["properties"]["securityRules"]:
                rule["etag"] = 'W/"azure"'
                rule["properties"]["provisioningState"] = "Succeeded"
    for index, subnet in enumerate(state[VNET]["properties"]["subnets"]):
        state[VNET]["properties"]["subnets"][index] = copy.deepcopy(state[subnet["id"]])
    assert net.verify_common_network(planned, before=before, after=inventory(state, intent),
        expected_resources=net.expected_resource_bodies(compiled, planned))["preserved"]
    with pytest.raises(net.PreservationError, match="frozen-compiled-resource-bodies-required"):
        net.verify_common_network(planned, before=before, after=inventory(state, intent))


def executor_fixture(monkeypatch, compiled):
    state, intent = initial(), desired()
    proof = {"payload_sha256": net.digest(net._source_files(ROOT)), "compiled_arm_sha256": net.digest(compiled)}
    monkeypatch.setattr(net, "_compile_capability", lambda *args, **kwargs: (compiled, proof))
    prepared = net.prepare_common_network(source_root=ROOT, desired=intent, inventory=inventory(state, intent))

    class Cloud:
        def __init__(self):
            self.state = state
            self.calls = []

        def arm(self, method, identifier, version, data=None, allowed=()):
            self.calls.append((method, identifier))
            assert "/providers/Microsoft.Resources/deployments/afnet-" in identifier
            if method == "PUT":
                assert data["properties"]["mode"] == "Incremental"
                assert data["properties"]["parameters"]["commonNetworkProfile"]["value"] == "preserve-v1"
                self.state, _ = apply_native_arm(self.state, prepared["frozen_plan"], data["properties"]["template"])
                return 202, {}, {}
            assert method == "GET"
            return 200, {}, {"properties": {"provisioningState": "Succeeded"}}
    return Cloud(), intent, prepared


def test_native_executor_revalidates_then_deploys_and_proves_retention(monkeypatch, compiled):
    cloud, intent, prepared = executor_fixture(monkeypatch, compiled)
    result = net.execute_common_network(prepared, cloud=cloud, source_root=ROOT,
        inventory_collector=lambda: inventory(cloud.state, intent), assert_lease=lambda: True, sleeper=lambda _: None)
    assert result["succeeded"]
    assert result["outputs"]["admin_subnet_id"] == VNET + "/subnets/snet-one"
    assert result["outputs"]["preservation_evidence"]["preserved"] is True
    assert [method for method, _ in cloud.calls] == ["PUT", "GET"]
    intent["owned_resource_ids"] = result["outputs"]["owned_resource_ids"]
    replay = net.prepare_common_network(source_root=ROOT, desired=intent, inventory=inventory(cloud.state, intent))
    cloud.calls.clear()
    result = net.execute_common_network(replay, cloud=cloud, source_root=ROOT,
        inventory_collector=lambda: inventory(cloud.state, intent), assert_lease=lambda: True)
    assert result["succeeded"] and result["outputs"]["deployment_id"] is None and cloud.calls == []


def test_executor_stale_inventory_and_missing_lease_prohibit_mutation(monkeypatch, compiled):
    cloud, intent, prepared = executor_fixture(monkeypatch, compiled)
    for has_lease, error in [(False, "shared-hub-lease-required"), (True, "inventory-changed")]:
        cloud.state[VNET]["etag"] = 'W/"external-writer"'
        with pytest.raises(net.PreservationError, match=error):
            net.execute_common_network(prepared, cloud=cloud, source_root=ROOT,
                inventory_collector=lambda: inventory(cloud.state, intent), assert_lease=lambda: has_lease)
        assert cloud.calls == []


def test_executor_rejects_changed_frozen_writable_body_before_transport(monkeypatch, compiled):
    cloud, intent, prepared = executor_fixture(monkeypatch, compiled)
    prepared["expected_resources"][VNET + "/subnets/snet-one"]["properties"]["addressPrefix"] = "10.1.8.0/26"
    with pytest.raises(net.PreservationError, match="frozen-compiled-resource-bodies-changed"):
        net.execute_common_network(prepared, cloud=cloud, source_root=ROOT,
            inventory_collector=lambda: inventory(cloud.state, intent), assert_lease=lambda: True)
    assert cloud.calls == []


def test_executor_unknown_outcome_never_deletes_or_claims_success(monkeypatch, compiled):
    cloud, intent, prepared = executor_fixture(monkeypatch, compiled)
    original = cloud.arm

    def pending(method, *args, **kwargs):
        if method == "GET":
            return 200, {}, {"properties": {"provisioningState": "Running"}}
        return original(method, *args, **kwargs)
    monkeypatch.setattr(cloud, "arm", pending)
    with pytest.raises(net.PreservationError, match="pending-retain-evidence"):
        net.execute_common_network(prepared, cloud=cloud, source_root=ROOT, max_polls=1,
            inventory_collector=lambda: inventory(cloud.state, intent), assert_lease=lambda: True, sleeper=lambda _: None)
    assert all(method != "DELETE" for method, _ in cloud.calls)


def test_prepare_checks_compiled_parameter_schema_before_mutation(monkeypatch, compiled):
    _, intent, _ = executor_fixture(monkeypatch, compiled)
    intent["parameters"]["enablePublicAccessWithPerimeter"] = True
    with pytest.raises(net.PreservationError, match="unknown-common-network-parameter"):
        net.prepare_common_network(source_root=ROOT, desired=intent, inventory=inventory(initial(), intent))


def test_byo_is_not_preservation_proof_and_gateway_extensions_not_silently_dropped():
    for key in ("BYO_subnets", "deployAIGatewayNetworking", "deployOnlyAIGatewayNetworking"):
        intent = desired()
        intent["parameters"][key] = True
        with pytest.raises(net.PreservationError):
            plan(initial(), intent)


def test_exact_inventory_collector_never_treats_denial_as_absence():
    class Cloud:
        def arm(self, method, identifier, version, allowed):
            assert method == "GET"
            return 403, {}, {}
    with pytest.raises(net.PreservationError, match="inventory-read-failed"):
        net.collect_inventory(Cloud(), vnet_id=VNET, other_vnet_ids=[])


def test_real_collector_transport_reads_vnet_subnets_and_nsgs_without_type_confusion():
    state, intent = initial(), desired()
    state[NSG + "nsg-snet-one"] = resource(NSG + "nsg-snet-one", {"securityRules": []})
    state[HUB] = resource(HUB, {"addressSpace": {"addressPrefixes": ["10.90.0.0/24"]}})
    calls = []

    class Cloud:
        def arm(self, method, identifier, version, allowed):
            calls.append(identifier)
            assert method == "GET" and version == net.API_VERSION and allowed == (200, 404)
            return (200, {}, copy.deepcopy(state[identifier])) if identifier in state else (404, {}, {"error": "NotFound"})
    result = net.collect_inventory(Cloud(), vnet_id=VNET, other_vnet_ids=[HUB],
                                   resource_ids=net.required_resource_ids(intent), reserved_ranges=["172.20.0.0/24"])
    assert set(calls) == set(net.required_resource_ids(intent)) | {HUB}
    assert {entry["id"] for entry in result["vnet_ranges"]} == {VNET, HUB}
    assert result["resources"][NSG + "nsg-snet-one"]["properties"]["securityRules"] == []
    assert result["resources"][VNET + "/subnets/snet-one"] is None
    intent["reused_resource_ids"].append(NSG + "nsg-snet-one")
    assert net.plan_common_network(vnet=result["resources"][VNET], desired=intent, inventory=result)
    intent["vnet_id"] = NSG + "nsg-snet-one"
    with pytest.raises(net.PreservationError, match="parent-vnet-id-required"):
        net.required_resource_ids(intent)


def peer_inputs():
    hub = resource(HUB, {"addressSpace": {"addressPrefixes": ["10.90.0.0/24"]}, "virtualNetworkPeerings": []})
    spoke = initial()[VNET]
    gateway_id = RG + "/providers/microsoft.network/virtualnetworkgateways/vpn"
    gateway = resource(gateway_id, {"gatewayType": "Vpn", "ipConfigurations": [{
        "properties": {"subnet": {"id": HUB + "/subnets/gatewaysubnet"}}}]})
    return dict(hub=hub, spoke=spoke, hub_gateway=gateway, spoke_gateways=[],
                hub_peering_name="to-one", spoke_peering_name="to-hub")


def test_exact_peering_pair_gateway_prerequisites_and_no_hub_ownership():
    inputs = peer_inputs()
    result = net.plan_peerings(**inputs)
    assert [x["id"] for x in result["operations"]] == [
        HUB + "/virtualnetworkpeerings/to-one", VNET + "/virtualnetworkpeerings/to-hub"]
    assert result["operations"][0]["data"]["properties"]["allowGatewayTransit"] is True
    assert result["operations"][1]["data"]["properties"]["useRemoteGateways"] is True
    assert result["deletion_resource_ids"] == []
    inputs["hub_gateway"]["properties"]["provisioningState"] = "Updating"
    with pytest.raises(net.PreservationError, match="ready-hub-vpn"):
        net.plan_peerings(**inputs)


def test_owned_peering_update_is_exact_and_retains_reviewed_extra_fields():
    inputs = peer_inputs()
    result = net.plan_peerings(**inputs)
    for operation, parent in zip(result["operations"], (inputs["hub"], inputs["spoke"])):
        child = resource(operation["id"], operation["data"]["properties"])
        parent["properties"]["virtualNetworkPeerings"].append(child)
    owned = [x["id"] for x in result["operations"]]
    assert net.plan_peerings(**inputs, reused_resource_ids=owned)["operations"] == []
    peer = inputs["hub"]["properties"]["virtualNetworkPeerings"][0]
    peer["properties"].update(allowGatewayTransit=False, doNotVerifyRemoteGateways=False)
    with pytest.raises(net.PreservationError, match="unowned-peering-update"):
        net.plan_peerings(**inputs, reused_resource_ids=owned)
    changed = net.plan_peerings(**inputs, owned_resource_ids=owned)
    assert len(changed["operations"]) == 1
    assert changed["operations"][0]["if_match"] == peer["etag"]
    assert changed["operations"][0]["data"]["properties"]["doNotVerifyRemoteGateways"] is False


def test_second_remote_gateway_and_unrelated_peering_target_are_rejected():
    inputs = peer_inputs()
    inputs["spoke"]["properties"]["virtualNetworkPeerings"][0]["properties"]["useRemoteGateways"] = True
    with pytest.raises(net.PreservationError, match="another-remote-gateway"):
        net.plan_peerings(**inputs)
    inputs = peer_inputs()
    child = resource(HUB + "/virtualnetworkpeerings/to-one", {"remoteVirtualNetwork": {"id": HUB}})
    inputs["hub"]["properties"]["virtualNetworkPeerings"].append(child)
    with pytest.raises(net.PreservationError, match="peering-target-conflict"):
        net.plan_peerings(**inputs)
