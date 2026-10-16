"""Offline subnet-task authentication/dependency regressions; never contact Azure."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts"
ALLOCATOR = SCRIPTS / "subnetCalc_v2.ps1"
DEPENDENCIES = SCRIPTS / "modules" / "pipelineFunctions.psm1"
ADO = SCRIPTS.parent / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines"
JOB = ADO / "esml-infra-project" / "jobs" / "job-1-genai-networking.yaml"
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"


def run_powershell(tmp_path, code, *, cli=False, github=False):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is required for offline subnet checks")
    harness = tmp_path / "harness.ps1"
    harness.write_text(code, encoding="utf-8")
    return subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(harness)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        env={**os.environ, "AIFACTORY_USE_AZURE_CLI": str(cli).lower(),
             "GITHUB_ACTIONS": str(github).lower()},
    )


@pytest.mark.parametrize("cli,github", [(True, False), (False, True), (False, False)])
def test_dependency_imports_do_not_mix_az_modules_in_cli_mode(tmp_path, cli, github):
    code = r"""
$ErrorActionPreference = 'Stop'
$script:imports = [System.Collections.Generic.List[string]]::new()
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '__DEPENDENCIES__', [ref]$null, [ref]$null)
$ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false) | ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }
function Get-PSCallStack {
    @([pscustomobject]@{Command='Import-Dependencies'},
      [pscustomobject]@{Command='subnetCalc_v2.ps1'})
}
function Get-Module {
    param([string]$Name, [switch]$ListAvailable)
    if (-not $ListAvailable) { return }
    $versions = @{ 'Az.Accounts'='5.3.4'; 'Az.Resources'='4.3.0';
                   'Az.Network'='4.10.0'; 'Subnet'='1.0.6' }
    [pscustomobject]@{Name=$Name; Version=[version]$versions[$Name]; ModuleBase='offline'}
}
function Install-Module { throw 'No dependency installation is permitted in this regression' }
function Import-Module {
    param([string]$Name, [string]$RequiredVersion, [switch]$Force)
    $script:imports.Add($Name)
}
Import-Dependencies
ConvertTo-Json -InputObject @($script:imports) -Compress
""".replace("__DEPENDENCIES__", str(DEPENDENCIES).replace("'", "''"))
    result = run_powershell(tmp_path, code, cli=cli, github=github)
    assert result.returncode == 0, result.stderr
    imports = json.loads(result.stdout)
    assert imports == (["Subnet"] if cli or github else
                       ["Az.Accounts", "Az.Resources", "Az.Network", "Subnet"])


@pytest.fixture
def allocator_harness(tmp_path):
    output = tmp_path / "parameters"
    code = r"""
$ErrorActionPreference = 'Stop'
function Import-Module { param([string]$Name) }
function Import-Dependencies {}
function Get-Subnet {
    param([string]$IPAddress, [int]$MaskBits)
    $bytes = [System.Net.IPAddress]::Parse($IPAddress).GetAddressBytes()
    [array]::Reverse($bytes)
    $number = [BitConverter]::ToUInt32($bytes, 0)
    $size = [math]::Pow(2, 32 - $MaskBits)
    $first = [uint32]([math]::Floor($number / $size) * $size)
    [pscustomobject]@{
        NetworkAddress = ConvertTo-DottedDecimalIP "$first"
        BroadcastAddress = ConvertTo-DottedDecimalIP "$([uint32]($first + $size - 1))"
    }
}
$global:subnetTestVnet = @{
    id='/subscriptions/__SUBSCRIPTION__/resourceGroups/fixture-esml-common-swe-dev-002/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-swe-dev-001'
    addressSpace=@{addressPrefixes=@('172.16.0.0/18')}
    subnets=@(0,64,128,192 | ForEach-Object { @{addressPrefix="172.16.0.$_/26"} })
}
$global:subnetTestCliCalls = @()
$global:subnetTestAzCalls = 0
function az {
    $global:subnetTestCliCalls += ,@($args)
    $global:LASTEXITCODE = __CLI_EXIT__
    '__CLI_JSON__'
}
function Get-AzContext {
    if ($env:AIFACTORY_USE_AZURE_CLI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true') {
        throw 'CLI mode must not load Az.Accounts'
    }
    [pscustomobject]@{Subscription='__SUBSCRIPTION__'; Account='offline'}
}
function Get-AzVirtualNetwork {
    param([string]$ResourceGroupName, [string]$Name)
    if ($env:AIFACTORY_USE_AZURE_CLI -eq 'true' -or $env:GITHUB_ACTIONS -eq 'true') {
        throw 'Assembly with same name is already loaded'
    }
    $global:subnetTestAzCalls++
    $global:subnetTestVnet
}
$parameters = @{
    filePath='__OUTPUT__'; env='dev'; subscriptionId='__SUBSCRIPTION__'
    prjResourceSuffix='-001'; aifactorySuffixRGADO='-002'; commonResourceSuffixADO='-001'
    locationADO='swedencentral'; locationSuffixADO='swe'; projectTypeADO='all'
    commonRGNamePrefixVar='fixture-'; vnetNameBase='vnt-esmlcmn'
    vnetResourceGroupBase='esml-common'
}
& '__ALLOCATOR__' @parameters
ConvertTo-Json -InputObject @{cliCalls=$global:subnetTestCliCalls; azCalls=$global:subnetTestAzCalls} -Depth 5 -Compress
"""
    vnet = {
        "id": f"/subscriptions/{SUBSCRIPTION}/resourceGroups/fixture-esml-common-swe-dev-002/providers/Microsoft.Network/virtualNetworks/vnt-esmlcmn-swe-dev-001",
        "addressSpace": {"addressPrefixes": ["172.16.0.0/18"]},
        "subnets": [{"addressPrefix": f"172.16.0.{octet}/26"} for octet in (0, 64, 128, 192)],
    }

    def harness(*, cli_exit=0, cli_json=None):
        return (code.replace("__ALLOCATOR__", str(ALLOCATOR).replace("'", "''"))
                .replace("__OUTPUT__", str(output).replace("'", "''"))
                .replace("__SUBSCRIPTION__", SUBSCRIPTION)
                .replace("__CLI_EXIT__", str(cli_exit))
                .replace("__CLI_JSON__", (json.dumps(vnet) if cli_json is None else cli_json).replace("'", "''")))

    return harness, output


@pytest.mark.parametrize("cli,github", [(True, False), (False, True), (False, False)])
def test_full_allocator_retains_output_and_uses_selected_read_context(tmp_path, allocator_harness, cli, github):
    harness, output = allocator_harness
    result = run_powershell(tmp_path, harness(), cli=cli, github=github)
    assert result.returncode == 0, result.stderr
    values = json.loads((output / "subnetParameters.json").read_text(encoding="utf-8-sig"))["parameters"]
    assert values["vnetResourceGroup"]["value"] == "fixture-esml-common-swe-dev-002"
    assert values["commonResourceSuffix"]["value"] == "-001"
    cidrs = {key: item["value"] for key, item in values.items() if key.endswith("SubnetCidr")}
    assert len(cidrs) == 8 and all(value for value in cidrs.values())
    assert sorted(int(value.split("/")[1]) for value in cidrs.values()) == [23, 23, 24, 25, 26, 26, 26, 27]
    calls = json.loads(result.stdout.splitlines()[-1])
    if cli or github:
        assert calls["azCalls"] == 0
        assert calls["cliCalls"] == [[
            "network", "vnet", "show", "--subscription", SUBSCRIPTION,
            "--resource-group", "fixture-esml-common-swe-dev-002",
            "--name", "vnt-esmlcmn-swe-dev-001", "--only-show-errors", "--output", "json",
        ]]
    else:
        assert calls["azCalls"] == 1 and calls["cliCalls"] == []


@pytest.mark.parametrize("exit_code,response", [(1, "AuthorizationFailed"), (0, "not valid JSON")])
def test_failed_cli_reads_stop_without_writing_allocation_parameters(tmp_path, allocator_harness, exit_code, response):
    harness, output = allocator_harness
    result = run_powershell(tmp_path, harness(cli_exit=exit_code, cli_json=response), cli=True)
    assert result.returncode != 0
    assert not (output / "subnetParameters.json").exists()
    assert "Assembly with same name" not in result.stderr


def test_cli_mode_rejects_mixing_az_service_principal_authentication(tmp_path, allocator_harness):
    harness, output = allocator_harness
    code = harness().replace("@parameters\n", "@parameters -useServicePrincipal\n")
    result = run_powershell(tmp_path, code, cli=True)
    assert result.returncode != 0
    assert "already authenticated CLI context" in result.stderr
    assert not (output / "subnetParameters.json").exists()


def test_ado_task_uses_authenticated_cli_and_preserves_all_arguments():
    steps = yaml.safe_load(JOB.read_text(encoding="utf-8"))["steps"]
    step = next(item for item in steps if item.get("displayName") == "04_pwsh_calculate_subnet_allocations")
    assert step["task"] == "AzureCLI@2"
    assert step["env"]["AIFACTORY_USE_AZURE_CLI"] == "true"
    inputs = step["inputs"]
    assert inputs["azureSubscription"] == "${{ parameters.serviceConnection }}"
    assert inputs["scriptType"] == "pscore" and inputs["scriptLocation"] == "scriptPath"
    assert inputs["scriptPath"].endswith("/scripts/subnetCalc_v2.ps1")
    assert "azurePowerShellVersion" not in inputs
    assert "GITHUB_ACTIONS" not in step["env"]
    for argument in (
        '-filePath "../../../../../aifactory/parameters/"',
        '-subscriptionId "$(dev_test_prod_sub_id)"',
        '-projectTypeADO "$(admin_projectType)"',
        '-vnetResourceGroup_param "$(vnetResourceGroup_resolved)"',
        '-vnetNameFull_param "$(vnetNameFull_resolved)"',
    ):
        assert argument in inputs["arguments"]
