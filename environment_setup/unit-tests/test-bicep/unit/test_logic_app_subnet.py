"""Offline dedicated Logic Apps subnet contracts: real PowerShell, Bicep and CI sources."""

import ast
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
SCRIPTS = BICEP / "scripts"
SETTINGS = BICEP / "copy_to_local_settings"
ADO = SETTINGS / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs"
GH = SETTINGS / "github-actions/infra-project-phase.yml"
SUB = "11111111-1111-4111-8111-111111111111"
VNET_ID = f"/subscriptions/{SUB}/resourceGroups/network-rg/providers/Microsoft.Network/virtualNetworks/shared-dev"
LOGIC_ID = VNET_ID + "/subnets/snt-prj012-logicapp"
FLAGS = dict(enableLogicApps="true", logicAppType="Standard", byoASEv3="false",
             enablePublicAccessWithPerimeter="false")
SUFFIXES = dict(genai="genai", aks="aks", aks2="aks-002", aca="aca", aca2="aca-002",
                webapp="webapp", dbxPub="dbxpub", dbxPriv="dbxpriv")


def ps(tmp_path, code, fixture=None):
    executable = shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell Core required")
    if fixture is not None:
        (tmp_path / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    script = tmp_path / "run.ps1"
    script.write_text("$ErrorActionPreference='Stop'\n" + code, encoding="utf-8")
    return subprocess.run([executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script)],
                          cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60,
                          env={**os.environ, "AIFACTORY_USE_AZURE_CLI": "true", "GITHUB_ACTIONS": "false"})


MOCKS = r"""
$global:fixture = Get-Content './fixture.json' -Raw | ConvertFrom-Json -AsHashtable
function Import-Module { param($Name) }
function Import-Dependencies {}
function ConvertTo-Variables {
    param($InputObject)
    foreach ($property in $InputObject.parameters.PSObject.Properties) {
        Set-Variable -Scope Global -Name $property.Name -Value $property.Value.value
    }
}
function az {
    Add-Content './reads.jsonl' (ConvertTo-Json -InputObject @($args) -Compress)
    $global:LASTEXITCODE = 0
    $command = $args[0..2] -join ' '
    if ($command -eq 'network vnet show') {
        $fixture.vnet | ConvertTo-Json -Depth 20 -Compress
    } elseif ($command -eq 'deployment group show') {
        $query = $args[[array]::IndexOf($args, '--query') + 1]
        if ($query -match 'properties.outputs.(\w+).value') {
            $key = $Matches[1]
            if ($query.StartsWith('{state:')) {
                @{ state=$fixture.deploymentState; value=$fixture.outputs[$key] } | ConvertTo-Json -Compress
            } else { $fixture.outputs[$key] }
        } else { throw 'Unexpected deployment query' }
    } elseif (($args[0..3] -join ' ') -eq 'network vnet subnet show') {
        if ($fixture.readFailure) { $global:LASTEXITCODE = 1; return 'AuthorizationFailed' }
        $fixture.subnet | ConvertTo-Json -Depth 20 -Compress
    } else {
        throw 'Unexpected Azure command: tests allow reads only'
    }
}
$parameters = $fixture.parameters
"""


def subnet(name="snt-prj012-logicapp", cidr="100.120.94.128/26"):
    return dict(name=name, id=VNET_ID + "/subnets/" + name, addressPrefix=cidr,
                provisioningState="Succeeded", delegations=[dict(serviceName="Microsoft.Web/serverFarms")])


def existing_vnet():
    cidrs = ["100.120.90.0/25", "100.120.94.0/26", "100.120.91.0/24",
             "100.120.88.0/23", "100.120.92.0/23", "100.120.94.64/27",
             "100.120.90.128/26", "100.120.90.192/26"]
    subnets = [subnet(f"snt-prj012-{suffix}", cidr) for suffix, cidr in zip(SUFFIXES.values(), cidrs)]
    subnets.append(subnet("snt-prj001-genai", "100.120.80.0/25"))
    return dict(id=VNET_ID, addressSpace=dict(addressPrefixes=["100.120.64.0/18"]), subnets=subnets)


def allocate(tmp_path, *, flags=None, vnet=None, project="012", environment="dev"):
    parameters = dict(filePath=str(tmp_path), env=environment, subscriptionId=SUB,
                      prjResourceSuffix="-001", aifactorySuffixRGADO="-001",
                      commonResourceSuffixADO="-001", locationADO="westeurope",
                      locationSuffixADO="weu", projectTypeADO="all", commonRGNamePrefixVar="fixture-",
                      vnetNameBase="shared", vnetResourceGroupBase="network",
                      vnetResourceGroup_param="network-rg", vnetNameFull_param="shared-dev",
                      projectNumber=project, **(FLAGS if flags is None else flags))
    fixture = dict(vnet=existing_vnet() if vnet is None else vnet, parameters=parameters)
    result = ps(tmp_path, MOCKS + f"\n& '{SCRIPTS / 'subnetCalc_v2.ps1'}' @parameters\n", fixture)
    return result, tmp_path / "subnetParameters.json"


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_actual_allocator_preserves_all_priors_and_appends_dedicated_26(tmp_path, environment):
    vnet = existing_vnet()
    before = copy.deepcopy(vnet)
    result, path = allocate(tmp_path, vnet=vnet, environment=environment)
    assert result.returncode == 0, result.stderr
    values = json.loads(path.read_text(encoding="utf-8-sig"))["parameters"]
    for key, previous in zip(SUFFIXES, vnet["subnets"]):
        assert values[key + "SubnetCidr"]["value"] == previous["addressPrefix"]
    allocated = ipaddress.ip_network(values["logicappSubnetCidr"]["value"])
    assert str(allocated) == "100.120.94.128/26"
    assert all(not allocated.overlaps(ipaddress.ip_network(item["addressPrefix"])) for item in vnet["subnets"])
    assert vnet == before


@pytest.mark.parametrize("flag,value", [("enableLogicApps", "false"), ("logicAppType", "Consumption"),
                                       ("byoASEv3", "true"), ("enablePublicAccessWithPerimeter", "true")])
@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_disabled_modes_allocate_nothing_extra_even_when_vnet_full(tmp_path, flag, value, environment):
    vnet = existing_vnet()
    vnet["subnets"].append(subnet("tail", "100.120.127.0/24"))
    result, path = allocate(tmp_path, flags={**FLAGS, flag: value}, vnet=vnet, environment=environment)
    assert result.returncode == 0, result.stderr
    assert "logicappSubnetCidr" not in json.loads(path.read_text(encoding="utf-8-sig"))["parameters"]


def test_existing_dedicated_subnet_is_reused_without_allocating_more(tmp_path):
    vnet = existing_vnet()
    vnet["subnets"] += [subnet(), subnet("tail", "100.120.127.0/24")]
    result, path = allocate(tmp_path, vnet=vnet)
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text(encoding="utf-8-sig"))["parameters"]["logicappSubnetCidr"]["value"] == "100.120.94.128/26"


@pytest.mark.parametrize("problem", ["missing-id", "foreign-vnet", "missing-subnets", "null-subnets", "object-subnets", "foreign-subnet-id"])
def test_allocator_requires_exact_vnet_identity_and_complete_subnet_inventory(tmp_path, problem):
    vnet = existing_vnet()
    if problem == "missing-id":
        vnet.pop("id")
    elif problem == "foreign-vnet":
        vnet["id"] = VNET_ID + "-other"
    elif problem == "missing-subnets":
        vnet.pop("subnets")
    elif problem == "null-subnets":
        vnet["subnets"] = None
    elif problem == "object-subnets":
        vnet["subnets"] = {}
    else:
        item = subnet()
        item["id"] = LOGIC_ID.replace("shared-dev", "other-vnet")
        vnet["subnets"].append(item)
    result, output = allocate(tmp_path, vnet=vnet)
    assert result.returncode != 0 and not output.exists()


@pytest.mark.parametrize("problem", ["full", "overlap", "outside", "multiple-spaces", "small", "delegation", "state"])
def test_unsafe_network_or_existing_logic_subnet_fails_before_output(tmp_path, problem):
    vnet = existing_vnet()
    if problem == "full":
        vnet["subnets"].append(subnet("tail", "100.120.127.0/24"))
    elif problem == "overlap":
        vnet["subnets"].append(subnet("overlap", "100.120.94.0/25"))
    elif problem == "outside":
        vnet["subnets"].append(subnet("outside", "100.120.128.0/24"))
    elif problem == "multiple-spaces":
        vnet["addressSpace"]["addressPrefixes"].append("10.0.0.0/16")
    else:
        existing = subnet()
        if problem == "small":
            existing["addressPrefix"] = "100.120.94.128/27"
        elif problem == "delegation":
            existing["delegations"] = []
        else:
            existing["provisioningState"] = "Updating"
        vnet["subnets"].append(existing)
    result, path = allocate(tmp_path, vnet=vnet)
    assert result.returncode != 0
    assert not path.exists()


@pytest.mark.parametrize("flag,value", [("enableLogicApps", "$(enableLogicApps)"), ("enableLogicApps", ""),
                                       ("logicAppType", "unknown"), ("byoASEv3", "yes"),
                                       ("enablePublicAccessWithPerimeter", "$(missing)")])
def test_unknown_flags_are_errors_not_disabled(tmp_path, flag, value):
    result, path = allocate(tmp_path, flags={**FLAGS, flag: value})
    assert result.returncode != 0 and not path.exists()
    assert not (tmp_path / "reads.jsonl").exists()


def dynamic(tmp_path, *, byo=False, flags=None, name="snt-<network_env>prj<xxx>-logicapp",
            output=LOGIC_ID, returned=None, read_failure=False, deployment_state="Succeeded"):
    parameters = dict(filePath=str(tmp_path) + os.sep, env="dev", subscriptionId=SUB,
                      aifactorySuffixRGADO="-001", locationSuffixADO="weu", projectNumber="012",
                      projectTypeADO="all", BYO_subnets=str(byo).lower(), network_env="dev-",
                      enableAIFoundry="false", enableAksForAzureML="false", enableContainerApps="false",
                      **(FLAGS if flags is None else flags))
    common = dict(vnetResourceGroup_param="network-rg", vnetNameFull_param="shared-dev",
                  vnetNameBase="shared", vnetResourceGroupBase="network", commonResourceSuffix="-001")
    for index in range(1, 6):
        values = {**common, "subnetProjLogicapp": name} if index == 5 else {}
        path = tmp_path / f"input{index}.json"
        path.write_text(json.dumps(dict(parameters={k: dict(value=v) for k, v in values.items()})))
        parameters[f"bicepPar{index}"] = str(path)
    outputs = {key + "SubnetId": VNET_ID + "/subnets/snt-prj012-" + suffix
               for key, suffix in SUFFIXES.items()}
    outputs.update(logicappSubnetId=output, dbxPubSubnetName="snt-prj012-dbxpub", dbxPrivSubnetName="snt-prj012-dbxpriv")
    fixture = dict(parameters=parameters, outputs=outputs, subnet=subnet() if returned is None else returned,
                   readFailure=read_failure, deploymentState=deployment_state)
    result = ps(tmp_path, MOCKS + f"\n& '{SCRIPTS / 'genDynamicNetworkParamFile.ps1'}' @parameters\n", fixture)
    return result, tmp_path / "dynamicNetworkParams.json"


def test_dynamic_output_retains_exact_subnet_id_and_reads_it(tmp_path):
    result, path = dynamic(tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text(encoding="utf-8-sig"))["parameters"]["logicappSubnetId"]["value"] == LOGIC_ID
    reads = [json.loads(line) for line in (tmp_path / "reads.jsonl").read_text().splitlines()]
    assert reads[-1][0:4] == ["network", "vnet", "subnet", "show"]
    assert reads[-1][5] == LOGIC_ID


@pytest.mark.parametrize("bad", ["", LOGIC_ID.replace("012", "001"), LOGIC_ID.replace("network-rg", "wrong-rg"),
                                 LOGIC_ID.replace("shared-dev", "shared-prod"), LOGIC_ID.replace("logicapp", "aks")])
def test_missing_or_stale_network_outputs_fail_closed(tmp_path, bad):
    result, path = dynamic(tmp_path, output=bad)
    assert result.returncode != 0 and not path.exists()


def test_failed_deployment_cannot_supply_stale_successful_subnet_output(tmp_path):
    result, path = dynamic(tmp_path, deployment_state="Failed")
    assert result.returncode != 0 and not path.exists()


@pytest.mark.parametrize("problem", ["read", "state", "delegation", "id", "prefix", "private-endpoint", "nic"])
def test_live_subnet_read_must_match_contract(tmp_path, problem):
    item = subnet()
    if problem == "state":
        item["provisioningState"] = "Failed"
    elif problem == "delegation":
        item["delegations"].append(dict(serviceName="Microsoft.App/environments"))
    elif problem == "id":
        item["id"] = LOGIC_ID.replace("012", "001")
    elif problem == "prefix":
        item["addressPrefix"] = "100.120.94.128/27"
    elif problem == "private-endpoint":
        item["privateEndpoints"] = [dict(id="endpoint")]
    elif problem == "nic":
        item["ipConfigurations"] = [dict(id="nic-ipconfig")]
    result, path = dynamic(tmp_path, returned=item, read_failure=problem == "read")
    assert result.returncode != 0 and not path.exists()


def test_byo_explicit_name_placeholders_are_routed_and_read_not_mutated(tmp_path):
    item = subnet("snt-dev-prj012-logicapp")
    result, path = dynamic(tmp_path, byo=True, returned=item)
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text(encoding="utf-8-sig"))["parameters"]["logicappSubnetId"]["value"] == item["id"]
    reads = [json.loads(line) for line in (tmp_path / "reads.jsonl").read_text().splitlines()]
    assert len(reads) == 1 and reads[0][:4] == ["network", "vnet", "subnet", "show"]


@pytest.mark.parametrize("name", ["", "$(subnetProjLogicapp)", "<todo>", "snt-prj012-aks", "snt-prj012-webapp"])
def test_byo_rejects_missing_invalid_or_shared_subnet_name(tmp_path, name):
    result, path = dynamic(tmp_path, byo=True, name=name)
    assert result.returncode != 0 and not path.exists()


@pytest.mark.parametrize("flag,value", [("enableLogicApps", "false"), ("logicAppType", "Consumption"),
                                       ("byoASEv3", "true"), ("enablePublicAccessWithPerimeter", "true")])
def test_dynamic_disabled_gate_never_reads_logic_subnet(tmp_path, flag, value):
    result, path = dynamic(tmp_path, flags={**FLAGS, flag: value}, output="", read_failure=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text(encoding="utf-8-sig"))["parameters"]["logicappSubnetId"]["value"] == ""
    assert "logicappSubnetId" not in (tmp_path / "reads.jsonl").read_text()


def compile_bicep(path, output):
    compiler = shutil.which("bicep")
    if not compiler:
        pytest.skip("Cached Bicep CLI required")
    result = subprocess.run([compiler, "build", str(path), "--no-restore", "--outfile", str(output)],
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(output.read_text(encoding="utf-8-sig"))


def test_compiled_site_uses_logic_id_not_aks_and_keeps_genai_inbound(tmp_path):
    source = BICEP / "esml-genai-1/11-integration.bicep"
    baseline = subprocess.run(["git", "show", "1b4a2190:environment_setup/aifactory/bicep/esml-genai-1/11-integration.bicep"],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    previous = next(line for line in baseline.splitlines() if "virtualNetworkSubnetResourceId:" in line)
    assert "aksSubnetName" in previous  # Reproduces the task-68 root cause in the authorized baseline.
    compiled = compile_bicep(source, tmp_path / "integration.json")
    resources = compiled["resources"]
    site = next(resource for resource in (resources.values() if isinstance(resources, dict) else resources)
                if "virtualNetworkSubnetResourceId" in resource.get("properties", {}).get("parameters", {}))
    parameters = site["properties"]["parameters"]
    outbound = json.dumps(parameters["virtualNetworkSubnetResourceId"])
    assert "parameters('logicappSubnetId')" in outbound and "aksSubnet" not in outbound
    assert "parameters('byoASEv3')" in outbound and "parameters('enablePublicAccessWithPerimeter')" in outbound
    assert "genaiSubnetName" in json.dumps(parameters["privateEndpoints"])
    assert "logicAppsExists" in site["condition"]
    assert "subnetDelegationServerFarm" not in source.read_text(encoding="utf-8")


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


def compiled_logic_site(tmp_path):
    template = compile_bicep(BICEP / "esml-genai-1/11-integration.bicep", tmp_path / "integration.json")
    resources = template["resources"]
    site = next(resource for resource in (resources.values() if isinstance(resources, dict) else resources)
                if "virtualNetworkSubnetResourceId" in resource.get("properties", {}).get("parameters", {}))
    return template, site["properties"]["parameters"]


@pytest.mark.parametrize("flags", [{}, {"byoASEv3": True}, {"enablePublicAccessWithPerimeter": True}])
def test_compiled_site_fails_closed_without_logic_subnet(tmp_path, flags):
    # An empty ID must never deploy a private Logic App without outbound integration.
    template, parameters = compiled_logic_site(tmp_path)
    expression = parameters["virtualNetworkSubnetResourceId"]
    values = {"logicappSubnetId": LOGIC_ID, "byoASEv3": False, "enablePublicAccessWithPerimeter": False, **flags}
    assert arm_value(expression, values, template) == {"value": "" if flags else LOGIC_ID}
    values["logicappSubnetId"] = ""
    if flags:
        assert arm_value(expression, values, template) == {"value": ""}
    else:
        with pytest.raises(ValueError, match="requires logicappSubnetId"):
            arm_value(expression, values, template)


@pytest.mark.parametrize("flags,integrated", [
    ({}, True), ({"byoASEv3": True}, False), ({"enablePublicAccessWithPerimeter": True}, False),
])
def test_compiled_logic_app_routes_all_outbound_traffic_through_vnet(tmp_path, flags, integrated):
    # RFC1918-only routing would bypass private endpoints in ranges such as 100.64.0.0/10.
    template, parameters = compiled_logic_site(tmp_path)
    values = {"byoASEv3": False, "enablePublicAccessWithPerimeter": False, **flags}
    routing = arm_value(parameters["outboundVnetRouting"], values, template)["value"]
    web = next(config for config in parameters["configs"]["value"] if config["name"] == "web")["properties"]
    assert arm_value(web["vnetRouteAllEnabled"], values, template) is integrated
    if integrated:
        assert routing == {"allTraffic": True, "applicationTraffic": True, "contentShareTraffic": True}
    else:
        assert routing is None


def test_network_compiles_with_dedicated_delegation_and_all_sibling_dependencies(tmp_path):
    compiled = compile_bicep(BICEP / "esml-genai-1/31-network.bicep", tmp_path / "network.json")
    writer = next(resource for resource in compiled["resources"] if "logicappSnet-" in resource["name"])
    values = writer["properties"]["parameters"]
    assert values["delegations"]["value"] == ["Microsoft.Web/serverFarms"]
    assert values["name"]["value"] == "[format('snt-{0}-logicapp', variables('projectName'))]"
    for prefix in ("aks-", "aks2-", "genai-", "acaSnet-", "acaSnet2-", "webappSnet-", "dbxpub-", "dbxpriv-"):
        assert prefix in json.dumps(writer["dependsOn"])
    assert "sntLogicappExists" in compiled["variables"]["createLogicappSubnet"]
    assert "BYO_subnets" in compiled["variables"]["createLogicappSubnet"]
    assert "logicappSubnetId" in compiled["outputs"]
    assert compiled["variables"]["aksSubnetSettings"]["delegations"] == []
    assert compiled["variables"]["genaiSubnetSettings"]["delegations"] == []


def test_all_global_dynamic_consumers_accept_optional_logicapp_id(tmp_path):
    consumers = list((BICEP / "esml-genai-1").glob("*.bicep"))
    consumers = [path for path in consumers if "param webappSubnetId" in path.read_text(encoding="utf-8")]
    assert len(consumers) == 13
    for source in consumers:
        compiled = compile_bicep(source, tmp_path / (source.stem + ".json"))
        assert compiled["parameters"]["logicappSubnetId"] == {"type": "string", "defaultValue": ""} or (
            compiled["parameters"]["logicappSubnetId"]["defaultValue"] == "")


@pytest.mark.parametrize("provider", ["ado", "github"])
def test_provider_contract_wires_flags_and_existing_site_guard(provider):
    if provider == "ado":
        network = yaml.safe_load((ADO / "job-1-genai-networking.yaml").read_text(encoding="utf-8"))["steps"]
        services = yaml.safe_load((ADO / "job-2-genai-services.yaml").read_text(encoding="utf-8"))["steps"]
        calc = next(s["inputs"]["arguments"] for s in network if s.get("displayName") == "04_pwsh_calculate_subnet_allocations")
        dynamic_call = next(s["inputs"]["arguments"] for s in services if s.get("displayName") == "04_pwsh_fetch_network_parameters")
        deploy = next(s["inputs"]["overrideParameters"] for s in network if s.get("displayName") == "05_arm_deploy_subnets_and_NSGs")
        text = (ADO / "job-2-genai-services.yaml").read_text(encoding="utf-8")
        for task in (next(s for s in network if s.get("displayName") == "00_preflight_network_cidr_checks"),
                     next(s for s in services if "preflight" in s.get("displayName", ""))):
            assert all(flag in task["env"] for flag in FLAGS)
    else:
        text = GH.read_text(encoding="utf-8")
        steps = yaml.safe_load(text)["jobs"]["deploy-project"]["steps"]
        calc = next(s["run"] for s in steps if s.get("name") == "05_Calculate_Subnet_Allocations")
        dynamic_call = next(s["run"] for s in steps if s.get("name") == "14_Generate_Dynamic_Network_Parameters")
        deploy = next(s["run"] for s in steps if s.get("name") == "07_Deploy_Subnet_IfNotExists")
    for call in (calc, dynamic_call, deploy):
        for flag in FLAGS:
            assert flag in call
    assert "projectNumber" in calc and "sntLogicappExists" in deploy
    assert "subnetProjLogicapp" in text and "logiAppType=" in text
    assert 'logicResourceType="Microsoft.Web/sites"' in text
    assert 'logicResourceType="Microsoft.Logic/workflows"' in text
    assert "Ambiguous existing Logic Apps" in text and "lapp-${projectNumber}-${locationSuffix}-${envName}-" in text
    assert "deploy-integration-with-retry.py -- az deployment sub create" in text


@pytest.mark.parametrize("invalid", [False, True])
def test_legacy_ado_unset_values_use_defaults_but_macros_fail(tmp_path, invalid):
    reset = "\n".join(f"Remove-Item 'Env:{name.upper()}' -ErrorAction SilentlyContinue"
                      for name in [*FLAGS, "subnetProjLogicapp"])
    if invalid:
        reset += "\n$env:LOGICAPPTYPE='$(unknown)'"
    result = ps(tmp_path, reset + f"\n& '{SCRIPTS / 'resolve-logicapp-network-inputs.ps1'}'\n")
    if invalid:
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        assert "variable=logicAppType]Standard" in result.stdout
        assert "variable=enableLogicApps]false" in result.stdout
        assert "variable=subnetProjLogicapp]\n" in result.stdout


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("problem", ["none", "denied", "wrong-id", "missing-subnets", "null-subnets", "foreign-child"])
def test_actual_subnet_existence_probe_rejects_read_failure_and_is_project_exact(tmp_path, provider, problem):
    if provider == "ado":
        steps = yaml.safe_load((ADO / "job-1-genai-networking.yaml").read_text(encoding="utf-8"))["steps"]
        task = next(s for s in steps if s.get("displayName") == "04b_check_subnet_exists_for_project")
        assert task["inputs"]["scriptPath"].endswith("/getProjectSubnetState.ps1")
        assert task["inputs"]["scriptType"] == "pscore"
    else:
        steps = yaml.safe_load(GH.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["steps"]
        task = next(s for s in steps if s.get("name") == "06_Check_Subnet_Existence")
        assert "getProjectSubnetState.ps1" in task["run"] and task["shell"] == "pwsh"
    vnet = {"id": VNET_ID, "subnets": [subnet(), subnet("snt-prj001-genai")]}
    if problem == "wrong-id":
        vnet["id"] = VNET_ID + "-wrong"
    elif problem == "missing-subnets":
        vnet.pop("subnets")
    elif problem == "null-subnets":
        vnet["subnets"] = None
    elif problem == "foreign-child":
        vnet["subnets"][0]["id"] = LOGIC_ID.replace("shared-dev", "other-vnet")
    code = f"""
$env:GITHUB_ENV = Join-Path $PWD 'probe.env'
function az {{
    $global:LASTEXITCODE = {9 if problem == 'denied' else 0}
    Get-Content './fixture.json' -Raw
}}
& '{SCRIPTS / 'getProjectSubnetState.ps1'}' -SubscriptionId '{SUB}' -ResourceGroupName network-rg -VnetName shared-dev -ProjectNumber 012 -Provider {provider}
"""
    result = ps(tmp_path, code, vnet)
    if problem != "none":
        assert result.returncode != 0
        assert "sntLogicappExists" not in result.stdout and not (tmp_path / "probe.env").exists()
    else:
        assert result.returncode == 0, result.stderr
        output = result.stdout if provider == "ado" else (tmp_path / "probe.env").read_text()
        assert ("sntLogicappExists]true" if provider == "ado" else "sntLogicappExists=true") in output
        assert ("sntGenaiExists]false" if provider == "ado" else "sntGenaiExists=false") in output
