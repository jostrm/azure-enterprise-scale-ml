"""Offline GitHub manual/reviewed input and CLI-only subnet regressions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[4]
TEMPLATES = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions"
SCRIPTS = ROOT / "environment_setup/aifactory/bicep/scripts"
PROJECT = yaml.safe_load((TEMPLATES / "infra-project.yml").read_text(encoding="utf-8"))
PHASE = yaml.safe_load((TEMPLATES / "infra-project-phase.yml").read_text(encoding="utf-8"))
DISPATCH = PROJECT.get("on", PROJECT.get(True))["workflow_dispatch"]["inputs"]
CALL = PHASE.get("on", PHASE.get(True))["workflow_call"]["inputs"]
CONFIGURE = PROJECT["jobs"]["configure"]["steps"]
STEPS = PHASE["jobs"]["deploy-project"]["steps"]
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REVIEWED_FILE = "aifactory/.reviewed-project-config.json"


def named(steps, name):
    return next(step for step in steps if step.get("name") == name)


def enabled(step, inputs):
    expression = step["if"].removeprefix("${{").removesuffix("}}").strip()
    expression = re.sub(r"inputs\.(\w+)", lambda match: repr(inputs.get(match[1], "")), expression)
    expression = re.sub(r"!(?!=)", "not ", expression.replace("&&", " and ").replace("||", " or "))
    return bool(eval(expression, {"__builtins__": {}}, {}))


def run_python(step, values, monkeypatch):
    source = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    source = source.replace("${{ inputs.environment }}", values.get("TARGET_ENVIRONMENT", "dev"))
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    exec(compile(source, step["name"], "exec"), {})


@pytest.fixture
def workspace(monkeypatch):
    path = ROOT / ".test-state" / ("github-inputs-" + uuid4().hex)
    path.mkdir(parents=True)
    monkeypatch.chdir(path)
    try:
        yield path
    finally:
        monkeypatch.chdir(ROOT)
        shutil.rmtree(path)


def reviewed(workspace, target="dev"):
    values = {"project_number_000": "017", "tenantId": TENANT,
              "dev_sub_id": SUBSCRIPTION, "test_sub_id": SUBSCRIPTION, "prod_sub_id": SUBSCRIPTION}
    raw = json.dumps({"dev": values, "stage_prod": values}, separators=(",", ":"))
    path = workspace / REVIEWED_FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return {
        "DEPLOYMENT_ID": "12345678-1234-4234-8234-123456789012", "PROJECT_NUMBER": "017",
        "TARGET_ENVIRONMENT": target, "CONFIG_FILE": REVIEWED_FILE,
        "CONFIG_HASH": hashlib.sha256(raw.encode()).hexdigest(),
        "CONFIG_SECRET": "AIFACTORY_CONFIG_SYNTHETIC", "AIFACTORY_CONFIG_JSON": raw,
        "EXPECTED_SUBSCRIPTION": SUBSCRIPTION, "EXPECTED_TENANT": TENANT,
        "dev_test_prod_sub_id": SUBSCRIPTION, "tenantId": TENANT, "JSON_IDENTITY_AUTH": "false",
    }


def test_empty_manual_inputs_are_optional_in_dispatch_and_reusable_workflow():
    for key in ("deployment_id", "project_number", "config_hash", "self_hosted_runner_label", "admin_vm_runner_label"):
        assert DISPATCH[key]["required"] is False
        assert DISPATCH[key]["default"] == ""
    assert DISPATCH["environment"]["required"] is True
    assert DISPATCH["environment"]["options"] == ["dev", "stage", "prod"]
    assert DISPATCH["config_file"]["default"] == "aifactory/variables.json"
    assert DISPATCH["config_secret"]["default"] == "AIFACTORY_CONFIG_JSON"
    assert CALL["config_file"]["required"] is False
    assert CALL["config_file"]["default"] == ""
    for key in ("environment", "phase", "runs_on"):
        assert CALL[key]["required"] is True
    for job in ("deploy_infrastructure", "deploy_foundry"):
        assert PROJECT["jobs"][job]["with"]["config_file"] == "${{ inputs.config_file }}"


def test_required_manual_inputs_keep_nonempty_defaults_and_exact_scope_selectors():
    for path in TEMPLATES.glob("*.yml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        inputs = document.get("on", document.get(True)).get("workflow_dispatch", {}).get("inputs", {})
        for key, definition in inputs.items():
            if definition.get("required") and definition["type"] != "boolean":
                assert definition.get("default"), f"{path.name}/{key}: required-empty manual input"
        if path.name in {"infra-project-dashboards.yml", "infra-project-healthmodel.yml"}:
            assert inputs["environment"]["required"] and inputs["project_number"]["required"]


@pytest.mark.parametrize("target", ["dev", "stage", "prod"])
@pytest.mark.parametrize("config_file", ["", "aifactory/variables.json"])
def test_manual_default_and_variables_only_runner_paths(workspace, monkeypatch, target, config_file):
    if config_file:
        path = workspace / config_file
        path.parent.mkdir()
        path.write_text('{"dev":{"useSelfHostedBuildAgent":false}}', encoding="utf-8")
    inputs = {"environment": target, "config_file": config_file, "deployment_id": "",
              "project_number": "", "config_hash": "", "json_identity_auth": False}
    assert not enabled(named(CONFIGURE, "Validate reviewed project and target"), inputs)
    assert not enabled(named(STEPS, "00_Validate_Reviewed_Target"), inputs)
    output = workspace / "outputs"
    run_python(named(CONFIGURE, "Resolve runner from workflow input and JSON"), {
        "CONFIG_FILE": config_file, "RUNNER_SELECTION": "from-config",
        "SELF_HOSTED_RUNNER_LABEL": "", "LEGACY_ADMIN_VM_RUNNER_LABEL": "",
        "TARGET_ENVIRONMENT": target, "GITHUB_OUTPUT": str(output),
    }, monkeypatch)
    assert "runs_on=\"ubuntu-latest\"" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("target", ["dev", "stage", "prod"])
def test_reviewed_preflights_accept_exact_protected_configuration(workspace, monkeypatch, target):
    values = reviewed(workspace, target)
    inputs = {key.lower(): value for key, value in values.items()}
    inputs["json_identity_auth"] = False
    assert enabled(named(CONFIGURE, "Validate reviewed project and target"), inputs)
    assert enabled(named(STEPS, "00_Validate_Reviewed_Target"), inputs)
    run_python(named(CONFIGURE, "Validate reviewed project and target"), values, monkeypatch)
    run_python(named(STEPS, "00_Validate_Reviewed_Target"), values, monkeypatch)


@pytest.mark.parametrize("field", ["deployment_id", "project_number", "config_hash", "config_file"])
def test_partial_review_metadata_cannot_silently_select_legacy_mode(workspace, monkeypatch, field):
    values = reviewed(workspace)
    inputs = {"deployment_id": "", "project_number": "", "config_hash": "", "config_file": ""}
    inputs[field] = values[field.upper()]
    step = named(CONFIGURE, "Validate reviewed project and target")
    assert enabled(step, inputs), "Incomplete reviewed inputs must not bypass preflight"
    values.update({key.upper(): value for key, value in inputs.items()})
    with pytest.raises((SystemExit, ValueError)):
        run_python(step, values, monkeypatch)


@pytest.mark.parametrize("field,value", [
    ("AIFACTORY_CONFIG_JSON", ""), ("CONFIG_SECRET", ""), ("CONFIG_HASH", ""),
    ("CONFIG_HASH", "0" * 64), ("PROJECT_NUMBER", ""), ("PROJECT_NUMBER", "018"),
    ("DEPLOYMENT_ID", ""), ("CONFIG_FILE", ""), ("CONFIG_FILE", "aifactory/variables.json"),
    ("EXPECTED_SUBSCRIPTION", TENANT), ("EXPECTED_TENANT", SUBSCRIPTION),
])
def test_reviewed_configure_requires_secret_hash_project_and_exact_target(workspace, monkeypatch, field, value):
    values = reviewed(workspace)
    values[field] = value
    with pytest.raises((SystemExit, ValueError, OSError)):
        run_python(named(CONFIGURE, "Validate reviewed project and target"), values, monkeypatch)


def test_checked_in_file_cannot_replace_the_protected_reviewed_payload(workspace, monkeypatch):
    values = reviewed(workspace)
    values["AIFACTORY_CONFIG_JSON"] += "\n"
    with pytest.raises(SystemExit, match="differs from the run-specific secret"):
        run_python(named(CONFIGURE, "Validate reviewed project and target"), values, monkeypatch)


def test_reviewed_phase_validates_before_overrides_and_login():
    guard = STEPS.index(named(STEPS, "00_Validate_Reviewed_Target"))
    for index, step in enumerate(STEPS):
        if step.get("uses") == "azure/login@v2" or step.get("name") in {
            "00_Materialize_Protected_JSON_Config", "00_Apply_JSON_Config_Override",
        }:
            assert guard < index, "Validate the protected payload before consuming it or logging in"


@pytest.mark.parametrize("field,value", [
    ("AIFACTORY_CONFIG_JSON", ""), ("CONFIG_HASH", ""),
    ("CONFIG_HASH", "0" * 64), ("DEPLOYMENT_ID", ""), ("CONFIG_FILE", ""),
    ("dev_test_prod_sub_id", TENANT), ("tenantId", SUBSCRIPTION),
])
def test_reviewed_phase_rejects_missing_or_changed_contract(workspace, monkeypatch, field, value):
    values = reviewed(workspace)
    values[field] = value
    with pytest.raises((SystemExit, ValueError)):
        run_python(named(STEPS, "00_Validate_Reviewed_Target"), values, monkeypatch)


def test_json_identity_mode_cannot_disable_reviewed_guards(workspace, monkeypatch):
    if "json_identity_auth" not in DISPATCH:
        assert "json_identity_auth" not in CALL
        return
    values = reviewed(workspace)
    values["JSON_IDENTITY_AUTH"] = "true"
    inputs = {key.lower(): value for key, value in values.items()}
    inputs["json_identity_auth"] = True
    for step in (named(CONFIGURE, "Validate reviewed project and target"), named(STEPS, "00_Validate_Reviewed_Target")):
        assert enabled(step, inputs)
        with pytest.raises(SystemExit, match="JSON identity"):
            run_python(step, values, monkeypatch)


def test_normal_json_identity_mode_does_not_require_reviewed_metadata():
    inputs = {"config_file": "aifactory/variables.json", "json_identity_auth": True}
    assert not enabled(named(CONFIGURE, "Validate reviewed project and target"), inputs)
    assert not enabled(named(STEPS, "00_Validate_Reviewed_Target"), inputs)


def test_subnet_step_uses_azure_login_cli_without_az_powershell_session():
    subnet = named(STEPS, "05_Calculate_Subnet_Allocations")
    assert PHASE["jobs"]["deploy-project"]["defaults"]["run"]["shell"] == "pwsh"
    assert "subnetCalc_v2.ps1" in subnet["run"]
    assert "-useServicePrincipal" not in subnet["run"]
    logins = [step for step in STEPS[:STEPS.index(subnet)] if step.get("uses") == "azure/login@v2"]
    assert logins
    assert all(step["with"].get("enable-AzPSSession", False) is False for step in logins)
    assert not any(step.get("uses", "").startswith("azure/powershell") for step in STEPS)


def test_real_github_subnet_dependency_resolver_never_installs_or_imports_az():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is required for offline dependency checks")
    code = r"""
$ErrorActionPreference = 'Stop'
$script:imports = [System.Collections.Generic.List[string]]::new()
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DEPENDENCIES, [ref]$null, [ref]$null)
$ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false) | ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }
function Get-PSCallStack {
    @([pscustomobject]@{Command='Import-Dependencies'},
      [pscustomobject]@{Command='subnetCalc_v2.ps1'})
}
function Get-Module {
    param([string]$Name, [switch]$ListAvailable)
    if ($ListAvailable -and $Name -eq 'Subnet') {
        [pscustomobject]@{Name='Subnet'; Version=[version]'1.0.6'; ModuleBase='offline'}
    }
}
function Install-Module { throw 'No installations permitted' }
function Import-Module {
    param([string]$Name, [string]$RequiredVersion, [switch]$Force)
    if ($Name -like 'Az*') { throw 'Assembly with same name is already loaded' }
    $script:imports.Add($Name)
}
Import-Dependencies
ConvertTo-Json -InputObject @($script:imports) -Compress
"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", code],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
        env={**os.environ, "GITHUB_ACTIONS": "true", "AIFACTORY_USE_AZURE_CLI": "false",
             "DEPENDENCIES": str(SCRIPTS / "modules/pipelineFunctions.psm1")},
    )
    assert result.returncode == 0, result.stderr
    expected = ["Subnet"] if "Get-Subnet" in (SCRIPTS / "subnetCalc_v2.ps1").read_text(encoding="utf-8") else []
    assert json.loads(result.stdout) == expected
