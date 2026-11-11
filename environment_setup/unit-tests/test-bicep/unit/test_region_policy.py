"""Region policy kit: AI Search in three regions, everything else in Sweden Central.

The kit (copy_to_local_settings/automation/coreteam/governance/region-policy) is copied into every
consumer repo by the template copy. These offline tests check the real policy JSON with a small rule
evaluator, and run the create and remove scripts in pwsh against a stand-in `az` function that logs
every call. No Azure login is needed.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from base.policy_rule import is_denied

ROOT = Path(__file__).resolve().parents[4]
KIT = (ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings" / "automation"
       / "coreteam" / "governance" / "region-policy")
POLICIES = KIT / "policies"
NEW = KIT / "New-EsafRegionPolicy.ps1"
REMOVE = KIT / "Remove-EsafRegionPolicy.ps1"
MODULE = KIT / "EsafRegionPolicy.psm1"

SUB = "11111111-2222-3333-4444-555555555555"
TENANT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OTHER_TENANT = "99999999-8888-7777-6666-555555555555"
MARKER = {"createdBy": "esaf-region-policy", "version": "1.0.0"}
DEFINITIONS = ["esaf-allowed-locations-except-types", "esaf-allowed-locations-for-types",
               "esaf-allowed-locations-resource-groups"]
SEARCH = "Microsoft.Search/searchServices"
SET_VALUES = {
    "baselineLocations": ["swedencentral"],
    "multiRegionResourceTypes": [SEARCH],
    "multiRegionLocations": ["swedencentral", "francecentral", "italynorth"],
    "effect": "Deny",
}


# ---------------------------------------------------------------- rule matrix on the real JSON

def load(name: str) -> dict:
    return json.loads((POLICIES / name).read_text(encoding="utf-8"))


def denied(resource_type: str, location: str, include_resource_groups: bool = True) -> bool:
    policy_set = load("esaf-region-policy.policyset.json")["properties"]
    for reference in policy_set["policyDefinitions"]:
        if reference["policyDefinitionReferenceId"] == "resourceGroupLocations" and not include_resource_groups:
            continue
        name = reference["policyDefinitionId"].rsplit("/", 1)[-1]
        definition = load(f"{name}.json")
        values = {key: SET_VALUES[re.match(r"^\[parameters\('([^']+)'\)\]$", spec["value"]).group(1)]
                  for key, spec in reference.get("parameters", {}).items()}
        if is_denied(definition, {"type": resource_type, "location": location}, values):
            return True
    return False


@pytest.mark.parametrize("resource_type,location,expected_denied", [
    (SEARCH, "swedencentral", False),
    (SEARCH, "francecentral", False),
    (SEARCH, "italynorth", False),
    (SEARCH, "westeurope", True),
    (SEARCH, "norwayeast", True),
    ("Microsoft.Storage/storageAccounts", "swedencentral", False),
    ("Microsoft.Storage/storageAccounts", "francecentral", True),
    ("Microsoft.Storage/storageAccounts", "italynorth", True),
    ("Microsoft.KeyVault/vaults", "westeurope", True),
    ("Microsoft.Network/virtualNetworks", "swedencentral", False),
    ("Microsoft.Network/virtualNetworks", "italynorth", True),
    ("Microsoft.Network/privateDnsZones", "global", False),
    ("Microsoft.Resources/subscriptions/resourceGroups", "swedencentral", False),
    ("Microsoft.Resources/subscriptions/resourceGroups", "francecentral", True),
    ("MICROSOFT.SEARCH/searchservices", "FranceCentral", False),
    ("microsoft.storage/STORAGEACCOUNTS", "SwedenCentral", False),
])
def test_ai_search_may_use_three_regions_and_everything_else_only_sweden_central(resource_type, location, expected_denied):
    assert denied(resource_type, location) is expected_denied


def test_resource_groups_are_free_when_their_rule_is_left_out():
    assert denied("Microsoft.Resources/subscriptions/resourceGroups", "francecentral",
                  include_resource_groups=False) is False


def test_definition_modes_cover_resource_groups_only_where_intended():
    modes = {name: load(f"{name}.json")["properties"]["mode"] for name in DEFINITIONS}
    assert modes == {"esaf-allowed-locations-except-types": "Indexed",
                     "esaf-allowed-locations-for-types": "Indexed",
                     "esaf-allowed-locations-resource-groups": "All"}


# ---------------------------------------------------------------- scripts against a stand-in az

FAKE_AZ = r"""
$global:FakeState = Get-Content -Raw -LiteralPath $env:FAKE_AZ_STATE | ConvertFrom-Json -AsHashtable
function global:az {
    $a = @($args | ForEach-Object { [string]$_ })
    $files = @{}
    foreach ($x in $a) {
        if ($x.StartsWith('@') -and (Test-Path -LiteralPath $x.Substring(1))) {
            $files[$x] = Get-Content -Raw -LiteralPath $x.Substring(1)
        }
    }
    Add-Content -LiteralPath $env:FAKE_AZ_LOG -Value (@{ args = $a; files = $files } | ConvertTo-Json -Compress -Depth 40)
    $global:LASTEXITCODE = 0
    if ($a[0] -eq 'account' -and $a[1] -eq 'show') {
        return (@{ id = 'sub'; tenantId = $FakeState.tenantId } | ConvertTo-Json)
    }
    if ($a -contains 'show') {
        $i = [array]::IndexOf($a, '--name')
        $key = "$($a[1])/$($a[$i + 1])"
        if ($FakeState.existing.ContainsKey($key)) { return ($FakeState.existing[$key] | ConvertTo-Json -Depth 20) }
        $global:LASTEXITCODE = 3
        Write-Error "(NotFound) '$($a[$i + 1])' could not be found." -ErrorAction Continue
        return
    }
    return '{}'
}
"""


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run(script: Path, tmp_path: Path, *params: str, tenant: str = TENANT, existing: dict | None = None):
    pwsh = shutil.which("pwsh")
    assert pwsh, "PowerShell 7 (pwsh) is required for these offline contracts"
    state = tmp_path / "state.json"
    log = tmp_path / "az.log"
    state.write_text(json.dumps({"tenantId": tenant, "existing": existing or {}}), encoding="utf-8")
    log.write_text("", encoding="utf-8")
    command = (f"$env:FAKE_AZ_STATE = {ps_quote(str(state))}; $env:FAKE_AZ_LOG = {ps_quote(str(log))}\n"
               + FAKE_AZ + f"\n& {ps_quote(str(script))} " + " ".join(params))
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", timeout=120)
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return result, calls


def ids(*extra: str) -> tuple[str, ...]:
    return ("-TenantId", TENANT, "-SubscriptionId", SUB, *extra)


def writes(calls: list[dict]) -> list[list[str]]:
    return [c["args"] for c in calls if c["args"][-1] != "--help" and c["args"][2] in ("create", "delete")]


def value_after(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def file_json(call: dict, flag: str):
    return json.loads(call["files"][value_after(call["args"], flag)])


def owned_everything() -> dict:
    existing = {f"definition/{name}": {"name": name, "metadata": MARKER} for name in DEFINITIONS}
    existing["set-definition/esaf-region-policy"] = {"name": "esaf-region-policy", "metadata": MARKER}
    existing["assignment/esaf-region-policy"] = {"name": "esaf-region-policy", "metadata": MARKER}
    return existing


def test_kit_has_no_subscription_or_tenant_defaults():
    guid = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    for path in KIT.rglob("*"):
        if path.is_file():
            assert not guid.search(path.read_text(encoding="utf-8")), f"{path.name} contains a GUID"


def test_one_settings_file_splats_into_both_scripts():
    example = (KIT / "region-policy.settings.example.psd1").read_text(encoding="utf-8")
    keys = set(re.findall(r"^\s*#?\s*(\w+)\s*=", example, re.MULTILINE))
    assert {"TenantId", "SubscriptionId", "ManagementGroupId", "AssignmentScope", "AssignmentName"} <= keys
    command = "; ".join(f"(Get-Command {ps_quote(str(s))}).Parameters.Keys -join ','" for s in (NEW, REMOVE))
    result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    for line in result.stdout.split():
        assert keys <= set(line.split(",")), line


@pytest.mark.parametrize("script", [NEW, REMOVE])
def test_subscription_and_tenant_are_required(script, tmp_path):
    result, calls = run(script, tmp_path, "-TenantId", TENANT, "-Force" if script == REMOVE else "")
    assert result.returncode != 0
    assert calls == []


def test_create_builds_definitions_set_and_assignment_with_sweden_central_defaults(tmp_path):
    result, calls = run(NEW, tmp_path, *ids())
    assert result.returncode == 0, result.stderr
    created = [(c["args"][1], value_after(c["args"], "--name")) for c in calls if c["args"][2] == "create"]
    assert created == [("definition", n) for n in DEFINITIONS] + [
        ("set-definition", "esaf-region-policy"), ("assignment", "esaf-region-policy")]
    for call in calls:
        assert value_after(call["args"], "--subscription") == SUB, call["args"]
    modes = [value_after(c["args"], "--mode") for c in calls if c["args"][1:3] == ["definition", "create"]]
    assert modes == ["Indexed", "Indexed", "All"]
    assignment = next(c for c in calls if c["args"][1:3] == ["assignment", "create"])
    assert value_after(assignment["args"], "--scope") == f"/subscriptions/{SUB}"
    assert value_after(assignment["args"], "--enforcement-mode") == "Default"
    assert value_after(assignment["args"], "--policy-set-definition") == (
        f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policySetDefinitions/esaf-region-policy")
    params = file_json(assignment, "--params")
    assert {k: v["value"] for k, v in params.items()} == SET_VALUES
    assert file_json(assignment, "--metadata")["createdBy"] == "esaf-region-policy"
    policy_set = next(c for c in calls if c["args"][1:3] == ["set-definition", "create"])
    references = file_json(policy_set, "--definitions")
    assert [r["policyDefinitionId"] for r in references] == [
        f"/subscriptions/{SUB}/providers/Microsoft.Authorization/policyDefinitions/{n}" for n in DEFINITIONS]


def test_create_without_resource_group_rule_leaves_that_definition_out(tmp_path):
    result, calls = run(NEW, tmp_path, *ids("-RestrictResourceGroupLocation", "$false"))
    assert result.returncode == 0, result.stderr
    names = [value_after(c["args"], "--name") for c in calls if c["args"][1:3] == ["definition", "create"]]
    assert names == DEFINITIONS[:2]
    policy_set = next(c for c in calls if c["args"][1:3] == ["set-definition", "create"])
    assert [r["policyDefinitionReferenceId"] for r in file_json(policy_set, "--definitions")] == [
        "baselineLocations", "multiRegionTypes"]


def test_create_in_audit_mode_and_with_custom_regions(tmp_path):
    result, calls = run(NEW, tmp_path, *ids("-EnforcementMode", "DoNotEnforce", "-MultiRegionLocations",
                                            "swedencentral,westeurope"))
    assert result.returncode == 0, result.stderr
    assignment = next(c for c in calls if c["args"][1:3] == ["assignment", "create"])
    assert value_after(assignment["args"], "--enforcement-mode") == "DoNotEnforce"
    assert file_json(assignment, "--params")["multiRegionLocations"]["value"] == ["swedencentral", "westeurope"]


def test_management_group_stores_definitions_there(tmp_path):
    result, calls = run(NEW, tmp_path, *ids("-ManagementGroupId", "mg-esaf"))
    assert result.returncode == 0, result.stderr
    for call in calls:
        if call["args"][1] in ("definition", "set-definition"):
            assert value_after(call["args"], "--management-group") == "mg-esaf"
    assignment = next(c for c in calls if c["args"][1:3] == ["assignment", "create"])
    assert value_after(assignment["args"], "--policy-set-definition").startswith(
        "/providers/Microsoft.Management/managementGroups/mg-esaf/")


def test_create_runs_again_over_its_own_objects(tmp_path):
    result, calls = run(NEW, tmp_path, *ids(), existing=owned_everything())
    assert result.returncode == 0, result.stderr
    assert len(writes(calls)) == 5


def test_create_refuses_to_overwrite_a_foreign_object_before_any_write(tmp_path):
    existing = {"definition/esaf-allowed-locations-for-types": {"name": "x", "metadata": {"createdBy": "someone"}}}
    result, calls = run(NEW, tmp_path, *ids(), existing=existing)
    assert result.returncode != 0
    assert "esaf-allowed-locations-for-types" in result.stderr + result.stdout
    assert writes(calls) == []


@pytest.mark.parametrize("script", [NEW, REMOVE])
def test_wrong_tenant_stops_before_any_write(script, tmp_path):
    result, calls = run(script, tmp_path, *ids("-Force" if script == REMOVE else ""),
                        tenant=OTHER_TENANT, existing=owned_everything())
    assert result.returncode != 0
    assert writes(calls) == []
    assert TENANT in result.stderr + result.stdout


@pytest.mark.parametrize("script", [NEW, REMOVE])
def test_what_if_writes_nothing(script, tmp_path):
    result, calls = run(script, tmp_path, *ids("-WhatIf"), existing=owned_everything())
    assert result.returncode == 0, result.stderr
    assert writes(calls) == []


def test_remove_deletes_assignment_then_set_then_definitions(tmp_path):
    result, calls = run(REMOVE, tmp_path, *ids("-Force"), existing=owned_everything())
    assert result.returncode == 0, result.stderr
    deleted = [(c[1], value_after(c, "--name")) for c in writes(calls)]
    assert deleted == [("assignment", "esaf-region-policy"), ("set-definition", "esaf-region-policy")] + [
        ("definition", n) for n in DEFINITIONS]
    for call in calls:
        assert value_after(call["args"], "--subscription") == SUB, call["args"]
    assignment = next(c for c in writes(calls) if c[1] == "assignment")
    assert value_after(assignment, "--scope") == f"/subscriptions/{SUB}"


def test_remove_keep_definitions_only_removes_the_assignment(tmp_path):
    result, calls = run(REMOVE, tmp_path, *ids("-Force", "-KeepDefinitions"), existing=owned_everything())
    assert result.returncode == 0, result.stderr
    assert [(c[1], c[2]) for c in writes(calls)] == [("assignment", "delete")]


def test_remove_skips_objects_it_did_not_create(tmp_path):
    existing = owned_everything()
    existing["set-definition/esaf-region-policy"] = {"name": "esaf-region-policy", "metadata": {"createdBy": "x"}}
    result, calls = run(REMOVE, tmp_path, *ids("-Force"), existing=existing)
    assert result.returncode == 0, result.stderr
    assert "set-definition" not in [c[1] for c in writes(calls)]
    assert "skipped" in result.stdout.lower()


def test_remove_with_nothing_there_is_a_no_op(tmp_path):
    result, calls = run(REMOVE, tmp_path, *ids("-Force"))
    assert result.returncode == 0, result.stderr
    assert writes(calls) == []
    assert "not found" in result.stdout.lower()
