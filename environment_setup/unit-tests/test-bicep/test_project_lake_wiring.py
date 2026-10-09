"""Offline contracts and mocked PowerShell execution for project lake onboarding."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from domain.pipeline_contracts import evaluate, load_pipeline, objects

ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup/aifactory/bicep"
CALLER = BICEP / "scripts/Invoke-ProjectLakeAccess.ps1"
RBAC = BICEP / "esml-genai-1/08b-rbac-common-rg.bicep"
ADO = BICEP / (
    "copy_to_local_settings/azure-devops/esml-yaml-pipelines/"
    "esml-infra-project/jobs/job-2-genai-services.yaml"
)
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
MI = "00000000-0000-0000-0000-000000000011"
GROUP = "00000000-0000-0000-0000-000000000012"
USER = "00000000-0000-0000-0000-000000000013"
AML = "00000000-0000-0000-0000-000000000014"
COMPUTE = "00000000-0000-0000-0000-000000000021"
UAMI = "00000000-0000-0000-0000-000000000022"
UAMI_RESOURCE = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/actual-project-rg/"
    "providers/Microsoft.ManagedIdentity/userAssignedIdentities/compute-uami"
)


def contract():
    return {
        "enabled": True,
        "subscriptionId": "00000000-0000-0000-0000-000000000001",
        "tenantId": "00000000-0000-0000-0000-000000000002",
        "storageResourceGroup": "actual-common-rg",
        "projectResourceGroup": "actual-project-rg",
        "storageAccount": "",
        "fileSystem": "lake3",
        "project": "project001",
        "environment": "dev",
        "projectManagedIdentityObjectId": MI,
        "managedIdentityObjectIds": [MI],
        "groupObjectIds": [GROUP],
        "userObjectIds": [USER],
        "readOnlyObjectIds": [AML],
    }


@pytest.fixture
def run_caller():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 is required for offline caller execution")
    work = ROOT / ".test-state" / f"project-lake-wiring-{uuid.uuid4().hex}"
    (work / "scripts").mkdir(parents=True)
    (work / "esml-util").mkdir()
    shutil.copyfile(CALLER, work / "scripts/Invoke-ProjectLakeAccess.ps1")
    (work / "esml-util/25-add-users-to-datalake-acl-rbac.ps1").write_text(
        """param(
        $tenantID, $subscriptionID, $storageAccount, $storageResourceGroup,
        $adlsgen2filesystem, $projectXXX, $environment, $userObjectIds,
        $managedIdentityObjectIds, $readOnlyObjectIds, $projectADGroupObjectId,
        [switch]$Execute, [switch]$LegacyLayout)
        if ($env:MOCK_ACL_FAILURE -eq 'true') { throw 'data-plane authorization failed' }
        $values = @{}
        foreach ($name in $PSBoundParameters.Keys) {
            if ($PSBoundParameters[$name] -is [switch]) {
                $values[$name] = [bool]$PSBoundParameters[$name]
            } else { $values[$name] = $PSBoundParameters[$name] }
        }
        $values | ConvertTo-Json -Compress -Depth 10 | Add-Content $env:MOCK_ACL_LOG
        """,
        encoding="utf-8",
    )
    harness = work / "harness.ps1"
    harness.write_text(
        """
        $ErrorActionPreference = 'Stop'
        function az {
            $arguments = @($args)
            ConvertTo-Json -InputObject $arguments -Compress | Add-Content $env:MOCK_AZ_LOG
            $global:LASTEXITCODE = [int]$env:MOCK_AZ_EXIT
            if ($arguments[0] -eq 'storage') {
                if ($arguments[2] -eq 'list') { return $env:MOCK_STORAGE_LIST }
                if ($arguments[2] -eq 'show') { return $env:MOCK_STORAGE }
            }
            if ($arguments[0] -eq 'resource') {
                if ($arguments[1] -eq 'list') { return $env:MOCK_WORKSPACES }
                if ($arguments[1] -eq 'show') { return $env:MOCK_WORKSPACE }
            }
            if ($arguments[0] -eq 'ml' -and $arguments[1] -eq 'compute' -and $arguments[2] -eq 'list') {
                $global:LASTEXITCODE = [int]$env:MOCK_COMPUTE_EXIT
                return $env:MOCK_COMPUTES
            }
            if ($arguments[0] -eq 'identity' -and $arguments[1] -eq 'show') { return $env:MOCK_UAMI }
            throw 'Unexpected cloud command'
        }
        & (Join-Path $PSScriptRoot 'scripts/Invoke-ProjectLakeAccess.ps1') `
            -ContractPath (Join-Path $PSScriptRoot 'contract.json') `
            -Execute:($env:MOCK_EXECUTE -eq 'true')
        """,
        encoding="utf-8",
    )

    def run(value=None, *, flags=None, accounts=None, execute=False, az_exit=0, acl_failure=False,
            workspaces=None, workspace=None, computes=None, uami=None, compute_exit=0):
        for log in ("az.jsonl", "acl.jsonl"):
            (work / log).unlink(missing_ok=True)
        (work / "contract.json").write_text(json.dumps(value or contract()), encoding="utf-8")
        env = os.environ | {
            "PROJECT_LAKE_CONTRACT_READY": "true",
            "PROJECT_LAKE_ACCESS_ENABLED": "true",
            "PROJECT_LAKE_GATEWAY_ONLY": "false",
            "PROJECT_LAKE_LEGACY_LAYOUT": "false",
            "PROJECT_LAKE_AML_ENABLED": "false",
            "MOCK_STORAGE_LIST": json.dumps(
                accounts if accounts is not None else [{"name": "actualsharedlake", "isHnsEnabled": True}]
            ),
            "MOCK_STORAGE": json.dumps({"name": "actualsharedlake", "isHnsEnabled": True}),
            "MOCK_WORKSPACES": json.dumps(workspaces if workspaces is not None else []),
            "MOCK_WORKSPACE": json.dumps(workspace if workspace is not None else {
                "identity": {"type": "SystemAssigned", "principalId": AML},
            }),
            "MOCK_COMPUTES": json.dumps(computes if computes is not None else []),
            "MOCK_UAMI": json.dumps(uami if uami is not None else {"principalId": UAMI}),
            "MOCK_COMPUTE_EXIT": str(compute_exit),
            "MOCK_AZ_LOG": str(work / "az.jsonl"),
            "MOCK_ACL_LOG": str(work / "acl.jsonl"),
            "MOCK_AZ_EXIT": str(az_exit),
            "MOCK_ACL_FAILURE": str(acl_failure).lower(),
            "MOCK_EXECUTE": str(execute).lower(),
        }
        env.update(flags or {})
        result = subprocess.run(
            [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(harness)],
            env=env, capture_output=True, text=True, timeout=30, check=False, cwd=work,
        )

        def read(log):
            path = work / log
            return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()] if path.exists() else []

        return result, read("az.jsonl"), read("acl.jsonl")

    try:
        yield run
    finally:
        shutil.rmtree(work)


@pytest.mark.parametrize("execute", [False, True])
def test_resolves_actual_lake_and_forwards_every_principal(run_caller, execute):
    result, calls, acl = run_caller(execute=execute)
    assert result.returncode == 0, result.stderr
    assert len(acl) == 1
    assert acl[0]["storageAccount"] == "actualsharedlake"
    assert acl[0]["storageResourceGroup"] == "actual-common-rg"
    assert acl[0]["managedIdentityObjectIds"] == [MI]
    assert acl[0]["projectADGroupObjectId"] == GROUP
    assert acl[0]["userObjectIds"] == [USER]
    assert acl[0]["readOnlyObjectIds"] == [AML]
    assert acl[0]["environment"] == "dev"
    assert acl[0]["Execute"] is execute
    assert acl[0]["LegacyLayout"] is False
    assert all("--subscription" in call for call in calls)
    assert calls[-1][:2] == ["resource", "list"]
    assert calls[-1][calls[-1].index("--resource-group") + 1] == "actual-project-rg"


def test_explicit_account_skips_discovery_and_preserves_legacy_opt_in(run_caller):
    value = contract() | {"storageAccount": "customlake"}
    result, calls, acl = run_caller(value, flags={"PROJECT_LAKE_LEGACY_LAYOUT": "true"})
    assert result.returncode == 0, result.stderr
    assert len(calls) == 2 and calls[0][2] == "show"
    assert "customlake" in calls[0]
    assert acl[0]["storageAccount"] == "customlake"
    assert acl[0]["LegacyLayout"] is True


def test_refreshes_new_workspace_and_compute_identities_without_stale_contract_ids(run_caller):
    result, calls, acl = run_caller(
        contract() | {"readOnlyObjectIds": []},
        flags={"PROJECT_LAKE_AML_ENABLED": "true"},
        workspaces=[{"name": "new-workspace", "kind": "Default"}],
        computes=[{"name": "new-cpu", "identity": {"type": "system_assigned", "principal_id": COMPUTE}}],
        execute=True,
    )
    assert result.returncode == 0, result.stderr
    assert acl[0]["readOnlyObjectIds"] == [AML]
    assert acl[0]["managedIdentityObjectIds"] == [MI, COMPUTE]
    compute_call = next(call for call in calls if call[:3] == ["ml", "compute", "list"])
    assert compute_call[compute_call.index("--workspace-name") + 1] == "new-workspace"
    for call in calls:
        assert "--subscription" in call
        expected_rg = "actual-common-rg" if call[0] == "storage" else "actual-project-rg"
        assert call[call.index("--resource-group") + 1] == expected_rg


@pytest.mark.parametrize("identity", [
    {"type": "user_assigned", "user_assigned_identities": [{"resource_id": UAMI_RESOURCE}]},
    {"type": "UserAssigned", "userAssignedIdentities": {UAMI_RESOURCE: {}}},
])
def test_resolves_referenced_compute_uami_by_resource_id_without_graph(run_caller, identity):
    result, calls, acl = run_caller(
        workspaces=[{"name": "existing-workspace"}],
        computes=[{"name": "uami-cpu", "identity": identity}],
    )
    assert result.returncode == 0, result.stderr
    assert acl[0]["managedIdentityObjectIds"] == [MI, UAMI]
    identity_call = next(call for call in calls if call[:2] == ["identity", "show"])
    assert identity_call[identity_call.index("--ids") + 1] == UAMI_RESOURCE
    assert not any(call[0] == "ad" for call in calls)


def test_current_compute_ids_are_deduplicated_and_workspace_stays_read_only(run_caller):
    result, calls, acl = run_caller(
        workspaces=[{"name": "existing-one"}, {"name": "existing-two"}],
        computes=[
            {"name": "mixed", "identity": {
                "type": "SystemAssigned, UserAssigned", "principalId": COMPUTE,
                "userAssignedIdentities": {UAMI_RESOURCE: {"principalId": MI}},
            }},
            {"name": "attached", "identity": {"type": "None"}},
        ],
    )
    assert result.returncode == 0, result.stderr
    assert acl[0]["managedIdentityObjectIds"] == [MI, COMPUTE]
    assert acl[0]["readOnlyObjectIds"] == [AML]
    assert len([call for call in calls if call[:3] == ["ml", "compute", "list"]]) == 2
    assert not any(call[0] == "identity" for call in calls)


@pytest.mark.parametrize("workspaces", [[], [{"name": "hub-only", "kind": "Hub"}]])
def test_requested_aml_missing_fails_even_when_predeployment_ids_are_empty(run_caller, workspaces):
    result, _, acl = run_caller(
        contract() | {"readOnlyObjectIds": []},
        flags={"PROJECT_LAKE_AML_ENABLED": "true"}, workspaces=workspaces,
    )
    assert result.returncode != 0
    assert "no current AML workspace" in result.stderr
    assert not acl


def test_disabled_aml_does_not_invent_workspace_or_compute_ids(run_caller):
    result, calls, acl = run_caller(contract() | {"readOnlyObjectIds": []}, workspaces=[])
    assert result.returncode == 0, result.stderr
    assert acl[0]["readOnlyObjectIds"] == []
    assert acl[0]["managedIdentityObjectIds"] == [MI]
    assert not any(call[0] == "ml" for call in calls)


@pytest.mark.parametrize("kwargs,message", [
    ({"workspace": {"identity": {"type": "SystemAssigned"}}}, "Missing or invalid"),
    ({"computes": [{"name": "cpu", "identity": {"type": "system_assigned"}}]}, "Missing or invalid"),
    ({"computes": [{"name": "cpu", "identity": {"type": "user_assigned", "user_assigned_identities": []}}]}, "No user-assigned"),
    ({"compute_exit": 7}, "Azure CLI failed"),
    ({"computes": [{"name": "cpu", "identity": {
        "type": "user_assigned", "user_assigned_identities": [{"resource_id": "bad-reference"}],
    }}]}, "Invalid user-assigned"),
])
def test_identity_discovery_failures_prevent_all_acl_writes(run_caller, kwargs, message):
    result, _, acl = run_caller(workspaces=[{"name": "workspace"}], **kwargs)
    assert result.returncode != 0
    assert message in result.stderr
    assert not acl


def test_mi_only_and_multiple_team_groups_are_not_silently_dropped(run_caller):
    result, _, acl = run_caller(contract() | {"groupObjectIds": [], "userObjectIds": []})
    assert result.returncode == 0, result.stderr
    assert acl[0]["managedIdentityObjectIds"] == [MI]
    assert acl[0]["projectADGroupObjectId"] == ""
    second = "00000000-0000-0000-0000-000000000015"
    result, _, acl = run_caller(contract() | {"groupObjectIds": [GROUP, second]})
    assert result.returncode == 0, result.stderr
    assert [item["projectADGroupObjectId"] for item in acl] == [GROUP, second]


@pytest.mark.parametrize("flags", [
    {"PROJECT_LAKE_ACCESS_ENABLED": "false"},
    {"PROJECT_LAKE_GATEWAY_ONLY": "true"},
])
def test_disabled_common_lake_has_no_cloud_calls(run_caller, flags):
    result, calls, acl = run_caller(flags=flags | {"PROJECT_LAKE_CONTRACT_READY": "false"})
    assert result.returncode == 0, result.stderr
    assert not calls and not acl


@pytest.mark.parametrize("flags,message", [
    ({"PROJECT_LAKE_CONTRACT_READY": "$(projectLakeAccessContractReady)"}, "current-run"),
    ({"PROJECT_LAKE_ACCESS_ENABLED": "yes"}, "must be true or false"),
    ({"PROJECT_LAKE_LEGACY_LAYOUT": "yes"}, "must be true or false"),
    ({"PROJECT_LAKE_AML_ENABLED": "yes"}, "must be true or false"),
])
def test_flags_and_stale_outputs_fail_before_cloud_access(run_caller, flags, message):
    result, calls, acl = run_caller(flags=flags)
    assert result.returncode != 0
    assert message in result.stderr
    assert not calls and not acl


@pytest.mark.parametrize("changes", [
    {"projectManagedIdentityObjectId": ""},
    {"projectResourceGroup": ""},
    {"managedIdentityObjectIds": []},
    {"groupObjectIds": ["<todo>"]},
    {"enabled": False},
])
def test_incomplete_principal_contract_fails_before_writes(run_caller, changes):
    result, calls, acl = run_caller(contract() | changes)
    assert result.returncode != 0
    assert not calls and not acl


@pytest.mark.parametrize("accounts", [
    [],
    [{"name": "ordinaryblob", "isHnsEnabled": False}],
    [{"name": "lakeone", "isHnsEnabled": True}, {"name": "laketwo", "isHnsEnabled": True}],
])
def test_missing_or_ambiguous_lake_never_guesses_name(run_caller, accounts):
    result, _, acl = run_caller(accounts=accounts)
    assert result.returncode != 0
    assert "Set datalakeName_param" in result.stderr
    assert not acl


def test_cli_and_acl_failures_are_not_swallowed(run_caller):
    result, _, acl = run_caller(az_exit=7)
    assert result.returncode != 0 and not acl
    result, _, acl = run_caller(acl_failure=True)
    assert result.returncode != 0 and not acl
    assert "Storage Blob Data Owner" in result.stderr


def named_step(path, name):
    matches = [item for item in objects(load_pipeline(path))
               if item.get("name", item.get("displayName")) == name]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.parametrize("path", [ADO, GHA])
def test_both_pipelines_use_current_outputs_same_identity_and_fail_closed(path):
    rbac = named_step(path, "101-rbac-common-rg")
    acl = named_step(path, "102-project-lake-access")
    script = rbac.get("run", rbac.get("inputs", {}).get("inlineScript", ""))
    assert "set -euo pipefail" in script
    assert "--query properties.outputs.projectLakeAccess.value" in script
    assert "tee project-lake-access.json" in script
    assert "--parameters datalakeName_param=" in script
    assert "--parameters enableProjectLakeAccess=" in script
    assert "--parameters deployOnlyAIGatewayNetworking=" in script
    assert acl.get("continueOnError", acl.get("continue-on-error", False)) is False
    assert "PROJECT_LAKE_LEGACY_LAYOUT" in acl["env"]
    assert "enableAzureMachineLearning" in acl["env"]["PROJECT_LAKE_AML_ENABLED"]
    if path == ADO:
        assert acl["inputs"]["azureSubscription"] == rbac["inputs"]["azureSubscription"]
        assert "-Execute" in acl["inputs"]["arguments"]
    else:
        assert "steps.common_rbac.outcome == 'success'" in acl["env"]["PROJECT_LAKE_CONTRACT_READY"]
        assert "-Execute" in acl["run"]

    flags = ("deleteAllServicesForProject", "debug_disable_101_rbac_common_rg",
             "debug_disable_61_foundation", "debug_disable_62_core_infrastructure")
    for mode in ("legacy", "groups-v1"):
        for phase in ("infra", "foundry"):
            for disabled in (None, *flags):
                context = {"parameters.phase": phase, "inputs.phase": phase, "success": True}
                for prefix in ("variables.", "env."):
                    context[prefix + "persona_access_mode"] = mode
                    context.update({prefix + flag: str(flag == disabled).lower() for flag in flags})
                rbac_runs = evaluate(rbac.get("condition", rbac.get("if")), context)
                acl_runs = evaluate(acl.get("condition", acl.get("if")), context)
                assert rbac_runs is (phase == "infra" and disabled is None)
                assert acl_runs is (rbac_runs and mode == "legacy")


def test_bicep_emits_resolved_identities_without_data_plane_deployment_script():
    source = RBAC.read_text(encoding="utf-8")
    output = source.split("output projectLakeAccess object = {", 1)[1].split("\n}", 1)[0]
    for field in ("projectManagedIdentityObjectId: var_miPrj_PrincipalId",
                  "storageAccount: datalakeName_param", "storageResourceGroup: commonResourceGroup",
                  "projectResourceGroup: targetResourceGroup",
                  "readOnlyObjectIds:", "groupObjectIds:", "userObjectIds:"):
        assert field in output
    assert "enableProjectLakeAccess && !deployOnlyAIGatewayNetworking" in output
    assert "Microsoft.Resources/deploymentScripts" not in source
    assert "if(personaAccessMode == 'legacy' && !enableProjectLakeAccess && !deployOnlyAIGatewayNetworking" in source
    assert "if (enableAzureMachineLearning)" in source
    caller = CALLER.read_text(encoding="utf-8")
    for forbidden in ("TemporaryDataOwner", "az account set", "--account-key", "--sas-token",
                      "publicNetworkAccess", "Storage Blob Data Reader", "mrvel"):
        assert forbidden not in caller


@pytest.mark.parametrize("mode", ["legacy", "groups-v1"])
@pytest.mark.parametrize("lake_access", [False, True])
@pytest.mark.parametrize("gateway_only", [False, True])
def test_bicep_legacy_lake_fallback_never_broadens_groups_mode(mode, lake_access, gateway_only):
    source = RBAC.read_text(encoding="utf-8")
    context = {"personaAccessMode": mode, "enableProjectLakeAccess": lake_access,
               "deployOnlyAIGatewayNetworking": gateway_only, "aiHubExists": False, "amlExists": False,
               "enableAIFoundryHub": True, "enableAzureMachineLearning": True}
    conditions = re.findall(r"^module rbacLake\w+ .*? = if\((.+)\) \{", source, re.MULTILINE)
    assert len(conditions) == 2
    for condition in conditions:
        expression = re.sub(r"!(\w+)", r"not(\1)", condition)
        assert evaluate(expression, context) is (mode == "legacy" and not lake_access and not gateway_only)
    output = source.split("output projectLakeAccess object = {", 1)[1].split("\n}", 1)[0]
    enabled = re.search(r"^\s*enabled: (.+)$", output, re.MULTILINE)[1]
    assert evaluate(re.sub(r"!(\w+)", r"not(\1)", enabled), context) is (
        mode == "legacy" and lake_access and not gateway_only)


def test_manual_member_caller_requires_execute_and_forwards_scope():
    source = (BICEP / "esml-util/26-add-esml-project-member.ps1").read_text(encoding="utf-8")
    assert source.index("if (-not $Execute)") < source.index("New-AzResourceGroupDeployment")
    for field in ("subscriptionID = $subscriptionID", "storageResourceGroup = $storageResourceGroup",
                  "environment = $env", "managedIdentityObjectIds = $managedIdentityObjectIds",
                  "readOnlyObjectIds = $readOnlyObjectIds"):
        assert field in source
    assert "& $aclScript @aclParameters -Execute" in source
    assert "Set-AzContext" not in source
    assert "Set-AzDefault" not in source


@pytest.mark.parametrize("name", ["addUserAsProjectMember", "addUserAsProjectMemberByoVnetRGs"])
def test_manual_bicep_lake_roles_are_container_arm_reader_only(name):
    source = (BICEP / f"modules/{name}.bicep").read_text(encoding="utf-8")
    role = source.split("resource readerDatalakeStorage ", 1)[1].split("\n}]", 1)[0]
    assert "scope:projectLakeContainer" in role
    assert "readerRoleDefinition.id" in role
    assert "acdd72a7-3385-48ef-bd42-f606fba81ae7" in source
    assert "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1" not in source
