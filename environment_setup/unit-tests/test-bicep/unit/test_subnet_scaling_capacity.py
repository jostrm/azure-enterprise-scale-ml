"""Offline capacity checks: real allocator functions, no Azure/module imports."""

import ipaddress
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
ALLOCATOR = ROOT / "environment_setup/aifactory/bicep/scripts/subnetCalc_v2.ps1"


@pytest.fixture(scope="module")
def allocation_results():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell is required for offline allocator checks.")
    # Load definitions only; never execute Import-Dependencies or the Azure calls.
    # Get-Subnet is the external Subnet module's IPv4 arithmetic primitive.
    code = r"""
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '__ALLOCATOR__', [ref]$null, [ref]$null)
$ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false) | ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }
function Get-Subnet {
    param([string]$IPAddress, [int]$MaskBits)
    $bytes = [System.Net.IPAddress]::Parse($IPAddress).GetAddressBytes()
    [array]::Reverse($bytes)
    $number = [BitConverter]::ToUInt32($bytes, 0)
    $size = [math]::Pow(2, 32 - $MaskBits)
    $first = [uint32]([math]::Floor($number / $size) * $size)
    $last = [uint32]($first + $size - 1)
    [pscustomobject]@{
        NetworkAddress = ConvertTo-DottedDecimalIP "$first"
        BroadcastAddress = ConvertTo-DottedDecimalIP "$last"
    }
}
$required = @{}
foreach ($parameter in $ast.ParamBlock.Parameters) {
    $name = $parameter.Name.VariablePath.UserPath
    if ($name -like '*SubnetCidrAll') {
        $required[$name -replace 'All$',''] = $parameter.DefaultValue.SafeGetValue()
    }
}
$results = foreach ($case in @(
    @{prefix=18;octet=0}, @{prefix=18;octet=15},
    @{prefix=18;octet=20}, @{prefix=18;octet=25},
    @{prefix=20;octet=0}, @{prefix=20;octet=0;gateway=$true}
)) {
    $vnet = "172.16.0.0/$($case.prefix)"
    $subnets = @(0,64,128,192 | ForEach-Object {
        [pscustomobject]@{AddressPrefix="172.16.$($case.octet).$_/26"}
    })
    if ($case.gateway) {
        $subnets += [pscustomobject]@{AddressPrefix='172.16.15.224/27'}
    }
    $possible = @{}
    $required.Values | Select-Object -Unique | ForEach-Object {
        $possible[$_] = Get-SubnetFitting -addressSpace $vnet -cidrNotation $_
    }
    $profiles = @()
    $partialCount = 0
    for ($project = 1; $project -le 10; $project++) {
        $lastNetwork, $lastMask = @($subnets | Sort-Object {
            $_.AddressPrefix.split("/")[0] -as [Version]
        } -Bottom 1)[0].AddressPrefix.split("/")
        $start = Find-NextIpAddress (Get-Subnet $lastNetwork -MaskBits $lastMask).BroadcastAddress.IPAddressToString
        $result = New-SubnetScheme -map $required -startIp $start -possibleValuesMap $possible 6>$null
        if ($result.Count -ne $required.Count) {
            $partialCount = $result.Count
            break
        }
        $profiles += ,$result
        $subnets += @($result.Values | ForEach-Object {
            [pscustomobject]@{AddressPrefix=$_}
        })
    }
    [pscustomobject]@{
        prefix=$case.prefix;octet=$case.octet;gateway=[bool]$case.gateway;profiles=$profiles;
        partialCount=$partialCount;subnets=@($subnets.AddressPrefix)
    }
}
ConvertTo-Json -InputObject @($results) -Depth 6 -Compress
""".replace("__ALLOCATOR__", str(ALLOCATOR).replace("'", "''"))
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    return {(item["prefix"], item["octet"], item["gateway"]): item
            for item in json.loads(result.stdout)}


@pytest.mark.parametrize("prefix,octet,full_profiles", [
    (18, 0, 7), (18, 15, 6), (18, 20, 5), (18, 25, 4), (20, 0, 1),
])
def test_append_only_allocator_capacity(allocation_results, prefix, octet, full_profiles):
    result = allocation_results[prefix, octet, False]
    assert len(result["profiles"]) == full_profiles
    assert result["partialCount"] < 8
    vnet = ipaddress.ip_network(f"172.16.0.0/{prefix}")
    subnets = [ipaddress.ip_network(cidr) for cidr in result["subnets"]]
    assert all(subnet.subnet_of(vnet) for subnet in subnets)
    assert not any(a.overlaps(b) for index, a in enumerate(subnets) for b in subnets[index + 1:])
    for profile in result["profiles"]:
        assert sorted(ipaddress.ip_network(cidr).prefixlen for cidr in profile.values()) == [
            23, 23, 24, 25, 26, 26, 26, 27,
        ]
        assert sum(ipaddress.ip_network(cidr).num_addresses for cidr in profile.values()) == 1632


def test_address_budget_is_not_an_allocator_capacity_guarantee():
    project = 2 * 512 + 256 + 128 + 3 * 64 + 32
    common = 4 * 64
    assert (2**14 - common) // project == 9
    assert common + 10 * project == 16576 > 2**14
    assert (common + project) * 2 == 3776 <= 2**12
    assert (common + project - 32) * 2 == 3712 <= 2**12


def test_integrated_gateway_at_vnet_end_blocks_append_only_allocator(allocation_results):
    result = allocation_results[20, 0, True]
    assert result["profiles"] == []
    assert result["partialCount"] == 0
    assert "172.16.15.224/27" in result["subnets"]
    assert sum(ipaddress.ip_network(cidr).num_addresses for cidr in result["subnets"]) == 288
