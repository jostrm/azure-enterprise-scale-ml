"""Offline regressions for the dedicated Logic Apps Standard outbound subnet."""

import copy
import ast
from functools import lru_cache
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

import pytest
import yaml

from .test_subnet_scaling_capacity import SUFFIXES, inventory, invoke_allocator, subnet
from .test_capacity_resource_deployment import runner


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"


def test_logic_app_never_integrates_with_or_redelegates_aks():
    source = (BICEP / "esml-genai-1/11-integration.bicep").read_text(encoding="utf-8")
    integration = next(line for line in source.splitlines() if "virtualNetworkSubnetResourceId:" in line)
    assert "logicappSubnetId" in integration
    assert "aksSubnetName" not in integration
    assert "module subnetDelegationServerFarm" not in source
    assert "genaiSubnetName)" in source  # Inbound PE stays separate.


@pytest.mark.parametrize("project", ["001", "012"])
@pytest.mark.parametrize("azure", ["cli", "az"])
def test_existing_project_adds_only_dedicated_26_and_reuses_it(project, azure):
    vnet = inventory(("100.120.80.0/20",), [
        subnet(f"snt-prj{project}-genai", "100.120.90.0/25"),
        subnet(f"snt-prj{project}-aks", "100.120.91.0/26"),
        subnet(f"snt-prj{project}-aca", "100.120.92.0/23"),
        {**subnet(f"snt-prj{project}-webapp", "100.120.94.64/27"),
         "delegations": [{"serviceName": "Microsoft.Web/serverFarms"}]},
    ])
    before = copy.deepcopy(vnet)
    run, data = invoke_allocator(vnet, projectNumber=project, projectTypeADO="genai-1",
                                 enableLogicApps="true", azure=azure)
    assert run.returncode == 0, run.stdout + run.stderr
    values = {key: value["value"] for key, value in data["parameters"].items()}
    allocated = ipaddress.ip_network(values["logicappSubnetCidr"])
    assert allocated.prefixlen == 26
    assert all(not allocated.overlaps(ipaddress.ip_network(s["addressPrefix"])) for s in vnet["subnets"])
    assert vnet == before
    for purpose in ("genai", "aks", "aca", "webapp"):
        assert values[f"{purpose}SubnetCidr"] == next(s["addressPrefix"] for s in vnet["subnets"]
                                                    if s["name"] == f"snt-prj{project}-{purpose}")
    vnet["subnets"].append({**subnet(f"snt-prj{project}-logicapp", str(allocated)),
                           "delegations": [{"serviceName": "Microsoft.Web/serverFarms"}]})
    run, repeated = invoke_allocator(vnet, projectNumber=project, projectTypeADO="genai-1",
                                     enableLogicApps="true", azure=azure)
    assert run.returncode == 0, run.stdout + run.stderr
    assert repeated["parameters"]["logicappSubnetCidr"]["value"] == str(allocated)


@pytest.mark.parametrize("flags", [
    {}, {"enableLogicApps": "false"}, {"enableLogicApps": "true", "logicAppType": "Consumption"},
    {"enableLogicApps": "true", "byoASEv3": "true"},
    {"enableLogicApps": "true", "enablePublicAccessWithPerimeter": "true"},
])
def test_no_logic_app_allocation_when_not_required(flags):
    run, data = invoke_allocator(inventory(), **flags)
    assert run.returncode == 0, run.stdout + run.stderr
    assert not data["parameters"].get("logicappSubnetCidr", {}).get("value")


@pytest.mark.parametrize("project", ["001", "012"])
def test_ordinary_all_profile_update_adds_only_missing_logic_app(project):
    vnet = inventory()
    run, initial = invoke_allocator(vnet, projectNumber=project)
    assert run.returncode == 0, run.stderr
    for key, purpose in SUFFIXES.items():
        vnet["subnets"].append(subnet(f"snt-prj{project}-{purpose}", initial["parameters"][key]["value"]))
    run, updated = invoke_allocator(vnet, projectNumber=project,
                                    json_parameters={4: {"enableLogicApps": "true"}})
    assert run.returncode == 0, run.stderr
    assert set(updated["parameters"]) - set(initial["parameters"]) == {"logicappSubnetCidr"}
    for key in SUFFIXES:
        assert updated["parameters"][key] == initial["parameters"][key]


@pytest.mark.parametrize("mutation,error", [
    ({"delegations": []}, "delegated only"),
    ({"delegations": [{"serviceName": "Microsoft.App/environments"}]}, "delegated only"),
    ({"addressPrefix": "100.120.94.128/27"}, "/26 or larger"),
    ({"privateEndpoints": [{"id": "pe"}]}, "private endpoints"),
    ({"ipConfigurations": [{"id": "nic"}]}, "NIC IP"),
    ({"provisioningState": "Failed"}, "must be Succeeded"),
    ({"provisioningState": "Updating"}, "must be Succeeded"),
    ({"provisioningState": None}, "must be Succeeded"),
])
def test_allocator_never_resizes_or_redelegates_existing_logic_subnet(mutation, error):
    existing = {**subnet("snt-prj012-logicapp", "100.120.94.128/26"),
                "delegations": [{"serviceName": "Microsoft.Web/serverFarms"}], **mutation}
    run, data = invoke_allocator(inventory(("100.120.80.0/20",), [existing]),
                                 projectNumber="012", enableLogicApps="true")
    assert run.returncode != 0 and data is None
    assert error in run.stderr


@pytest.mark.parametrize("azure", ["cli", "az"])
def test_allocator_rejects_wrong_scope_even_successful_inventory(azure):
    vnet = {**inventory(), "id": "/subscriptions/other/resourceGroups/wrong/providers/Microsoft.Network/virtualNetworks/other"}
    run, data = invoke_allocator(vnet, enableLogicApps="true", azure=azure)
    assert run.returncode != 0 and data is None
    assert "inventory identity" in run.stderr


@pytest.mark.parametrize("azure", ["cli", "az"])
@pytest.mark.parametrize("invalid", [None, {}, "not-an-array", subnet("standalone", "10.113.0.0/26")])
def test_allocator_requires_actual_inventory_collection(azure, invalid):
    run, data = invoke_allocator({**inventory(), "subnets": invalid},
                                 enableLogicApps="true", azure=azure)
    assert run.returncode != 0 and data is None
    assert "subnet inventory" in run.stderr


@pytest.mark.parametrize("azure", ["cli", "az"])
def test_allocator_does_not_trust_a_foreign_subnet_in_correct_vnet_response(azure):
    vnet = inventory(subnets=[{**subnet("ordinary", "10.113.0.0/26"),
                               "id": "/subscriptions/foreign/resourceGroups/foreign/providers/Microsoft.Network/virtualNetworks/foreign/subnets/ordinary"}])
    run, data = invoke_allocator(vnet, enableLogicApps="true", azure=azure)
    assert run.returncode != 0 and data is None
    assert "Subnet inventory identity" in run.stderr


@pytest.mark.parametrize("azure", ["cli", "az"])
@pytest.mark.parametrize("identity", ["missing", "wrong-child"])
def test_allocator_checks_ordinary_child_identity_with_valid_selected_logic_subnet(azure, identity):
    vnet_id = ("/subscriptions/test-subscription/resourceGroups/acme-common-swc-dev-007"
               "/providers/Microsoft.Network/virtualNetworks/vnet-swc-dev-008")
    ordinary = {**subnet("ordinary", "10.113.0.0/26"),
                "id": None if identity == "missing" else f"{vnet_id}/subnets/another-child"}
    selected = {**subnet("snt-prj001-logicapp", "10.113.0.64/26"),
                "id": f"{vnet_id}/subnets/snt-prj001-logicapp",
                "delegations": [{"serviceName": "Microsoft.Web/serverFarms"}]}
    vnet = {**inventory(subnets=[ordinary, selected]), "id": vnet_id}

    run, data = invoke_allocator(vnet, enableLogicApps="true", azure=azure)

    assert run.returncode != 0 and data is None
    assert "Subnet inventory identity mismatch for 'ordinary'" in run.stderr


@pytest.mark.parametrize("azure", ["cli", "az"])
def test_allocator_accepts_case_insensitive_exact_ids_for_all_children(azure):
    vnet_id = ("/subscriptions/test-subscription/resourceGroups/acme-common-swc-dev-007"
               "/providers/Microsoft.Network/virtualNetworks/vnet-swc-dev-008")
    ordinary = {**subnet("ordinary", "10.113.0.0/26"), "id": f"{vnet_id}/subnets/ordinary".upper()}
    selected = {**subnet("SNT-PRJ001-LOGICAPP", "10.113.0.64/26"),
                "id": f"{vnet_id}/subnets/snt-prj001-logicapp".upper(),
                "delegations": [{"serviceName": "Microsoft.Web/serverFarms"}]}
    vnet = {**inventory(subnets=[ordinary, selected]), "id": vnet_id.upper()}

    run, data = invoke_allocator(vnet, enableLogicApps="true", azure=azure)

    assert run.returncode == 0, run.stdout + run.stderr
    assert data["parameters"]["logicappSubnetCidr"]["value"] == "10.113.0.64/26"


def test_allocator_accepts_native_az_list_without_coercing_invalid_objects():
    run, data = invoke_allocator(inventory(subnets=[subnet("ordinary", "10.113.0.0/26")]),
                                 enableLogicApps="true", azure="az-list")
    assert run.returncode == 0, run.stdout + run.stderr
    assert data["parameters"]["logicappSubnetCidr"]["value"].endswith("/26")


VNET_ID = "/subscriptions/test-subscription/resourceGroups/custom-dev/providers/Microsoft.Network/virtualNetworks/vnet-dev"
LOGIC_ID = VNET_ID + "/subnets/snt-prj012-logicapp"


def invoke_dynamic(*, azure="cli", config=None, parameters=None, output=LOGIC_ID, mutation=None,
                   deployment_state="Succeeded"):
    workspace = ROOT / ".test-state" / ("logicapp-" + uuid4().hex)
    workspace.mkdir(parents=True)
    base = {
        "vnetNameBase": "vnet", "vnetResourceGroupBase": "common", "commonResourceSuffix": "-001",
        "vnetNameFull_param": "vnet-<network_env>", "vnetResourceGroup_param": "custom-<network_env>",
        "enableLogicApps": "true",
    } | (config or {})
    args = {
        "filePath": str(workspace) + os.sep, "env": "dev", "subscriptionId": "test-subscription",
        "aifactorySuffixRGADO": "-001", "locationSuffixADO": "swc", "projectNumber": "012",
        "projectTypeADO": "all", "BYO_subnets": "false", "network_env": "dev",
        "enableAIFoundry": "false", "enableAksForAzureML": "false",
    } | (parameters or {})
    for number in range(1, 6):
        path = workspace / f"config-{number}.json"
        path.write_text(json.dumps({"parameters": {
            key: {"value": value} for key, value in (base if number == 5 else {"fixture": "offline"}).items()
        }}), encoding="utf-8")
        args[f"bicepPar{number}"] = str(path)
    outputs = {key + "SubnetId": {"value": VNET_ID + f"/subnets/snt-prj012-{purpose}"}
               for key, purpose in (("genai", "genai"), ("aks", "aks"), ("aks2", "aks-002"),
                                    ("aca", "aca"), ("aca2", "aca-002"), ("webapp", "webapp"))}
    outputs.update({"logicappSubnetId": {"value": output},
                    "dbxPubSubnetName": {"value": ""}, "dbxPrivSubnetName": {"value": ""}})
    subnet_data = {"id": LOGIC_ID, "properties": {
        "provisioningState": "Succeeded",
        "addressPrefix": "100.120.94.128/26",
        "delegations": [{"properties": {"serviceName": "Microsoft.Web/serverFarms"}}],
    }}
    if mutation:
        subnet_data["properties"].update(mutation)
    code = r"""
$ErrorActionPreference = 'Stop'
$parameters = $env:LOGIC_PARAMETERS | ConvertFrom-Json -AsHashtable
Microsoft.PowerShell.Core\Import-Module './modules/pipelineFunctions.psm1'
& (Get-Module pipelineFunctions) { function script:Import-Dependencies {} }
function global:az {
    $global:LASTEXITCODE = 0
    if (($args[0..2] -join ' ') -eq 'deployment group show') {
        if ($args[[array]::IndexOf($args, '--resource-group') + 1] -ne 'custom-dev' -or
            $args[[array]::IndexOf($args, '--subscription') + 1] -ne 'test-subscription') { throw 'Wrong deployment scope' }
        $query = $args[[array]::IndexOf($args, '--query') + 1]
        if ($query -like 'properties.{*') {
            return (@{provisioningState = ($env:LOGIC_DEPLOYMENT_STATE | ConvertFrom-Json)
                value = ($env:LOGIC_OUTPUTS | ConvertFrom-Json).logicappSubnetId.value} | ConvertTo-Json)
        }
        $key = ($query -split '\.')[2]
        return ($env:LOGIC_OUTPUTS | ConvertFrom-Json).$key.value
    }
    if ($args[0] -eq 'rest') {
        if ($args[[array]::IndexOf($args, '--method') + 1] -ne 'get') { throw 'Writes forbidden' }
        if ($env:LOGIC_AZURE -eq 'denied') { $global:LASTEXITCODE = 1; return 'Forbidden' }
        $response = $env:LOGIC_SUBNET | ConvertFrom-Json
        $response.id = ($args[[array]::IndexOf($args, '--url') + 1] -split '\?')[0]
        if ($env:LOGIC_AZURE -eq 'wrong-id') { $response.id += '-wrong' }
        return ($response | ConvertTo-Json -Depth 10)
    }
    throw "Unexpected Azure command: $args"
}
function global:Get-AzResourceGroupDeployment {
    param($ResourceGroupName, $Name)
    if ($ResourceGroupName -ne 'custom-dev') { throw 'Wrong deployment scope' }
    $outputs = @{}
    foreach ($property in ($env:LOGIC_OUTPUTS | ConvertFrom-Json).PSObject.Properties) {
        $outputs[$property.Name] = $property.Value
    }
    [pscustomobject]@{Outputs = $outputs; ProvisioningState = ($env:LOGIC_DEPLOYMENT_STATE | ConvertFrom-Json)}
}
function global:Invoke-AzRestMethod {
    param($Method, $Path)
    if ($Method -ne 'GET') { throw 'Writes forbidden' }
    $response = $env:LOGIC_SUBNET | ConvertFrom-Json
    $response.id = ($Path -split '\?')[0]
    [pscustomobject]@{StatusCode = 200; Content = ($response | ConvertTo-Json -Depth 10)}
}
try { & './genDynamicNetworkParamFile.ps1' @parameters }
catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
"""
    try:
        run = subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", code],
            cwd=BICEP / "scripts", capture_output=True, text=True, timeout=30,
            env={**os.environ, "GITHUB_ACTIONS": "false",
                 "AIFACTORY_USE_AZURE_CLI": "false" if azure == "az" else "true",
                 "LOGIC_PARAMETERS": json.dumps(args), "LOGIC_OUTPUTS": json.dumps(outputs),
                 "LOGIC_SUBNET": json.dumps(subnet_data), "LOGIC_AZURE": azure,
                 "LOGIC_DEPLOYMENT_STATE": json.dumps(deployment_state)},
        )
        path = workspace / "dynamicNetworkParams.json"
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else None
        return run, data
    finally:
        shutil.rmtree(workspace)


@pytest.mark.parametrize("azure", ["cli", "az"])
def test_dynamic_managed_reads_output_and_exact_subnet(azure):
    run, data = invoke_dynamic(azure=azure)
    assert run.returncode == 0, run.stdout + run.stderr
    assert data["parameters"]["logicappSubnetId"]["value"] == LOGIC_ID
    assert data["parameters"]["genaiSubnetId"]["value"] == VNET_ID + "/subnets/snt-prj012-genai"


@pytest.mark.parametrize("azure", ["cli", "az"])
@pytest.mark.parametrize("state", [None, "Failed", "Running"])
def test_dynamic_requires_succeeded_network_deployment(azure, state):
    run, data = invoke_dynamic(azure=azure, deployment_state=state)
    assert run.returncode != 0 and data is None
    assert "must be Succeeded" in run.stderr


@pytest.mark.parametrize("azure", ["cli", "az"])
@pytest.mark.parametrize("state", [None, "Failed", "Updating"])
def test_dynamic_requires_succeeded_exact_subnet(azure, state):
    run, data = invoke_dynamic(azure=azure, mutation={"provisioningState": state})
    assert run.returncode != 0 and data is None
    assert "must be Succeeded" in run.stderr


@pytest.mark.parametrize("output", ["", "malformed", VNET_ID + "/subnets/snt-prj001-logicapp",
                                  VNET_ID + "/subnets/snt-prj012-aks",
                                  LOGIC_ID.replace("custom-dev", "wrong-rg")])
def test_managed_missing_or_foreign_output_fails_closed(output):
    run, data = invoke_dynamic(output=output)
    assert run.returncode != 0 and data is None


@pytest.mark.parametrize("azure", ["denied", "wrong-id"])
def test_exact_subnet_read_must_succeed_and_match(azure):
    run, data = invoke_dynamic(azure=azure)
    assert run.returncode != 0 and data is None


@pytest.mark.parametrize("name", ["snt-prj<xxx>-logicapp",
                                 LOGIC_ID.replace("dev", "<network_env>").replace("012", "<xxx>")])
@pytest.mark.parametrize("azure", ["cli", "az"])
def test_byo_requires_and_resolves_explicit_name_or_id(name, azure):
    run, data = invoke_dynamic(azure=azure, config={"subnetProjLogicapp": name},
                               parameters={"BYO_subnets": "true"})
    assert run.returncode == 0, run.stdout + run.stderr
    assert data["parameters"]["logicappSubnetId"]["value"] == LOGIC_ID


@pytest.mark.parametrize("name", ["", "<todo>", "$(subnetProjLogicapp)", "wrong/name",
                                 LOGIC_ID.replace("test-subscription", "other"),
                                 "snt-prj012-webapp"])
def test_byo_missing_malformed_or_unsafe_selection_fails(name):
    run, data = invoke_dynamic(config={"subnetProjLogicapp": name}, parameters={"BYO_subnets": "true"})
    assert run.returncode != 0 and data is None


@pytest.mark.parametrize("mutation", [
    {"delegations": []}, {"delegations": [{"serviceName": "Microsoft.App/environments"}]},
    {"addressPrefix": "100.120.94.64/27"}, {"privateEndpoints": [{"id": "pe"}]},
])
def test_dynamic_rejects_unsafe_delegation_or_capacity(mutation):
    run, data = invoke_dynamic(mutation=mutation)
    assert run.returncode != 0 and data is None


@pytest.mark.parametrize("flags", [
    {"enableLogicApps": "false"}, {"logicAppType": "Consumption"}, {"byoASEv3": "true"},
    {"enablePublicAccessWithPerimeter": "true"},
])
def test_dynamic_disabled_integration_does_not_require_byo_subnet(flags):
    run, data = invoke_dynamic(parameters={"BYO_subnets": "true", **flags})
    assert run.returncode == 0, run.stdout + run.stderr
    assert data["parameters"]["logicappSubnetId"]["value"] == ""


@lru_cache
def compile_entry(name):
    result = subprocess.run([shutil.which("bicep"), "build", str(BICEP / "esml-genai-1" / name),
                             "--stdout", "--no-restore"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_compiled_logic_app_uses_explicit_outbound_and_separate_inbound():
    template = compile_entry("11-integration.bicep")
    resources = template["resources"].values() if isinstance(template["resources"], dict) else template["resources"]
    site = next(item for item in resources if "11-LogicApps01-" in item["name"])
    params = site["properties"]["parameters"]
    assert "logicappSubnetId" in json.dumps(params["virtualNetworkSubnetResourceId"])
    assert "aks" not in json.dumps(params["virtualNetworkSubnetResourceId"]).lower()
    assert "genaiSubnetName" in json.dumps(params["privateEndpoints"])
    assert "logicAppsExists" in site["condition"] and "Standard" in site["condition"]
    assert "11-snetDeleg" not in json.dumps(template["resources"])


def test_all_dynamic_consumer_compiled_contracts_accept_new_optional_parameter():
    provider_paths = [
        BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml",
        BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml",
    ]
    consumers = set()
    for path in provider_paths:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps = document.get("steps") or next(iter(document["jobs"].values()))["steps"]
        for step in steps:
            code = step.get("run", step.get("inputs", {}).get("inlineScript", ""))
            for command in code.split("--template-file")[1:]:
                if re.search(r'--parameters\s+["\']?@["\']?[^\s]*dynamicNetworkParams\.json', command):
                    name = re.match(r'\s+["\']?[^\s]*esml-genai-1/([^\s"\']+\.bicep)', command)
                    if name:
                        consumers.add(name[1])
    assert "11-integration.bicep" in consumers and len(consumers) >= 10
    run, dynamic = invoke_dynamic()
    assert run.returncode == 0, run.stderr
    for consumer in sorted(consumers):
        template = compile_entry(consumer)
        assert set(dynamic["parameters"]) <= set(template["parameters"]), consumer
        assert template["parameters"]["logicappSubnetId"]["defaultValue"] == ""


def test_network_bicep_dedicated_subnet_is_last_writer_and_reuse_is_not_written():
    template = compile_entry("31-network.bicep")
    logic = next(item for item in template["resources"] if "logicappSnet-" in item["name"])
    params = logic["properties"]["parameters"]
    assert params["delegations"]["value"] == ["Microsoft.Web/serverFarms"]
    assert "logicappSubnetCidr" in params["addressPrefix"]["value"]
    assert "logicapp" in params["name"]["value"]
    assert "createLogicAppSubnet" in logic["condition"]
    gate = template["variables"]["createLogicAppSubnet"]
    assert "sntLogicappExists" in gate and "BYO_subnets" in gate
    dependencies = json.dumps(logic["dependsOn"])
    for prefix in ("aks-", "genai-", "acaSnet-", "aks2-", "acaSnet2-", "webappSnet-", "dbxpub-", "dbxpriv-"):
        assert prefix in dependencies
    assert "logicappSubnetId" in template["outputs"]


def arm_value(expression, parameters, template):
    if not isinstance(expression, str) or not expression.startswith("["):
        return expression
    source = re.sub(r"\b(and|or|not|if)\(", lambda match: match[1].upper() + "(", expression[1:-1])

    def visit(node):
        if isinstance(node, ast.Constant):
            return node.value
        assert isinstance(node, ast.Call) and not node.keywords
        if isinstance(node.func, ast.Attribute):
            member = next(group for group in template["functions"] if group["namespace"] == node.func.value.id)["members"][node.func.attr]
            args = {key["name"]: visit(value) for key, value in zip(member["parameters"], node.args)}
            return arm_value(member["output"]["value"], args, template)
        name = node.func.id
        if name == "IF":
            return visit(node.args[1] if visit(node.args[0]) else node.args[2])
        values = [visit(arg) for arg in node.args]
        if name == "fail":
            raise ValueError(values[0])
        functions = {
            "parameters": parameters.__getitem__,
            "variables": lambda key: arm_value(template["variables"][key], parameters, template),
            "AND": lambda *args: all(args), "OR": lambda *args: any(args), "NOT": lambda value: not value,
            "empty": lambda value: not value, "equals": lambda a, b: a == b,
            "createObject": lambda *args: dict(zip(args[::2], args[1::2])),
            "true": lambda: True, "false": lambda: False, "null": lambda: None,
        }
        return functions[name](*values)

    return visit(ast.parse(source, mode="eval").body)


@pytest.mark.parametrize("flags,expected", [
    ({}, LOGIC_ID), ({"byoASEv3": True}, ""), ({"enablePublicAccessWithPerimeter": True}, ""),
])
def test_actual_compiled_outbound_value_and_missing_id_fail_closed(flags, expected):
    template = compile_entry("11-integration.bicep")
    expression = template["resources"]["logicAppStandard"]["properties"]["parameters"]["virtualNetworkSubnetResourceId"]
    parameters = {"logicappSubnetId": LOGIC_ID, "byoASEv3": False,
                  "enablePublicAccessWithPerimeter": False, **flags}
    assert arm_value(expression, parameters, template) == {"value": expected}
    parameters["logicappSubnetId"] = ""
    if flags:
        assert arm_value(expression, parameters, template) == {"value": ""}
    else:
        with pytest.raises(ValueError, match="requires logicappSubnetId"):
            arm_value(expression, parameters, template)


@pytest.mark.parametrize("flags,integrated", [
    ({}, True), ({"byoASEv3": True}, False), ({"enablePublicAccessWithPerimeter": True}, False),
])
def test_compiled_logic_app_routes_all_outbound_traffic_through_vnet(flags, integrated):
    # RFC1918-only routing would bypass private endpoints in ranges such as 100.64.0.0/10.
    template = compile_entry("11-integration.bicep")
    params = template["resources"]["logicAppStandard"]["properties"]["parameters"]
    values = {"byoASEv3": False, "enablePublicAccessWithPerimeter": False, **flags}
    routing = arm_value(params["outboundVnetRouting"], values, template)["value"]
    web = next(config for config in params["configs"]["value"] if config["name"] == "web")["properties"]
    assert arm_value(web["vnetRouteAllEnabled"], values, template) is integrated
    if integrated:
        assert routing == {"allTraffic": True, "applicationTraffic": True, "contentShareTraffic": True}
    else:
        assert routing is None


@pytest.mark.parametrize("flags", [
    {"enableLogicApps": False}, {"logicAppType": "Consumption"}, {"byoASEv3": True},
    {"enablePublicAccessWithPerimeter": True}, {"sntLogicappExists": True}, {"BYO_subnets": True},
])
def test_compiled_network_does_not_write_when_disabled_or_reused(flags):
    template = compile_entry("31-network.bicep")
    parameters = {key: value["defaultValue"] for key, value in template["parameters"].items() if "defaultValue" in value}
    parameters.update({"enableLogicApps": True, "logicappSubnetCidr": "100.120.94.128/26"})
    assert arm_value(template["variables"]["createLogicAppSubnet"], parameters, template)
    parameters.update(flags)
    assert not arm_value(template["variables"]["createLogicAppSubnet"], parameters, template)


@pytest.mark.parametrize("provider", ["ado", "gha"])
@pytest.mark.parametrize("mode", ["existing", "existing-uppercase", "absent", "denied", "wrong-scope",
                                 "missing-list", "object-list", "string-list", "null-list",
                                 "foreign-subnet", "failed-subnet", "missing-subnet-state",
                                 "unnamed-subnet", "foreign-other-subnet", "duplicate-other-subnet",
                                 "valid-other-subnet"])
def test_actual_provider_discovery_block_is_fail_closed(provider, mode):
    base = BICEP / "copy_to_local_settings"
    path = (base / "github-actions/infra-project-phase.yml" if provider == "gha" else
            base / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-1-genai-networking.yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = doc["steps"] if provider == "ado" else next(iter(doc["jobs"].values()))["steps"]
    step = next(step for step in steps if step.get("displayName", step.get("name")) ==
                ("04b_check_subnet_exists_for_project" if provider == "ado" else "06_Check_Subnet_Existence"))
    body = step["inputs"]["inlineScript"] if provider == "ado" else step["run"]
    values = {
        "project_number_000": "012", "dev_test_prod_sub_id": "test-subscription",
        "vnetResourceGroup_resolved": "custom-dev", "vnetNameFull_resolved": "vnet-dev",
        "enableLogicApps": "true", "logicAppType": "Standard", "byoASEv3": "false",
        "enablePublicAccessWithPerimeter": "false", "System.DefaultWorkingDirectory": ROOT.parent.as_posix(),
    }
    if provider == "ado":
        body = re.sub(r"\$\(([\w.]+)\)", lambda m: values.get(m[1], "unused"), body)
    else:
        body = re.sub(r"\$\{\{ env\.(\w+) }}", lambda m: values.get(m[1], "unused"), body)
        body = body.replace("${{ github.workspace }}", ROOT.parent.as_posix())
    workspace = ROOT / ".test-state" / ("logicapp-discovery-" + uuid4().hex)
    workspace.mkdir(parents=True)
    vnet = {"id": VNET_ID, "subnets": []}
    if mode in ("existing", "existing-uppercase", "foreign-subnet", "failed-subnet", "missing-subnet-state"):
        vnet["subnets"].append({
            "id": LOGIC_ID, "name": "snt-prj012-logicapp", "addressPrefix": "100.120.94.128/26",
            "provisioningState": "Succeeded",
            "delegations": [{"serviceName": "Microsoft.Web/serverFarms"}],
        })
    if mode == "existing-uppercase":
        vnet["id"] = vnet["id"].upper()
        vnet["subnets"][0]["id"] = LOGIC_ID.upper()
        vnet["subnets"][0]["name"] = "SNT-PRJ012-LOGICAPP"
    if mode == "foreign-subnet":
        vnet["subnets"][0]["id"] = LOGIC_ID.replace("custom-dev", "foreign")
    if mode == "failed-subnet":
        vnet["subnets"][0]["provisioningState"] = "Failed"
    if mode == "missing-subnet-state":
        del vnet["subnets"][0]["provisioningState"]
    if mode == "wrong-scope":
        vnet["id"] += "-wrong"
    if mode == "missing-list":
        del vnet["subnets"]
    if mode in ("object-list", "string-list", "null-list"):
        vnet["subnets"] = {"object-list": {}, "string-list": "invalid", "null-list": None}[mode]
    if mode == "unnamed-subnet":
        vnet["subnets"] = [{}]
    if mode in ("foreign-other-subnet", "duplicate-other-subnet", "valid-other-subnet"):
        other = {"id": f"{VNET_ID}/subnets/other-project", "name": "other-project"}
        vnet["subnets"] = [other]
        if mode == "foreign-other-subnet":
            other["id"] = other["id"].replace("custom-dev", "foreign")
        if mode == "duplicate-other-subnet":
            vnet["subnets"].append({key: value.upper() for key, value in other.items()})
    wrapper = workspace / "discovery.ps1"
    wrapper.write_text(r"""
$ErrorActionPreference = 'Stop'
function global:az {
    if ($env:DISCOVERY_MODE -eq 'denied') { $global:LASTEXITCODE=1; return 'Forbidden' }
    $global:LASTEXITCODE=0
    if (($args[0..2] -join ' ') -eq 'network vnet show') { return $env:DISCOVERY_VNET }
    if ($args[0] -eq 'rest' -and $args[[array]::IndexOf($args,'--method')+1] -eq 'get') {
        return (($env:DISCOVERY_VNET | ConvertFrom-Json).subnets[0] | ConvertTo-Json -Depth 10)
    }
    throw "Forbidden unexpected Azure command: $args"
}
$index = [array]::IndexOf($args, '-File')
$script = $args[$index+1]
$parameters = @{}
for ($i=$index+2; $i -lt $args.Count; $i+=2) { $parameters[$args[$i].TrimStart('-')] = $args[$i+1] }
try { & $script @parameters } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
""", encoding="utf-8")
    bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
    preamble = (
        'az() { if [ "$1 $2" = "account set" ]; then return 0; fi; return 99; }\n'
        f'pwsh() {{ "{Path(shutil.which("pwsh")).as_posix()}" -NoProfile -File "{wrapper.as_posix()}" "$@"; }}\n'
    )
    script = workspace / "provider.sh"
    script.write_text(preamble + body, encoding="utf-8", newline="\n")
    try:
        run = subprocess.run([str(bash) if bash.exists() else "bash", str(script)],
                             cwd=ROOT, text=True, capture_output=True, timeout=30,
                             env={**os.environ, "DISCOVERY_VNET": json.dumps(vnet), "DISCOVERY_MODE": mode,
                                  "GITHUB_ACTIONS": "true" if provider == "gha" else "false",
                                  "GITHUB_ENV": str(workspace / "github.env")})
        if mode in ("existing", "existing-uppercase", "absent", "valid-other-subnet"):
            assert run.returncode == 0, run.stdout + run.stderr
            state = (workspace / "github.env").read_text(encoding="utf-8-sig") if provider == "gha" else run.stdout
            expected = "true" if mode in ("existing", "existing-uppercase") else "false"
            assert (f"sntLogicappExists={expected}" if provider == "gha" else
                    f"variable=sntLogicappExists]{expected}") in state
        else:
            assert run.returncode != 0, run.stdout
            assert "variable=sntLogicappExists]" not in run.stdout
            assert not (workspace / "github.env").exists()
    finally:
        shutil.rmtree(workspace)


@pytest.mark.parametrize("provider", ["ado", "gha"])
@pytest.mark.parametrize("hosting", ["Standard", "Consumption"])
@pytest.mark.parametrize("mode", ["existing", "absent", "ambiguous", "denied"])
def test_actual_provider_logic_app_existence_matches_deployed_name(provider, hosting, mode):
    # A false negative redeploys task 68 and silently moves an existing app to the new subnet.
    base = BICEP / "copy_to_local_settings"
    if provider == "ado":
        steps = yaml.safe_load((base / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/"
                                "job-2-genai-services.yaml").read_text(encoding="utf-8"))["steps"]
        body = next(s for s in steps if s.get("displayName") == "05b_Check if resource exists")["inputs"]["inlineScript"]
        body = re.sub(r"\$\((\w+)\)", lambda m: {"logicAppType": hosting}.get(m[1], "test-subscription"), body)
        end_marker = "variable=logicAppsExists]false"
    else:
        steps = next(iter(yaml.safe_load((base / "github-actions/infra-project-phase.yml")
                                         .read_text(encoding="utf-8"))["jobs"].values()))["steps"]
        body = next(s for s in steps if s.get("name") == "16_Check_Resource_Existence")["run"]
        body = re.sub(r"\$\{\{ env\.(\w+) }}", lambda m: {"logicAppType": hosting}.get(m[1], "test-subscription"), body)
        end_marker = 'set_env "logicAppsExists" "false"'
    lines = body.splitlines()
    name_line = next(line for line in lines if re.match(r'\s*logicApps?Name="', line))
    start = next(i for i, line in enumerate(lines) if 'logicResourceType="Microsoft.Web/sites"' in line)
    end = next(i for i in range(start, len(lines)) if end_marker in lines[i])
    end += 1 if provider == "ado" else 0
    block = "\n".join([name_line] + lines[start:end + 1])
    expected_type = "Microsoft.Web/sites" if hosting == "Standard" else "Microsoft.Logic/workflows"
    deployed = "lapp-012-swe-dev-h7amw-001"  # 11-integration.bicep logicAppsName with resourceSuffix -001
    fake = f"""
projectNumber=012; projectName=prj012; locationSuffix=swe; envName=dev; suffixStandard=-001
targetResourceGroup=rg; targetRG=rg
set_env() {{ echo "$1=$2"; }}
az() {{
  [ "$MODE" = denied ] && {{ echo Forbidden >&2; return 1; }}
  type=""; query=""
  while [ $# -gt 0 ]; do
    case "$1" in --resource-type) type="$2"; shift;; --query) query="$2"; shift;; esac; shift
  done
  [ "$type" = "{expected_type}" ] || {{ echo "unexpected type $type" >&2; return 98; }}
  case "$query" in *"'lapp-012-swe-dev-'"*"'-001'"*) ;; *) echo "unexpected query $query" >&2; return 97;; esac
  case "$MODE" in
    existing) echo "{deployed}";;
    ambiguous) printf '%s\\n%s\\n' "{deployed}" "lapp-012-swe-dev-other-001";;
  esac
}}
"""
    workspace = ROOT / ".test-state" / ("logicapp-exists-" + uuid4().hex)
    workspace.mkdir(parents=True)
    script = workspace / "exists.sh"
    script.write_text(fake + block + "\n", encoding="utf-8", newline="\n")
    bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
    try:
        run = subprocess.run([str(bash) if bash.exists() else "bash", str(script)], cwd=ROOT, text=True,
                             capture_output=True, timeout=30, env={**os.environ, "MODE": mode})
    finally:
        shutil.rmtree(workspace)
    if mode in ("ambiguous", "denied"):
        assert run.returncode != 0, run.stdout
        assert "logicAppsExists" not in run.stdout
    else:
        assert run.returncode == 0, run.stdout + run.stderr
        expected = "true" if mode == "existing" else "false"
        assert (f"variable=logicAppsExists]{expected}" if provider == "ado" else
                f"logicAppsExists={expected}") in run.stdout


def test_logic_app_plan_is_only_created_for_standard():
    template = compile_entry("11-integration.bicep")
    resources = template["resources"].values() if isinstance(template["resources"], dict) else template["resources"]
    plan = next(item for item in resources if "11-Appfarm-LogicApps01-" in item["name"])
    # Consumption must not provision (or wait on capacity for) an unused WS1 plan.
    assert "parameters('logiAppType'), 'Standard'" in plan["condition"]
    assert "logicAppsExists" in plan["condition"]


@pytest.mark.parametrize("hosting", ["", "$(logicAppType)", "Standard", "Consumption", "invalid"])
def test_actual_ado_normalizer_preserves_historical_standard_default(hosting):
    path = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/logic-app-network-steps.yaml"
    code = yaml.safe_load(path.read_text())["steps"][0]["inputs"]["script"]
    run = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", code],
                         cwd=ROOT, capture_output=True, text=True, timeout=20,
                         env={**os.environ, "LOGIC_APP_TYPE": hosting,
                              "SUBNET_PROJ_LOGICAPP": "$(subnetProjLogicapp)"})
    if hosting == "invalid":
        assert run.returncode != 0
    else:
        assert run.returncode == 0, run.stderr
        expected = hosting if hosting in ("Standard", "Consumption") else "Standard"
        assert f"variable=logicAppType]{expected}" in run.stdout
        assert "variable=subnetProjLogicapp]\n" in run.stdout


def _all_steps(steps):
    """Top-level steps plus the steps inside ADO ${{ if }} / ${{ else }} blocks (e.g. the linuxRunner arms)."""
    for step in steps:
        if isinstance(step, dict) and len(step) == 1 and next(iter(step)).startswith("${{"):
            yield from _all_steps(next(iter(step.values())))
        elif isinstance(step, dict):
            yield step


def test_provider_allocator_dynamic_and_task68_pass_the_same_flags():
    base = BICEP / "copy_to_local_settings"
    ado = base / "azure-devops/esml-yaml-pipelines"
    network = yaml.safe_load((ado / "esml-infra-project/jobs/job-1-genai-networking.yaml").read_text(encoding="utf-8"))["steps"]
    services = yaml.safe_load((ado / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8"))["steps"]
    gha = next(iter(yaml.safe_load((base / "github-actions/infra-project-phase.yml").read_text(encoding="utf-8"))["jobs"].values()))["steps"]
    for steps, key, names in (
        (network, "displayName", ["04_pwsh_calculate_subnet_allocations", "05_arm_deploy_subnets_and_NSGs"]),
        (services, "displayName", ["04_pwsh_fetch_network_parameters", "68-integration"]),
        (gha, "name", ["05_Calculate_Subnet_Allocations", "07_Deploy_Subnet_IfNotExists",
                       "14_Generate_Dynamic_Network_Parameters", "68-integration"]),
    ):
        for name in names:
            matches = [step for step in _all_steps(steps) if step.get(key) == name]
            assert matches, name
            for step in matches:  # every conditional arm must pass the same flags
                code = json.dumps(step)
                for flag in ("enableLogicApps", "byoASEv3", "enablePublicAccessWithPerimeter"):
                    assert flag in code, (name, flag)
                assert "logicAppType" in code
                if name == "68-integration":
                    assert "logiAppType" in code
                    assert "dynamicNetworkParams.json" in code
    assert any(step.get("template") == "../../variables/logic-app-network-steps.yaml" for step in network)
    assert any(step.get("template") == "../../variables/logic-app-network-steps.yaml" for step in services)


def test_standalone_capacity_runner_filters_internal_dynamic_id(runner):
    result = runner.deployment_parameters(
        {"parameters": {"genaiSubnetId": {"type": "string", "defaultValue": ""}}},
        {"parameters": {"genaiSubnetId": {"value": "inbound"}, "logicappSubnetId": {"value": LOGIC_ID}}},
        {}, {},
    )
    assert result["parameters"] == {"genaiSubnetId": {"value": "inbound"}}


def test_simple_mode_profile_does_not_reserve_disabled_logic_app_capacity():
    from .test_simple_bootstrap import CONFIG
    assert "enableLogicApps" in CONFIG.SIMPLE_MODE_DISABLED
    assert "logic-apps" not in {item["id"] for item in CONFIG.SIMPLE_MODE_RESOURCE_CATALOG["project"]}
