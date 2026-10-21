"""Offline contracts for the isolated APIM provisioning stages; never deploy to Azure."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[4]
APIM = ROOT / "environment_setup/aifactory/bicep/esml-common/ai-gateway/apim"
ENTRYPOINTS = ("network-main", "service-main", "private-endpoint-main", "main")
SUBNET_PARAMETERS = {
    "integrationSubnetId", "integrationSubnetPrefix", "networkSecurityGroupId", "routeTableId",
}
SERVICE_PARAMETERS = {
    "apimServiceName", "location", "publisherName", "publisherEmail", "skuCapacity",
    "integrationSubnetId", "publicNetworkAccess", "ownershipId", "tags",
}
ENDPOINT_PARAMETERS = {
    "apimServiceName", "location", "privateEndpointSubnetId", "privateEndpointName",
    "privateDnsMode", "privateDnsZoneId", "tags", "ownershipId",
}
SERVICE_SCOPE_PARAMETERS = {"apimResourceGroupName", "apimSubscriptionId"}
OWNER_TAG = "aifactory-gateway-owner"


def test_existing_pool_policy_is_rawxml_and_retains_retry_expression():
    # main deploys policy.xml as rawxml after token replacement, so policy expressions stay unescaped.
    assert "format: 'rawxml'" in (APIM / "apim-configuration.bicep").read_text(encoding="utf-8")
    policy = (APIM / "policy.xml").read_text(encoding="utf-8")
    assert '<retry condition="@(context.Response != null && context.Response.StatusCode == 429)"' in policy
    sample = re.sub(r"__[A-Z_]+__", "", policy).replace("&&", "&amp;&amp;")
    assert ET.fromstring(sample).find("backend/retry") is not None


@pytest.mark.parametrize(("name", "scope", "parameters"), [
    ("network-main", "subscription", SUBNET_PARAMETERS | {"location"}),
    ("network-subnet", "resourceGroup", SUBNET_PARAMETERS),
    ("service-main", "subscription", SERVICE_PARAMETERS | SERVICE_SCOPE_PARAMETERS),
    ("apim-service", "resourceGroup", SERVICE_PARAMETERS),
    ("private-endpoint-main", "subscription", ENDPOINT_PARAMETERS | SERVICE_SCOPE_PARAMETERS),
    ("private-endpoint", "resourceGroup", ENDPOINT_PARAMETERS),
])
def test_source_parameter_and_scope_contract(name, scope, parameters):
    source = (APIM / f"{name}.bicep").read_text(encoding="utf-8")
    assert f"targetScope = '{scope}'" in source
    assert set(re.findall(r"^param (\w+) ", source, re.MULTILINE)) == parameters
    assert not re.search(r"\b(?:https?|br|ts):", source)


@pytest.mark.parametrize("name", ["service-main", "apim-service"])
def test_source_service_default_is_private_even_without_compiler(name):
    source = (APIM / f"{name}.bicep").read_text(encoding="utf-8")
    assert "param publicNetworkAccess string = 'Disabled'" in source
    assert "param ownershipId string\n" in source
    assert "param integrationSubnetId string\n" in source
    assert "param skuCapacity int = 1" in source
    assert "@minValue(1)\n@maxValue(10)\nparam skuCapacity int = 1" in source


@pytest.mark.parametrize("name", ["private-endpoint-main", "private-endpoint"])
def test_source_policy_dns_is_default_even_without_compiler(name):
    source = (APIM / f"{name}.bicep").read_text(encoding="utf-8")
    assert "param privateDnsMode string = 'policy'" in source
    assert "param privateDnsZoneId string = ''" in source


@pytest.fixture(scope="module")
def compiled():
    compiler = shutil.which("bicep")
    if not compiler:
        cache = Path(os.environ.get("AZURE_CONFIG_DIR", str(Path.home() / ".azure")))
        binary = cache / "bin" / ("bicep.exe" if os.name == "nt" else "bicep")
        compiler = str(binary) if binary.is_file() else None
    if not compiler:
        pytest.skip("Installed Bicep required; offline tests never install or download it")
    result = {}
    for name in ENTRYPOINTS:
        process = subprocess.run(
            [compiler, "build", str(APIM / f"{name}.bicep"), "--stdout", "--no-restore"],
            capture_output=True, text=True, timeout=120, cwd=ROOT,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        result[name] = json.loads(process.stdout)
    return result


def nested(compiled, name):
    resources = compiled[name]["resources"]
    assert len(resources) == 1
    deployment = resources[0]
    assert deployment["type"] == "Microsoft.Resources/deployments"
    assert deployment["properties"]["mode"] == "Incremental"
    return deployment["properties"]["template"]


def evaluate(value, parameters):
    """Interpret only the pure ARM functions needed by subnet and DNS assertions."""
    if isinstance(value, dict):
        return {key: evaluate(item, parameters) for key, item in value.items()}
    if isinstance(value, list):
        return [evaluate(item, parameters) for item in value]
    if not isinstance(value, str) or not value.startswith("["):
        return value
    functions = {
        "parameters": lambda name: parameters[name],
        "union": lambda *objects: {key: item for obj in objects for key, item in obj.items()},
        "createObject": lambda *pairs: dict(zip(pairs[::2], pairs[1::2])),
        "createArray": lambda *items: list(items),
        "empty": lambda item: not item,
        "arm_if": lambda condition, yes, no: yes if condition else no,
        "equals": lambda left, right: left == right,
        "split": lambda text, separator: text.split(separator),
        "format": lambda text, *args: text.format(*args),
    }

    def walk(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Subscript):
            return walk(node.value)[walk(node.slice)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return functions[node.func.id](*[walk(argument) for argument in node.args])
        raise AssertionError(f"Unreviewed ARM expression: {value}")

    expression = re.sub(r"\bif\(", "arm_if(", value[1:-1])
    return walk(ast.parse(expression, mode="eval").body)


@pytest.mark.parametrize(("name", "child_parameters"), [
    ("network-main", SUBNET_PARAMETERS),
    ("service-main", SERVICE_PARAMETERS),
    ("private-endpoint-main", ENDPOINT_PARAMETERS),
])
def test_stage_wrappers_forward_only_their_own_parameters(compiled, name, child_parameters):
    template = compiled[name]
    assert "/subscriptionDeploymentTemplate.json#" in template["$schema"]
    child = nested(compiled, name)
    assert "/deploymentTemplate.json#" in child["$schema"]
    passed = template["resources"][0]["properties"]["parameters"]
    assert set(passed) == child_parameters
    assert passed == {key: {"value": f"[parameters('{key}')]"} for key in child_parameters}


def test_network_scope_is_only_the_existing_vnet_resource_group_in_this_subscription(compiled):
    deployment = compiled["network-main"]["resources"][0]
    assert deployment["subscriptionId"] == "[subscription().subscriptionId]"
    assert deployment["resourceGroup"] == "[split(parameters('integrationSubnetId'), '/')[4]]"
    for name in ("integrationSubnetId", "integrationSubnetPrefix", "networkSecurityGroupId", "location"):
        assert "defaultValue" not in compiled["network-main"]["parameters"][name]
    assert compiled["network-main"]["parameters"]["routeTableId"]["defaultValue"] == ""


@pytest.mark.parametrize("name", ["service-main", "private-endpoint-main"])
def test_apim_stages_use_explicit_service_subscription_and_group(compiled, name):
    deployment = compiled[name]["resources"][0]
    assert deployment["subscriptionId"] == "[parameters('apimSubscriptionId')]"
    assert deployment["resourceGroup"] == "[parameters('apimResourceGroupName')]"
    assert compiled[name]["parameters"]["apimSubscriptionId"]["defaultValue"] == "[subscription().subscriptionId]"


@pytest.mark.parametrize(("name", "allowed_types"), [
    ("network-main", {"Microsoft.Network/virtualNetworks/subnets"}),
    ("service-main", {"Microsoft.ApiManagement/service"}),
    ("private-endpoint-main", {
        "Microsoft.Network/privateEndpoints", "Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
    }),
])
def test_mutation_footprint_never_replaces_shared_network_dns_or_rbac(compiled, name, allowed_types):
    resources = nested(compiled, name)["resources"]
    assert {resource["type"] for resource in resources} == allowed_types
    assert len(resources) == len(allowed_types)


@pytest.mark.parametrize("route_table", ["", "/subscriptions/sub/resourceGroups/net/providers/Microsoft.Network/routeTables/approved"])
def test_network_creates_only_explicit_child_prefix_delegation_and_existing_associations(compiled, route_table):
    params = {
        "integrationSubnetId": "/subscriptions/sub/resourceGroups/net/providers/Microsoft.Network/virtualNetworks/shared/subnets/apim-new",
        "integrationSubnetPrefix": "10.20.30.0/27",
        "networkSecurityGroupId": "/subscriptions/sub/resourceGroups/net/providers/Microsoft.Network/networkSecurityGroups/approved",
        "routeTableId": route_table,
    }
    resource = nested(compiled, "network-main")["resources"][0]
    assert evaluate(resource["name"], params) == "shared/apim-new"
    expected = {
        "addressPrefix": params["integrationSubnetPrefix"],
        "networkSecurityGroup": {"id": params["networkSecurityGroupId"]},
        "delegations": [{
            "name": "apim-v2-integration",
            "properties": {"serviceName": "Microsoft.Web/serverFarms"},
        }],
    }
    if route_table:
        expected["routeTable"] = {"id": route_table}
    assert evaluate(resource["properties"], params) == expected
    assert set(nested(compiled, "network-main")["outputs"]) == {"subnetId"}
    assert set(compiled["network-main"]["outputs"]) == {"subnetId"}


def test_service_secure_default_fixed_sku_system_identity_and_exact_network(compiled):
    child = nested(compiled, "service-main")
    for template in (compiled["service-main"], child):
        parameters = template["parameters"]
        assert parameters["publicNetworkAccess"]["defaultValue"] == "Disabled"
        assert set(parameters["publicNetworkAccess"]["allowedValues"]) == {"Enabled", "Disabled"}
        assert parameters["skuCapacity"]["defaultValue"] == 1
        assert parameters["skuCapacity"]["minValue"] == 1
        assert "defaultValue" not in parameters["ownershipId"]
        assert parameters["ownershipId"]["minLength"] == 1
    service = child["resources"][0]
    assert service["sku"] == {"name": "StandardV2", "capacity": "[parameters('skuCapacity')]"}
    assert service["identity"] == {"type": "SystemAssigned"}
    assert service["properties"] == {
        "publisherName": "[parameters('publisherName')]",
        "publisherEmail": "[parameters('publisherEmail')]",
        "developerPortalStatus": "Disabled",
        "publicNetworkAccess": "[parameters('publicNetworkAccess')]",
        "virtualNetworkType": "External",
        "virtualNetworkConfiguration": {"subnetResourceId": "[parameters('integrationSubnetId')]"},
    }


@pytest.mark.parametrize("name", ["service-main", "private-endpoint-main"])
def test_owner_tag_overrides_caller_tags_including_case_variants(compiled, name):
    child = nested(compiled, name)
    assert child["variables"]["callerTags"] == (
        "[toObject(filter(items(parameters('tags')), lambda('tag', "
        f"not(equals(toLower(lambdaVariables('tag').key), '{OWNER_TAG}')))), "
        "lambda('tag', lambdaVariables('tag').key), lambda('tag', lambdaVariables('tag').value))]"
    )
    assert child["resources"][0]["tags"] == (
        f"[union(variables('callerTags'), createObject('{OWNER_TAG}', parameters('ownershipId')))]"
    )


def test_service_outputs_are_real_resource_values_not_caller_supplied_identity_or_url(compiled):
    child = nested(compiled, "service-main")
    expected = {"apimResourceId", "managedIdentityPrincipalId", "gatewayUrl"}
    assert set(child["outputs"]) == set(compiled["service-main"]["outputs"]) == expected
    assert child["outputs"]["apimResourceId"]["value"] == "[resourceId('Microsoft.ApiManagement/service', parameters('apimServiceName'))]"
    assert child["outputs"]["managedIdentityPrincipalId"]["value"].endswith("'full').identity.principalId]")
    assert child["outputs"]["gatewayUrl"]["value"].endswith("'2024-05-01').gatewayUrl]")
    for name in ("managedIdentityPrincipalId", "gatewayUrl"):
        assert "reference(resourceId('Microsoft.ApiManagement/service'" in child["outputs"][name]["value"]


def test_private_endpoint_uses_existing_service_gateway_and_subnet_without_approving_connection(compiled):
    child = nested(compiled, "private-endpoint-main")
    endpoint = child["resources"][0]
    assert endpoint["properties"] == {
        "subnet": {"id": "[parameters('privateEndpointSubnetId')]"},
        "privateLinkServiceConnections": [{
            "name": "[parameters('privateEndpointName')]",
            "properties": {
                "privateLinkServiceId": "[resourceId('Microsoft.ApiManagement/service', parameters('apimServiceName'))]",
                "groupIds": ["Gateway"],
            },
        }],
    }
    assert set(child["outputs"]) == set(compiled["private-endpoint-main"]["outputs"]) == {
        "privateEndpointResourceId", "apimResourceId",
    }


@pytest.mark.parametrize(("mode", "creates_group"), [("policy", False), ("existingZone", True)])
def test_dns_policy_ownership_or_exact_existing_zone_only(compiled, mode, creates_group):
    child = nested(compiled, "private-endpoint-main")
    for template in (compiled["private-endpoint-main"], child):
        assert template["parameters"]["privateDnsMode"]["defaultValue"] == "policy"
        assert set(template["parameters"]["privateDnsMode"]["allowedValues"]) == {"policy", "existingZone"}
        assert template["parameters"]["privateDnsZoneId"]["defaultValue"] == ""
    zone_group = child["resources"][1]
    zone_id = "/subscriptions/dns/resourceGroups/hub/providers/Microsoft.Network/privateDnsZones/privatelink.azure-api.net"
    params = {"privateDnsMode": mode, "privateDnsZoneId": zone_id}
    assert evaluate(zone_group["condition"], params) is creates_group
    assert evaluate(zone_group["properties"], params) == {
        "privateDnsZoneConfigs": [{
            "name": "privatelink.azure-api.net", "properties": {"privateDnsZoneId": zone_id},
        }],
    }
    assert zone_group["dependsOn"] == ["[resourceId('Microsoft.Network/privateEndpoints', parameters('privateEndpointName'))]"]


def test_configuration_entrypoint_remains_existing_only_with_read_free_actual_id_output(compiled):
    template = compiled["main"]
    assert template["parameters"]["assignOpenAIUserRole"]["defaultValue"] is False
    assert template["parameters"]["mcpServers"]["defaultValue"] == []
    assert template["outputs"]["apimResourceId"]["value"] == (
        "[resourceId(parameters('apimSubscriptionId'), parameters('apimResourceGroupName'), "
        "'Microsoft.ApiManagement/service', parameters('apimServiceName'))]"
    )
    assert set(template["outputs"]) == {
        "apimApiId", "apimApiPath", "backendPoolResourceId", "policyFeatures", "mcpGatewayUrls",
        "requiredRoleDefinitionId", "apimResourceId",
    }
    configuration, mcp_servers, assignments = template["resources"]
    assert "apim-aoai-pool-" in configuration["name"]
    assert mcp_servers["copy"]["count"] == "[length(parameters('mcpServers'))]"
    assert "parameters('assignOpenAIUserRole')" in assignments["condition"]
    children = configuration["properties"]["template"]["resources"]
    children = children.values() if isinstance(children, dict) else children
    # The policy package adds only switch-gated resources; with main's defaults the footprint is unchanged.
    assert {child["type"] for child in children if not child.get("existing") and "condition" not in child} == {
        "Microsoft.ApiManagement/service/backends",
        "Microsoft.ApiManagement/service/apis",
        "Microsoft.ApiManagement/service/apis/operations",
        "Microsoft.ApiManagement/service/apis/policies",
    }
    assert {child["condition"] for child in children if "condition" in child} == {
        "[parameters('enableSemanticCache')]", "[parameters('emitTokenMetrics')]",
    }
