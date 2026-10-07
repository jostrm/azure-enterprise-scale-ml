"""Invoke the real PowerShell entry point, mocking only read-only Azure inventory.

These are offline allocation/parameter contract regressions, not deployment proof.
"""

import copy
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[4]
ALLOCATOR = ROOT / "environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1"
SUFFIXES = {
    "aksSubnetCidr": "aks", "aks2SubnetCidr": "aks-002",
    "acaSubnetCidr": "aca", "aca2SubnetCidr": "aca-002",
    "genaiSubnetCidr": "genai", "webappSubnetCidr": "webapp",
    "dbxPubSubnetCidr": "dbxpub", "dbxPrivSubnetCidr": "dbxpriv",
}


def subnet(name, cidr):
    return {"name": name, "addressPrefix": cidr}


def inventory(prefixes=("10.113.0.0/18",), subnets=()):
    return {"addressSpace": {"addressPrefixes": list(prefixes)}, "subnets": list(subnets)}


def invoke_allocator(vnet, *, azure="cli", json_project=None, json_parameters=None, **overrides):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell is required for allocator entry-point regressions")
    workspace = ROOT / ".test-state" / ("allocator-" + uuid4().hex)
    workspace.mkdir(parents=True)
    parameters = {
        "filePath": str(workspace), "env": "dev", "subscriptionId": "test-subscription",
        "prjResourceSuffix": "-099", "projectNumber": "001",
        "aifactorySuffixRGADO": "-007", "commonResourceSuffixADO": "-008",
        "locationADO": "swedencentral", "locationSuffixADO": "swc",
        "location": "swedencentral", "projectTypeADO": "all",
        "commonRGNamePrefixVar": "acme-", "vnetNameBase": "vnet",
        "vnetResourceGroupBase": "common",
    }
    parameters.update(overrides)
    if json_project is not None or json_parameters is not None:
        for index in range(1, 6):
            path = workspace / f"input-{index}.json"
            values = dict((json_parameters or {}).get(index, {}))
            if json_project is not None and index == 4:
                values["projectNumber"] = json_project
            path.write_text(json.dumps({"parameters": {
                key: {"value": value} for key, value in values.items()
            }}), encoding="utf-8")
            parameters[f"bicepPar{index}"] = str(path)
    parameters = {key: value for key, value in parameters.items() if value is not None}
    expected_name = parameters.get("vnetNameFull_param") or f"vnet-swc-{parameters['env']}-008"
    expected_rg = parameters.get("vnetResourceGroup_param") or f"acme-common-swc-{parameters['env']}-007"
    code = r"""
$ErrorActionPreference = 'Stop'
function global:Install-Module { throw 'Module installation is forbidden in offline tests' }
$parameters = $env:ALLOC_PARAMETERS | ConvertFrom-Json -AsHashtable
function global:az {
    if (($args[0..2] -join ' ') -ne 'network vnet show' -or
        $args[[array]::IndexOf($args, '--subscription') + 1] -ne 'test-subscription' -or
        $args[[array]::IndexOf($args, '--name') + 1] -ne $env:ALLOC_NAME -or
        $args[[array]::IndexOf($args, '--resource-group') + 1] -ne $env:ALLOC_RG) {
        throw "Unexpected Azure command: $args"
    }
    $global:LASTEXITCODE = if ($env:ALLOC_AZURE -eq 'cli-error') { 1 } else { 0 }
    $env:ALLOC_INVENTORY
}
if ($env:ALLOC_AZURE -in @('az', 'wrong-context')) {
    Microsoft.PowerShell.Core\Import-Module (Join-Path (Split-Path $env:ALLOC_SCRIPT) 'modules/pipelineFunctions.psm1')
    & (Get-Module pipelineFunctions) { function script:Import-Dependencies {} }
    function global:Get-AzContext {
        [pscustomobject]@{Subscription = [pscustomobject]@{Id = $env:ALLOC_CONTEXT}; Account = 'offline'}
    }
    function global:Get-AzVirtualNetwork {
        param($ResourceGroupName, $Name)
        if ($Name -ne $env:ALLOC_NAME -or $ResourceGroupName -ne $env:ALLOC_RG) {
            throw 'Wrong environment VNet'
        }
        $env:ALLOC_INVENTORY | ConvertFrom-Json
    }
}
try {
    & $env:ALLOC_SCRIPT @parameters
} catch {
    # Preserve the actual diagnostic without host-dependent ANSI wrapping.
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""
    try:
        run = subprocess.run(
            [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
            env={**os.environ, "GITHUB_ACTIONS": "true" if azure.startswith("cli") else "false",
                 "AIFACTORY_USE_AZURE_CLI": "true" if azure == "ado-cli" else "false",
                 "ALLOC_AZURE": azure,
                 "ALLOC_CONTEXT": "wrong" if azure == "wrong-context" else "test-subscription",
                 "ALLOC_SCRIPT": str(ALLOCATOR), "ALLOC_INVENTORY": json.dumps(vnet),
                 "ALLOC_PARAMETERS": json.dumps(parameters),
                 "ALLOC_NAME": expected_name, "ALLOC_RG": expected_rg},
        )
        output = workspace / "subnetParameters.json"
        data = json.loads(output.read_text(encoding="utf-8-sig")) if output.exists() else None
        return run, data
    finally:
        shutil.rmtree(workspace)


def allocate(vnet, **parameters):
    before = copy.deepcopy(vnet)
    run, data = invoke_allocator(vnet, **parameters)
    assert run.returncode == 0, run.stdout + run.stderr
    assert vnet == before
    assert data["contentVersion"] == "1.0.0.0"
    return {key: item["value"] for key, item in data["parameters"].items() if key in SUFFIXES}


def deploy_inventory(vnet, result, project="001"):
    vnet["subnets"].extend(subnet(f"snt-prj{project}-{SUFFIXES[key]}", value)
                           for key, value in result.items())


def assert_disjoint(vnet, result):
    spaces = [ipaddress.ip_network(cidr) for cidr in vnet["addressSpace"]["addressPrefixes"]]
    reserved = [ipaddress.ip_network(cidr) for item in vnet["subnets"]
                for cidr in (item.get("addressPrefixes") or [item["addressPrefix"]])]
    allocated = [ipaddress.ip_network(cidr) for cidr in result.values()]
    assert all(any(net.subnet_of(space) for space in spaces) for net in allocated)
    assert not any(net.overlaps(other) for net in allocated for other in reserved)
    assert not any(a.overlaps(b) for i, a in enumerate(allocated) for b in allocated[i + 1:])


def integrated_inventory():
    return inventory(subnets=[
        *(subnet(f"common-{i}", f"10.113.0.{i * 64}/26") for i in range(4)),
        subnet("snet-dns-private-resolver", "10.113.63.208/28"),
        subnet("GatewaySubnet", "10.113.63.224/27"),
    ])


def test_tail_gateway_three_projects_repeat_and_additions():
    vnet = integrated_inventory()
    original = copy.deepcopy(vnet["subnets"])
    for number in range(1, 4):
        project = f"{number:03}"
        result = allocate(vnet, projectNumber=project)
        assert len(result) == 8
        assert_disjoint(vnet, result)
        deploy_inventory(vnet, result, project)
        # Neither the resource suffix (-099) nor Azure enumeration order identifies the project.
        vnet["subnets"].reverse()
        assert allocate(vnet, projectNumber=project) == result
    assert all(item in vnet["subnets"] for item in original)
    assert not ipaddress.ip_network("172.31.240.0/24").overlaps(ipaddress.ip_network("10.113.0.0/18"))


@pytest.mark.parametrize("environment", ["dev", "test", "stage", "prod"])
@pytest.mark.parametrize("azure", ["cli", "az", "ado-cli"])
def test_environment_and_provider_paths(environment, azure):
    vnet = integrated_inventory()
    result = allocate(vnet, env=environment, azure=azure)
    assert_disjoint(vnet, result)
    assert sorted(ipaddress.ip_network(cidr).prefixlen for cidr in result.values()) == [
        23, 23, 24, 25, 26, 26, 26, 27,
    ]


def test_gaps_before_between_and_after_numeric_sorted_reservations():
    vnet = inventory(subnets=[
        subnet("late", "10.113.10.0/24"), subnet("early", "10.113.0.32/27"),
        subnet("middle", "10.113.2.0/23"), subnet("GatewaySubnet", "10.113.63.224/27"),
    ])
    result = allocate(vnet)
    assert result["acaSubnetCidr"] == "10.113.4.0/23"
    assert result["aca2SubnetCidr"] == "10.113.6.0/23"
    assert result["aks2SubnetCidr"] == "10.113.1.0/24"
    assert result["webappSubnetCidr"] == "10.113.0.0/27"
    assert_disjoint(vnet, result)
    vnet["subnets"].reverse()
    assert allocate(vnet) == result


def test_existing_partial_project_keeps_nondefault_prefix_and_adds_only_missing():
    vnet = integrated_inventory()
    vnet["subnets"] += [
        subnet("SNT-PRJ001-ACA", "10.113.16.0/24"),
        subnet("snt-prj001-genai", "10.113.18.0/26"),
    ]
    result = allocate(vnet)
    assert result["acaSubnetCidr"] == "10.113.16.0/24"
    assert result["genaiSubnetCidr"] == "10.113.18.0/26"
    missing = {key: value for key, value in result.items() if key not in ("acaSubnetCidr", "genaiSubnetCidr")}
    assert_disjoint(vnet, missing)
    deploy_inventory(vnet, missing)
    assert allocate(vnet, acaSubnetCidrAll="22", genaiSubnetCidrAll="24") == result


@pytest.mark.parametrize("prefix,expected", [(18, 9), (20, 2)])
def test_aligned_gap_capacity_and_exhaustion(prefix, expected):
    network = ipaddress.ip_network(f"172.16.0.0/{prefix}")
    vnet = inventory((str(network),), [
        *(subnet(f"common-{i}", f"172.16.0.{i * 64}/26") for i in range(4)),
        subnet("GatewaySubnet", str(list(network.subnets(new_prefix=27))[-1])),
    ])
    for index in range(expected):
        result = allocate(vnet, projectNumber=f"{index + 1:03}")
        assert_disjoint(vnet, result)
        deploy_inventory(vnet, result, f"{index + 1:03}")
    run, data = invoke_allocator(vnet, projectNumber=f"{expected + 1:03}")
    assert run.returncode != 0 and data is None
    assert "No aligned free" in run.stderr
    # An update still succeeds when no complete new project fits.
    assert len(allocate(vnet)) == 8


def test_fragmentation_fails_without_partial_parameters():
    vnet = inventory(("10.113.0.0/20",), [
        subnet(f"fragment-{i}", f"10.113.{i}.0/24") for i in range(0, 16, 2)
    ])
    run, data = invoke_allocator(vnet)
    assert run.returncode != 0 and data is None
    assert "No aligned free /23" in run.stderr


def test_exhaustion_after_first_assignment_never_emits_partial_parameters():
    run, data = invoke_allocator(inventory(("10.113.0.0/23",)))
    assert run.returncode != 0 and data is None
    assert "aca2SubnetCidr" in run.stderr and "No aligned free /23" in run.stderr


def test_multiple_vnet_and_subnet_prefixes_and_boundary():
    vnet = inventory(("255.255.248.0/21", "10.113.0.0/24"), [
        {"name": "multi", "addressPrefixes": ["10.113.0.0/24", "255.255.248.0/26"]},
        subnet("GatewaySubnet", "255.255.255.224/27"),
    ])
    result = allocate(vnet)
    assert_disjoint(vnet, result)
    assert all(value.startswith("255.") for value in result.values())
    vnet["addressSpace"]["addressPrefixes"].reverse()
    assert allocate(vnet) == result


def test_empty_vnet_and_json_project_identity_with_inline_precedence():
    vnet = inventory(subnets=[subnet("snt-prj002-genai", "10.113.18.0/26")])
    result = allocate(vnet, json_project="002", projectNumber=None)
    assert result["genaiSubnetCidr"] == "10.113.18.0/26"
    result = allocate(vnet, json_project="002", projectNumber="001")
    assert result["genaiSubnetCidr"] != "10.113.18.0/26"
    assert len(allocate(inventory())) == 8
    result = allocate(inventory(), vnetNameFull_param="custom-vnet", vnetResourceGroup_param="custom-rg")
    assert len(result) == 8


def test_json_parameter_precedence_and_required_ado_location():
    run, data = invoke_allocator(inventory(), location=None, json_parameters={
        1: {"location": "westeurope", "acaSubnetCidrAll": "24"},
        5: {"location": "eastus", "acaSubnetCidrAll": "25"},
    })
    assert run.returncode == 0, run.stdout + run.stderr
    assert data["parameters"]["location"]["value"] == "swedencentral"
    assert data["parameters"]["acaSubnetCidr"]["value"].endswith("/25")
    result = allocate(inventory(), json_parameters={1: {"acaSubnetCidrAll": "24"}},
                      acaSubnetCidrAll="23")
    assert result["acaSubnetCidr"].endswith("/23")


@pytest.mark.parametrize("kind,expected", [
    ("misaligned", "not network-aligned"), ("malformed", "Invalid IPv4 CIDR"),
    ("ipv6", "IPv6 allocation is not supported"), ("outside", "outside the VNet"),
    ("overlap", "prefixes overlap"), ("missing-prefix", "has no address prefixes"),
    ("missing-inventory", "inventory is missing"), ("duplicate-name", "duplicate subnet name"),
    ("overlapping-vnet", "VNet address prefixes overlap"),
    ("project-multiple", "Bicep addressPrefix parameter requires one"),
    ("blank-member", "invalid IPv4 CIDR"), ("null-member", "invalid IPv4 CIDR"),
    ("null-vnet", "vnetObj"),
])
def test_invalid_inventory_is_not_silently_ignored(kind, expected):
    vnet = inventory()
    if kind == "misaligned":
        vnet["subnets"] = [subnet("bad", "10.113.0.1/26")]
    elif kind == "malformed":
        vnet["subnets"] = [subnet("bad", "10.113.0.999/26")]
    elif kind == "ipv6":
        vnet["addressSpace"]["addressPrefixes"].append("fd00::/48")
    elif kind == "outside":
        vnet["subnets"] = [subnet("bad", "10.114.0.0/24")]
    elif kind == "overlap":
        vnet["subnets"] = [subnet("a", "10.113.0.0/24"), subnet("b", "10.113.0.0/26")]
    elif kind == "missing-prefix":
        vnet["subnets"] = [{"name": "bad"}]
    elif kind == "missing-inventory":
        del vnet["subnets"]
    elif kind == "duplicate-name":
        vnet["subnets"] = [subnet("same", "10.113.0.0/24"), subnet("SAME", "10.113.1.0/24")]
    elif kind == "overlapping-vnet":
        vnet["addressSpace"]["addressPrefixes"].append("10.113.0.0/24")
    elif kind == "project-multiple":
        vnet["subnets"] = [{"name": "snt-prj001-aks", "addressPrefixes": ["10.113.0.0/26", "10.113.1.0/26"]}]
    elif kind in ("blank-member", "null-member"):
        vnet["subnets"] = [{"name": "bad", "addressPrefixes": [
            "10.113.0.0/26", "" if kind == "blank-member" else None,
        ]}]
    elif kind == "null-vnet":
        vnet = None
    run, data = invoke_allocator(vnet)
    assert run.returncode != 0 and data is None
    assert expected in run.stderr


@pytest.mark.parametrize("parameters,expected", [
    ({"acaSubnetCidrAll": "bad"}, "Invalid subnet mask"),
    ({"acaSubnetCidrAll": "33"}, "Invalid subnet mask"),
    ({"projectNumber": None}, "projectNumber"),
    ({"projectTypeADO": "unknown"}, "Unsupported projectTypeADO"),
    ({"azure": "wrong-context"}, "No authenticated Azure context"),
    ({"azure": "cli-error"}, "Unable to read VNet"),
    ({"bicepPar1": "incomplete-parameters.json"}, "Supply all five JSON parameter files"),
])
def test_invalid_inputs_fail_closed(parameters, expected):
    run, data = invoke_allocator(inventory(), **parameters)
    assert run.returncode != 0 and data is None
    assert expected in run.stderr


@pytest.mark.parametrize("project_type,keys", [
    ("esml", {"aksSubnetCidr", "dbxPubSubnetCidr", "dbxPrivSubnetCidr"}),
    ("genai-1", {"aksSubnetCidr", "genaiSubnetCidr", "acaSubnetCidr", "webappSubnetCidr"}),
])
def test_supported_project_profiles(project_type, keys):
    vnet = integrated_inventory()
    result = allocate(vnet, projectTypeADO=project_type)
    assert result.keys() == keys
    assert_disjoint(vnet, result)


def test_canonical_pipeline_callers_supply_project_identity():
    template = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
    gha = (template / "github-actions/infra-project-phase.yml").read_text(encoding="utf-8")
    ado = (template / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-1-genai-networking.yaml").read_text(encoding="utf-8")
    assert '-projectNumber "${{ env.project_number_000 }}"' in gha.split('& "./subnetCalc_v2.ps1"', 1)[1].split('Write-Host ""', 1)[0]
    assert '-projectNumber "$(project_number_000)"' in ado.split("displayName: '04_pwsh_calculate_subnet_allocations'", 1)[1].split("- task:", 1)[0]


def test_bootstrap_distribution_uses_canonical_workflows_and_allocator():
    github = (ROOT / "bootstrap/03a-GH-bootstrap-files-no-env-overwrite.sh").read_text(encoding="utf-8")
    ado = (ROOT / "bootstrap/03b-ADO-YAML-bootstrap-files-no-var-overwrite.sh").read_text(encoding="utf-8")
    full = (ROOT / "bootstrap/lib/create-new-aifactory-scaleset.sh").read_text(encoding="utf-8")
    phase = "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml"
    job_tree = "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/."
    assert phase in github and phase in full
    assert job_tree in ado
    template = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
    github_phase = (template / "github-actions/infra-project-phase.yml").read_text(encoding="utf-8")
    ado_job = (template / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-1-genai-networking.yaml").read_text(encoding="utf-8")
    assert "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts" in github_phase
    assert "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1" in ado_job


def test_project_identity_matches_bicep_creation_and_existing_subnet_guards():
    bicep = (ROOT / "environment_setup/aifactory/bicep/esml-genai-1/31-network.bicep").read_text(encoding="utf-8")
    assert "var projectName = 'prj${projectNumber}'" in bicep
    for suffix in SUFFIXES.values():
        assert "name: 'snt-${projectName}-" + suffix + "'" in bicep
    for flag in ("sntGenaiExists", "sntAcaExists", "sntAca002Exists", "sntWebappExists",
                 "sntAksExists", "sntAks002Exists", "sntDatabricksPrivExists", "sntDatabricksPubExists"):
        assert f"!{flag}" in bicep


def test_missing_deployment_output_never_recommends_destructive_recovery():
    source = (ALLOCATOR.parent / "genDynamicNetworkParamFile.ps1").read_text(encoding="utf-8")
    failure = source.split("if ([string]::IsNullOrEmpty($aksSubnetId)) {", 1)[1].split("exit 1", 1)[0]
    assert "Do not delete or renumber existing subnets" in failure
    assert "Please delete" not in failure and "MISSING_REQUIRED_SUBNET_ID" not in failure
