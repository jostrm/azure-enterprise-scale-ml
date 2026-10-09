"""Offline provider parity and native-exit contracts for project deletion."""
from __future__ import annotations

import os
import json
from pathlib import Path
from functools import lru_cache
import re
import shlex
import shutil
import subprocess
import sys

import pytest

from domain.pipeline_contracts import (
    ADO_PROJECT, ADO_SERVICES, GHA_PHASE, GHA_PROJECT,
    deployments, evaluate, load_pipeline, objects,
)
from base.config import REPO_ROOT


SHARED_SCRIPT = "delete-services-if-disabled.sh"
REPORT = "AIF_DELETE_REPORT_DIR"


@lru_cache(maxsize=None)
def steps(platform):
    document = load_pipeline(GHA_PHASE if platform == "gha" else ADO_SERVICES)
    return document["jobs"]["deploy-project"]["steps"] if platform == "gha" else document["steps"]


def script(step):
    return step.get("run", step.get("inputs", {}).get("inlineScript", step.get("inputs", {}).get("script", "")))


def deletion(platform):
    found = [step for step in steps(platform)
             if any(SHARED_SCRIPT in line for line in script(step).splitlines() if not line.lstrip().startswith("#"))
             or SHARED_SCRIPT in step.get("inputs", {}).get("scriptPath", "")]
    assert len(found) == 1, f"{platform}: exactly one shared authoritative deletion invocation"
    return found[0]


def condition(step, platform):
    expression = step.get("if" if platform == "gha" else "condition", "success()")
    # The existing bounded evaluator does not implement always(). Its value is
    # unconditional; replace only that exact no-argument function for these tests.
    expression = expression.replace("always()", "true")
    if platform == "gha" and not re.search(r"\b(success|failure|cancelled|always)\(", step.get("if", "")):
        expression = "success() && (" + expression + ")"
    return expression


def context(platform, phase="infra", success=True, **values):
    prefix = "env." if platform == "gha" else "variables."
    result = {"success": success, "failed": not success, "canceled": False,
              "inputs.phase": phase, "parameters.phase": phase}
    # Unset CI variables resolve to empty strings, rather than Python truthiness.
    for step in objects(load_pipeline(GHA_PHASE if platform == "gha" else ADO_SERVICES)):
        for key in re.findall(r"(?:env\.|variables\[')([\w.]+)", step.get("if", step.get("condition", ""))):
            result[prefix + key] = ""
    defaults = {
        "deleteAllForProject": "false", "deleteAllServicesForProject": "false",
        "enableDeleteForDisabledResources": "false", "persona_preflight_ready": "true",
        "persona_access_mode": "legacy", "enableAIFoundry": "true",
    }
    defaults.update(values)
    result.update({prefix + key: value for key, value in defaults.items()})
    return result


@pytest.mark.parametrize("platform", ["gha", "ado"])
def test_shared_deletion_has_explicit_budget_and_per_attempt_reports(platform):
    step = deletion(platform)
    assert int(step["timeout-minutes" if platform == "gha" else "timeoutInMinutes"]) >= 120
    assert step.get("continue-on-error", step.get("continueOnError", "false")) == "false"
    assert step["env"]["AIF_DELETE_TIMEOUT_SECONDS"] == "1800"
    assert step["env"]["AIF_DELETE_POLL_SECONDS"] == "15"
    report_dir = step["env"][REPORT]
    if platform == "gha":
        assert all(token in report_dir for token in ("runner.temp", "github.run_id", "github.run_attempt", "inputs.phase"))
        assert int(load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["timeout-minutes"]) >= 150
        inherited = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["env"]
    else:
        assert all(token in report_dir for token in ("Build.ArtifactStagingDirectory", "System.JobId", "System.JobAttempt"))
        inherited = {}
        jobs = [item for item in objects(load_pipeline(ADO_PROJECT)) if item.get("deployment") == "ESGenAI_Services"]
        assert len(jobs) == 3
        assert all(int(job["timeoutInMinutes"]) >= 150 for job in jobs)
        assert step["inputs"]["scriptType"] == "bash"
        assert step["inputs"]["scriptLocation"] == "scriptPath"
    for flag in ("deleteAllForProject", "deleteAllServicesForProject", "enableDeleteForDisabledResources", "deleteKeyvaultAlso"):
        assert flag in step["env"] or flag in inherited


@pytest.mark.parametrize("platform", ["gha", "ado"])
@pytest.mark.parametrize("mode", ["none", "disabled", "services", "full"])
@pytest.mark.parametrize("success", [True, False])
def test_deletion_gate_runs_only_requested_successful_infra(platform, mode, success):
    values = {
        "enableDeleteForDisabledResources": str(mode in ("disabled", "services", "full")).lower(),
        "deleteAllServicesForProject": str(mode in ("services", "full")).lower(),
        "deleteAllForProject": str(mode == "full").lower(),
    }
    expression = condition(deletion(platform), platform)
    assert bool(evaluate(expression, context(platform, success=success, **values))) == (success and mode != "none")
    assert not evaluate(expression, context(platform, phase="foundry", success=success, **values))


@pytest.mark.parametrize("platform", ["gha", "ado"])
def test_detection_uses_authoritative_arm_resource_types(platform):
    detection = next(step for step in steps(platform)
                     if "resource_exists_fuzzy" in script(step) and "databricksExists" in script(step))
    text = script(detection)
    assert '"Microsoft.Databricks/workspaces"' in text
    assert '"Microsoft.MachineLearningServices/workspaces"' in text
    assert "Microsoft.Azure.Databricks" not in text


def test_linux_deletion_prerequisites_use_powershell_core():
    all_steps = steps("ado")
    main = all_steps.index(deletion("ado"))
    random = next(step for step in all_steps if step.get("displayName") == "00_generate_deployment_random_value")
    assert random["inputs"]["scriptType"] == "pscore"
    assert all(step.get("inputs", {}).get("scriptType") != "ps" for step in all_steps[:main])


@pytest.mark.parametrize("platform", ["gha", "ado"])
def test_reports_publish_after_failed_deletion_without_missing_directory_errors(platform):
    all_steps = steps(platform)
    main = deletion(platform)
    publish = next(step for step in all_steps
                   if step.get("name", step.get("displayName")) == "Publish AI Factory deletion reports")
    assert all_steps.index(main) < all_steps.index(publish)
    assert "always()" in publish.get("if", publish.get("condition", ""))
    if platform == "gha":
        assert main["run"].index("New-Item") < main["run"].index("& bash")
        assert publish["uses"] == "actions/upload-artifact@v4"
        assert publish["with"]["path"] == main["env"][REPORT] + "/*.json"
        assert publish["with"]["if-no-files-found"] == "ignore"
        assert evaluate(condition(publish, platform), context(platform, success=False))
    else:
        init = next(step for step in all_steps if step.get("displayName") == "Initialize AI Factory deletion reports")
        assert all_steps.index(init) < all_steps.index(main)
        assert init["condition"] == main["condition"]
        assert init["env"][REPORT] == main["env"][REPORT] == publish["inputs"]["targetPath"]
        assert script(init).index("mkdir") < script(init).index("variable=aifactoryDeletionReportReady]true")
        assert evaluate(condition(publish, platform), context(platform, success=False, aifactoryDeletionReportReady="true"))
        assert not evaluate(condition(publish, platform), context(platform, success=False, aifactoryDeletionReportReady=""))


@pytest.mark.parametrize("platform", ["gha", "ado"])
@pytest.mark.parametrize("success", [True, False])
def test_full_delete_never_falls_through_to_resource_creation(platform, success):
    document = load_pipeline(GHA_PHASE if platform == "gha" else ADO_SERVICES)
    for deployment in deployments(document):
        values = context(platform, success=success, deleteAllForProject="true",
                         deleteAllServicesForProject="true", enableDeleteForDisabledResources="true")
        assert not evaluate(condition(deployment.step, platform), values), deployment.name


def test_foundry_jobs_use_effective_deletion_outputs_and_preserve_failure_guards():
    phase = load_pipeline(GHA_PHASE)
    assert phase["on"]["workflow_call"]["outputs"]["skip_foundry"]["value"] == "${{ jobs.deploy-project.outputs.skip_foundry }}"
    assert phase["jobs"]["deploy-project"]["outputs"]["skip_foundry"] == "${{ steps.deletion_mode.outputs.skip_foundry }}"
    normalizer = next(step for step in steps("gha") if step.get("id") == "deletion_mode")
    assert "deleteAllForProject" in script(normalizer) and "deleteAllServicesForProject=true" in script(normalizer)
    foundry = load_pipeline(GHA_PROJECT)["jobs"]["deploy_foundry"]
    for skip, result, expected in [("false", "success", True), ("true", "success", False), ("false", "failure", False)]:
        assert bool(evaluate(foundry["if"], {
            "needs.deploy_infrastructure.outputs.skip_foundry": skip,
            "needs.deploy_infrastructure.result": result,
        })) == expected
    ado_normalizer = next(step for step in steps("ado") if step.get("name") == "deletionMode")
    assert "skipFoundry;isOutput=true" in script(ado_normalizer)
    for job in objects(load_pipeline(ADO_PROJECT)):
        if job.get("deployment") != "ESGenAI_Foundry":
            continue
        output = "dependencies.ESGenAI_Services.outputs.ESGenAI_Services.deletionMode.skipFoundry"
        for skip, result, expected in [
            ("false", "Succeeded", True),
            ("true", "Succeeded", False), ("false", "Failed", False),
        ]:
            assert bool(evaluate(job["condition"], {"canceled": False, output: skip,
                        "dependencies.ESGenAI_Services.result": result})) == expected


@pytest.mark.parametrize("exit_code", [0, 37])
def test_github_wrapper_propagates_actual_native_exit(tmp_path, exit_code):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core is not installed")
    body = deletion("gha")["run"]
    # This function stands in for bash but executes a real native process. The
    # wrapper is run verbatim, including report initialization and exit handling.
    native = f"& $env:ComSpec /d /c 'exit {exit_code}'" if os.name == "nt" else f"& /bin/sh -c 'exit {exit_code}'"
    wrapper = tmp_path / "delete-wrapper.ps1"
    wrapper.write_text("$ErrorActionPreference = 'Stop'\nfunction bash { Write-Output '##vso[task.setvariable variable=amlExists]false'; " + native + " }\n" + body, encoding="utf-8")
    github_env = tmp_path / "github-env"
    env = {**os.environ, REPORT: str(tmp_path / "reports"), "GITHUB_WORKSPACE": str(tmp_path), "GITHUB_ENV": str(github_env),
           "amlExists": "true", "aiHubExists": "false", "aiFoundryV2Exists": "true"}
    result = subprocess.run([pwsh, "-NoProfile", "-File", str(wrapper)], env=env, capture_output=True, text=True)
    assert (result.returncode == 0) == (exit_code == 0), result.stdout + result.stderr
    if exit_code == 0:
        assert "amlExists=false" in github_env.read_text(encoding="utf-8")
        assert "aif_delete_before_amlExists=true" in github_env.read_text(encoding="utf-8")
        assert "aif_delete_before_aiHubExists=false" in github_env.read_text(encoding="utf-8")
        assert "aif_delete_before_aiFoundryV2Exists=true" in github_env.read_text(encoding="utf-8")


def test_full_delete_failure_does_not_start_legacy_deployment_rollback():
    for step in steps("ado"):
        if not step.get("displayName", "").startswith(("111_", "112_", "114_")):
            continue
        expression = condition(step, "ado")
        expression = re.sub(r"contains\(variables\['Agent.JobStatus'\], '[^']+'\)", "true", expression)
        values = context("ado", success=False, deleteAllForProject="true", deleteAllServicesForProject="true",
                         debugEnableCleaning="true", **{"System.StageResult": "Failed", "71_deleted": "true", "72_deleted": "true"})
        assert not evaluate(expression, values), step["displayName"]


def test_real_bash_helper_cli_smoke_deletes_stale_databricks_inventory(tmp_path):
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    if not bash.is_file():
        pytest.skip("Git Bash or Bash is required for the offline process-chain smoke test")
    source = REPO_ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / SHARED_SCRIPT
    fake_bin = tmp_path / "isolated-bin"
    fake_bin.mkdir()
    fake_cli = tmp_path / "fake_azure_cli.py"
    fake_cli.write_text(r'''
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

args = sys.argv[1:]
root = Path(os.environ["FAKE_AZ_ROOT"])
with (root / "calls.jsonl").open("a", encoding="utf-8") as output:
    output.write(json.dumps({"args": args,
                             "dynamicInstall": os.environ.get("AZURE_EXTENSION_USE_DYNAMIC_INSTALL"),
                             "noPathConversion": os.environ.get("MSYS_NO_PATHCONV"),
                             "argConversionExclusion": os.environ.get("MSYS2_ARG_CONV_EXCL")}) + "\n")
resource = {
    "id": "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/unit-project002-sdc-dev-rg/providers/Microsoft.Databricks/workspaces/dbx-002-sdc-dev-smoke-001",
    "name": "dbx-002-sdc-dev-smoke-001",
    "type": "Microsoft.Databricks/workspaces",
    "properties": {"provisioningState": "Succeeded"},
}
if args[:2] == ["account", "set"]:
    sys.exit(0)
if args[:2] == ["resource", "list"]:
    print(json.dumps([resource]))
    sys.exit(0)
if args[:3] in (["network", "private-endpoint", "list"], ["network", "nic", "list"]):
    # The shared shell performs these read-only adjunct checks using TSV.
    sys.exit(0)
if args[:1] == ["rest"]:
    url = urlsplit(args[args.index("--url") + 1])
    assert url.netloc == "management.azure.com" and url.path == resource["id"], args
    method = args[args.index("--method") + 1].lower()
    deleted = root / "deleted"
    if method == "delete":
        assert not deleted.exists(), "Overlapping/repeated delete"
        deleted.touch()
        sys.exit(0)
    if method == "get":
        if deleted.exists():
            print('ERROR: Not Found({"error":{"code":"ResourceNotFound","message":"The workspace no longer exists."}})', file=sys.stderr)
            sys.exit(3)
        print(json.dumps(resource))
        sys.exit(0)
raise SystemExit("Unexpected offline Azure CLI call: " + repr(args))
''', encoding="utf-8")
    az = fake_bin / "az"
    az.write_text(
        f"#!/bin/sh\nexec {shlex.quote(Path(sys.executable).as_posix())} {shlex.quote(fake_cli.as_posix())} \"$@\"\n",
        encoding="utf-8", newline="\n",
    )
    az.chmod(0o755)
    if os.name == "nt":
        (fake_bin / "az.cmd").write_text(
            f'@echo off\n"{sys.executable}" "{fake_cli}" %*\nexit /b %errorlevel%\n',
            encoding="utf-8",
        )
        path = os.pathsep.join((str(fake_bin), str(Path(sys.executable).parent),
                                str(bash.parents[1] / "usr" / "bin")))
    else:
        (fake_bin / "python").symlink_to(sys.executable)
        for name in ("dirname", "tr"):
            executable = shutil.which(name)
            assert executable, f"The existing shell test requires {name}"
            (fake_bin / name).symlink_to(executable)
        path = str(fake_bin)
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"PATH", "BASH_ENV", "ENV", "AZURE_EXTENSION_USE_DYNAMIC_INSTALL"}
                   and not key.startswith("BASH_FUNC_")}
    environment.update({name: "true" for name in deletion("ado")["env"] if name.startswith("enable")})
    environment.update({
        "PATH": path, "FAKE_AZ_ROOT": str(tmp_path),
        "dev_test_prod_sub_id": "11111111-1111-4111-8111-111111111111",
        "admin_aifactoryPrefixRG": "unit-", "admin_aifactorySuffixRG": "-rg",
        "admin_locationSuffix": "sdc", "dev_test_prod": "dev", "project_number_000": "002",
        "projectPrefix": "", "projectSuffix": "", "deleteAllForProject": "false",
        "deleteAllServicesForProject": "false", "deleteKeyvaultAlso": "false",
        "enableDeleteForDisabledResources": "true", "enableDatabricks": "false",
        "databricksExists": "false", "allowPublicAccessWhenBehindVnet": "true",
        "AIF_DELETE_REPORT_DIR": str(tmp_path / "reports"),
        "AIF_DELETE_TIMEOUT_SECONDS": "20", "AIF_DELETE_POLL_SECONDS": "0.01",
        "PYTHONUTF8": "1",
    })
    # Resolve and require the fake CLI before sourcing any script. No ambient PATH
    # or Azure command can become a fallback, including inside the native helper.
    probe = 'python -c "import os, pathlib, shutil; assert pathlib.Path(shutil.which(\'az\')).parent == pathlib.Path(os.environ[\'FAKE_AZ_ROOT\']) / \'isolated-bin\'"'
    result = subprocess.run(
        [str(bash), "--noprofile", "--norc", "-c", "set -e\n" + probe + '\nexec "' + bash.as_posix() + '" "$1"', "smoke", source.as_posix()],
        cwd=REPO_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(call["args"][:2] == ["resource", "list"] for call in calls)
    rest = [call for call in calls if call["args"][0] == "rest"]
    assert [call["args"][call["args"].index("--method") + 1].lower() for call in rest] == ["get", "delete", "get"]
    assert all(call["dynamicInstall"] == "no" for call in rest)
    assert next(call for call in calls if call["args"][:2] == ["account", "set"])["dynamicInstall"] is None
    assert all(call["noPathConversion"] == "1" and call["argConversionExclusion"] == "*" for call in calls)
    assert not any(call["args"][0] in {"ml", "databricks", "extension"} for call in calls)
    assert all(call["args"][:2] in (["account", "set"], ["resource", "list"])
               or call["args"][:3] in (["network", "private-endpoint", "list"], ["network", "nic", "list"])
               or call["args"][0] == "rest" for call in calls)
    reports = tmp_path / "reports"
    lifecycle = json.loads((reports / "last-deletion.json").read_text(encoding="utf-8"))
    outcome = json.loads((reports / "deletion-result.json").read_text(encoding="utf-8"))
    assert lifecycle["status"] == "succeeded"
    assert lifecycle["action"] == "resource"
    assert list(lifecycle["states"].values()) == ["Absent"]
    assert outcome["status"] == "succeeded" and outcome["exitCode"] == 0
    assert outcome["fullProjectDeletion"] is False


def run_provider_bash(tmp_path, body, values, prelude=""):
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    if not bash.is_file():
        pytest.skip("Bash required for offline provider script execution")
    body = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", lambda match: values.get(match[1], ""), body)
    body = re.sub(r"\$\{\{\s*env\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}",
                  lambda match: values.get(match[1], ""), body)
    path = tmp_path / "provider-step.sh"
    path.write_text("set -e\naz() { echo 'UNEXPECTED AZ CALL' >&2; return 99; }\n"
                    "sleep() { :; }\n" + prelude + "\n" + body, encoding="utf-8", newline="\n")
    environment = {**os.environ, **values, "GITHUB_OUTPUT": str(tmp_path / "github-output"),
                   "MOCK_AZ_LOG": str(tmp_path / "mock-az-log")}
    environment.pop("BASH_ENV", None)
    return subprocess.run([str(bash), "--noprofile", "--norc", path.as_posix()],
                          cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
                          encoding="utf-8", timeout=30)


@pytest.mark.parametrize("full,services,expected_full,expected_services", [
    ("True", "FALSE", "true", "true"), ("FALSE", "True", "false", "true"),
    ("TRUE", "false", "true", "true"), ("false", "FALSE", "false", "false"),
])
def test_ado_actual_normalizer_handles_boolean_casing(tmp_path, full, services, expected_full, expected_services):
    step = next(step for step in steps("ado") if step.get("name") == "deletionMode")
    result = run_provider_bash(tmp_path, script(step), {
        "deleteAllForProject": full, "deleteAllServicesForProject": services,
        "BYO_subnets": "false",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"##vso[task.setvariable variable=deleteAllForProject]{expected_full}" in result.stdout
    assert f"##vso[task.setvariable variable=deleteAllServicesForProject]{expected_services}" in result.stdout
    assert f"##vso[task.setvariable variable=skipFoundry;isOutput=true]{expected_services}" in result.stdout


def test_github_services_only_preserves_legacy_foundation_boundary():
    assert deletion("gha")["env"]["AIF_DELETE_PRESERVE_FOUNDATION"] == "true"
    assert "AIF_DELETE_PRESERVE_FOUNDATION" not in deletion("ado")["env"]
    # Legacy services-only cleanup did not include these foundation resources;
    # service private endpoints and bot-specific identities remain service-owned.
    text = GHA_PHASE.read_text(encoding="utf-8")
    for retained in ("Key Vault", "Storage", "App Insights", "dashboards", "VMs", "ACR", "general identities", "common networking"):
        assert retained in text.split("AIF_DELETE_PRESERVE_FOUNDATION", 1)[0][-500:]


@pytest.mark.parametrize("existed", ["true", "false"])
def test_github_purge_uses_predelete_eligibility_not_imported_exists_flags(tmp_path, existed):
    step = next(step for step in steps("gha") if step.get("name") == "18_Purge_Soft_Deleted")
    result = run_provider_bash(tmp_path, script(step), {
        "amlExists": "false", "aiFoundryV2Exists": "false", "aiHubExists": "false",
        "aif_delete_before_amlExists": existed,
        "aif_delete_before_aiFoundryV2Exists": "false",
        "aif_delete_before_aiHubExists": "false",
        "dev_test_prod_sub_id": "unit-sub", "admin_location": "unit-region",
        "admin_aifactoryPrefixRG": "unit-", "project_number_000": "002",
        "admin_locationSuffix": "sdc", "dev_test_prod": "dev", "admin_aifactorySuffixRG": "-rg",
    }, r'''
az() {
  printf '%s\\n' "$*" >> "$MOCK_AZ_LOG"
  if [[ "$1 $2" == "account set" ]]; then return 0; fi
  if [[ "$1" == rest && "$*" == *deletedWorkspaces* && "$*" == *GET* ]]; then
    echo "QUERY:$*" >&2
    echo aml-unit
    return 0
  fi
  if [[ "$1" == rest && "$*" == *deletedWorkspaces/aml-unit* && "$*" == *DELETE* ]]; then
    echo "PURGE:$*" >&2
    return 0
  fi
  echo "UNEXPECTED:$*" >&2; return 99
}
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert ("PURGE:" in result.stderr) == (existed == "true")
    if existed == "true":
        assert "resourceGroup=='unit-project002-sdc-dev-rg'" in (tmp_path / "mock-az-log").read_text()
    assert "UNEXPECTED:" not in result.stderr


@pytest.mark.parametrize("confirmed", ["true", "false", ""])
def test_ado_purge_missing_group_requires_confirmed_current_run_deletion(tmp_path, confirmed):
    step = next(step for step in steps("ado") if step.get("name") == "purgeSoftDeleted")
    result = run_provider_bash(tmp_path, script(step), {
        "dev_test_prod_sub_id": "unit-sub", "admin_location": "unit-region",
        "admin_aifactoryPrefixRG": "unit-", "project_number_000": "002",
        "admin_locationSuffix": "sdc", "dev_test_prod": "dev", "admin_aifactorySuffixRG": "-rg",
        "deleteAllServicesForProject": "true", "aifProjectGroupDeletionConfirmed": confirmed,
        "aifProjectExists": "true", "aifProjectActualName": "aif-p-002-1-sdc-dev-recorded",
        "aifactory_salt": "", "aifactory_salt_random": "",
        "amlExists": "false", "aiHubExists": "false", "aiFoundryV2Exists": "false",
        "openaiExists": "false", "aiServicesExists": "false",
    }, r'''
az() {
  printf '%s\\n' "$*" >> "$MOCK_AZ_LOG"
  if [[ "$1 $2" == "account set" ]]; then return 0; fi
  if [[ "$1 $2" == "group exists" ]]; then echo false; return 0; fi
  if [[ "$1" == rest && "$*" == *aif-p-002-1-sdc-dev-recorded* ]]; then
    if [[ "$*" == *"--method get"* ]]; then echo SoftDeleted; return 0; fi
    if [[ "$*" == *"--method delete"* && "$*" == *forceToPurge=true* ]]; then
      echo "PURGE:$*" >&2; return 0
    fi
  fi
  if [[ "$1 $2 $3" == "cognitiveservices account list-deleted" ]]; then
    echo "SCOPED-LIST:$*" >&2; return 0
  fi
  echo "UNEXPECTED:$*" >&2; return 99
}
''')
    assert result.returncode == 0, result.stdout + result.stderr
    assert ("PURGE:" in result.stderr) == (confirmed == "true")
    assert "UNEXPECTED:" not in result.stderr
    if confirmed == "true":
        assert "/resourceGroups/unit-project002-sdc-dev-rg/" in result.stderr
        assert "resourceGroup=='unit-project002-sdc-dev-rg'" in (tmp_path / "mock-az-log").read_text()


PURGE_NAMES = {
    "aml": ["aml-002-sdc-dev-salt-001", "aml-002-sdc-dev-old-001"],
    "aifProject": ["aif-p-002-1-sdc-dev-salt-001", "ai-prj002-old-001"],
    "aiHub": ["aif-hub-002-sdc-dev-salt-001", "ai-hub-prj002-old-001"],
    "aiFoundryV2": ["aif2salt002dev", "aif2old002dev"],
    "openai": ["aoai-prj002-sdc-dev-salt-001", "aoai-prj002-sdc-dev-old-001"],
    "aiServices": ["aiservicesprj002sdcdevsalt001", "aiservicesprj002sdcdevold001"],
}


def run_recorded_purge(tmp_path, platform, service, names, **overrides):
    step = next(step for step in steps(platform)
                if step.get("name") == ("18_Purge_Soft_Deleted" if platform == "gha" else "purgeSoftDeleted"))
    values = {
        "dev_test_prod_sub_id": "unit-sub", "admin_location": "unit-region",
        "admin_aifactoryPrefixRG": "unit-", "admin_aifactorySuffixRG": "-rg",
        "project_number_000": "002", "admin_locationSuffix": "sdc", "dev_test_prod": "dev",
        "projectPrefix": "", "projectSuffix": "", "deleteAllServicesForProject": "false",
        "enableAzureMachineLearning": "true", "enableAIFoundryHub": "true", "enableAIFoundry": "false",
        "aifactory_salt": "", "aifactory_salt_random": "",
        "aif_delete_before_amlExists": "false", "aif_delete_before_aiHubExists": "false",
        "aif_delete_before_aiFoundryV2Exists": "false",
        "MOCK_INVENTORY": json.dumps(names), "MOCK_SERVICE": service,
        "MOCK_PYTHON": Path(sys.executable).as_posix(),
        "MOCK_SCRIPT": (tmp_path / "purge-az.py").as_posix(),
    }
    for candidate in PURGE_NAMES:
        values.update({candidate + "Exists": "false", candidate + "Deleted": "false",
                       candidate + "DeletedNames": f"$({candidate}DeletedNames)",
                       candidate + "ActualName": ""})
    values.update({service + "Deleted": "true", service + "DeletedNames": json.dumps(names),
                   service + "ActualName": names[-1] if names else ""})
    values.update(overrides)
    (tmp_path / "purge-az.py").write_text(r'''
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

args = sys.argv[1:]
with Path(os.environ["MOCK_AZ_LOG"]).open("a", encoding="utf-8") as output:
    output.write(json.dumps(args) + "\n")
names = json.loads(os.environ["MOCK_INVENTORY"])
service = os.environ["MOCK_SERVICE"]
rg = "unit-project002-sdc-dev-rg"
ml = service in ("aml", "aifProject", "aiHub")
def value(flag):
    return args[args.index(flag) + 1]
def listed():
    query = value("--query")
    assert f"resourceGroup=='{rg}'" in query, args
    if os.environ.get("MOCK_LIST_ERROR") == "true":
        sys.exit(42)
    if os.environ.get("MOCK_UNEXPECTED_TARGET") == "true":
        print("outside-authorized-prefix")
        return
    exact = re.findall(r"name=='([^']+)'", query)
    prefix = re.search(r"starts_with\(name, '([^']+)'\)", query)
    # The inventory contains unrelated names and a same-name shared-RG record.
    rows = [(name, rg) for name in names] + [("unrelated-target", rg), (names[0], "shared-rg")]
    for name, group in rows:
        if group != rg or (exact and name not in exact) or (prefix and not name.startswith(prefix[1])):
            continue
        print(name)
if args[:2] == ["account", "set"]:
    assert value("--subscription") == "unit-sub", args
elif args[:2] == ["group", "exists"]:
    assert value("--subscription") == "unit-sub" and value("--name") == rg, args
    print("true")
elif args[:2] == ["resource", "list"]:
    assert value("--resource-group") == rg, args
elif args[:3] == ["cognitiveservices", "account", "list-deleted"]:
    assert value("--subscription") == "unit-sub", args
    if not ml:
        listed()
elif args[:3] == ["cognitiveservices", "account", "purge"]:
    assert value("--subscription") == "unit-sub" and value("--resource-group") == rg, args
    assert not ml and value("--name") in names, args
elif args[0] == "rest":
    url = urlsplit(value("--url"))
    assert url.netloc == "management.azure.com" and url.path.startswith("/subscriptions/unit-sub/"), args
    if args[args.index("--method") + 1].lower() == "get":
        # The shared deletion helper already observed live resource absence.
        print("ResourceNotFound: workspace no longer exists", file=sys.stderr)
        sys.exit(3)
    else:
        assert value("--method").lower() == "delete", args
        assert ml and url.path.rsplit("/", 1)[-1] in names, args
        assert f"/resourceGroups/{rg}/providers/Microsoft.MachineLearningServices/workspaces/" in url.path, args
        assert url.query == "api-version=2024-10-01&forceToPurge=true", args
        if os.environ.get("MOCK_PURGE_ERROR"):
            print(os.environ["MOCK_PURGE_ERROR"], file=sys.stderr)
            sys.exit(int(os.environ["MOCK_PURGE_EXIT"]))
        # az rest returns zero for accepted 200/202 and idempotent absent 204.
        assert os.environ.get("MOCK_PURGE_STATUS", "202") in ("200", "202", "204")
else:
    raise AssertionError(args)
''', encoding="utf-8")
    result = run_provider_bash(tmp_path, script(step), values,
                               'az() { "$MOCK_PYTHON" "$MOCK_SCRIPT" "$@"; }')
    calls = [json.loads(line) for line in (tmp_path / "mock-az-log").read_text().splitlines()]
    purges = [args for args in calls
              if args[:3] == ["cognitiveservices", "account", "purge"]
              or (args[0] == "rest" and args[args.index("--method") + 1].lower() == "delete")]
    return result, calls, purges


@pytest.mark.parametrize("platform", ["gha", "ado"])
@pytest.mark.parametrize("service", PURGE_NAMES)
def test_purge_all_confirmed_names_despite_stale_false_flags(tmp_path, platform, service):
    names = PURGE_NAMES[service]
    result, calls, purges = run_recorded_purge(tmp_path, platform, service, names)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(purges) == 2
    for name in names:
        assert sum(name in " ".join(call) for call in purges) == 1
    if service in ("aml", "aifProject", "aiHub"):
        assert not any(call[0] == "rest" and call[call.index("--method") + 1].lower() == "get"
                       for call in calls)
        assert all("/resourceGroups/unit-project002-sdc-dev-rg/" in call[call.index("--url") + 1]
                   and "api-version=2024-10-01&forceToPurge=true" in call[call.index("--url") + 1]
                   for call in purges)
        assert result.stdout.count("AML workspace purge request accepted:") == 2
    else:
        exact_queries = [call[call.index("--query") + 1] for call in calls
                         if "--query" in call and names[0] in call[call.index("--query") + 1]]
        assert exact_queries
        assert all(f"resourceGroup=='unit-project002-sdc-dev-rg'" in query for query in exact_queries)
        assert any(all(f"name=='{name}'" in query for name in names) for query in exact_queries)


@pytest.mark.parametrize("platform", ["gha", "ado"])
@pytest.mark.parametrize("service", ["aml", "openai"])
def test_unconfirmed_names_do_not_authorize_purge(tmp_path, platform, service):
    result, _, purges = run_recorded_purge(tmp_path, platform, service, PURGE_NAMES[service],
                                          **{service + "Deleted": "false"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert not purges


@pytest.mark.parametrize("platform", ["gha", "ado"])
@pytest.mark.parametrize("raw", [
    "not json", "$(amlDeletedNames)", "{}", "[]", '["other-project-workspace"]',
    '["aml-002-sdc-dev-good", "aml-002-sdc-dev-\\nmalicious"]',
    '["aml-002-sdc-dev-$(echo injected)"]', '["aml-002-sdc-dev-good", 3]',
])
def test_invalid_confirmed_names_fail_before_any_purge(tmp_path, platform, raw):
    result, _, purges = run_recorded_purge(tmp_path, platform, "aml", PURGE_NAMES["aml"],
                                          amlDeletedNames=raw)
    assert result.returncode != 0
    assert not purges
    assert "Invalid" in result.stderr


@pytest.mark.parametrize("platform", ["gha", "ado"])
def test_positive_legacy_single_name_remains_eligible(tmp_path, platform):
    name = PURGE_NAMES["aml"][0]
    result, _, purges = run_recorded_purge(tmp_path, platform, "aml", [name], amlDeletedNames="")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(purges) == 1 and name in " ".join(purges[0])


@pytest.mark.parametrize("platform,service", [("gha", "openai"), ("gha", "aiFoundryV2"), ("ado", "aiFoundryV2")])
@pytest.mark.parametrize("failure", ["MOCK_LIST_ERROR", "MOCK_UNEXPECTED_TARGET"])
def test_purge_discovery_failures_are_not_empty_success(tmp_path, platform, service, failure):
    result, _, purges = run_recorded_purge(tmp_path, platform, service, PURGE_NAMES[service],
                                          **{failure: "true"})
    assert result.returncode != 0
    assert not purges


def test_recorded_github_names_override_broad_predelete_discovery(tmp_path):
    result, _, purges = run_recorded_purge(tmp_path, "gha", "aml", PURGE_NAMES["aml"],
                                          aif_delete_before_amlExists="true")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(purges) == 2


def test_ado_deleted_names_are_environment_inputs_not_shell_macros():
    step = next(step for step in steps("ado") if step.get("name") == "purgeSoftDeleted")
    for service in PURGE_NAMES:
        key = service + "DeletedNames"
        assert step["env"][key] == "$(" + key + ")"
        assert "$(" + key + ")" not in script(step)


@pytest.mark.parametrize("platform", ["gha", "ado"])
@pytest.mark.parametrize("service", ["aml", "aifProject", "aiHub"])
@pytest.mark.parametrize("error,exit_code", [("AuthorizationFailed: HTTP 403", 37), ("ServiceUnavailable: HTTP 503", 42)])
def test_recorded_ml_purge_failure_propagates_native_exit(tmp_path, platform, service, error, exit_code):
    result, calls, purges = run_recorded_purge(
        tmp_path, platform, service, PURGE_NAMES[service],
        MOCK_PURGE_ERROR=error, MOCK_PURGE_EXIT=str(exit_code),
    )
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert error in result.stderr
    assert len(purges) == 1
    assert "purge request accepted" not in result.stdout
    assert not any(call[0] == "rest" and call[call.index("--method") + 1].lower() == "get"
                   for call in calls)


@pytest.mark.parametrize("platform", ["gha", "ado"])
@pytest.mark.parametrize("status", ["200", "202", "204"])
def test_recorded_ml_purge_reports_request_acceptance_not_completion(tmp_path, platform, status):
    result, _, purges = run_recorded_purge(
        tmp_path, platform, "aml", [PURGE_NAMES["aml"][0]], MOCK_PURGE_STATUS=status,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(purges) == 1
    assert f"AML workspace purge request accepted: {PURGE_NAMES['aml'][0]}" in result.stdout
    assert "AML workspace purge completed" not in result.stdout


@pytest.mark.parametrize("platform", ["gha", "ado"])
def test_recorded_ml_project_purge_precedes_hub(tmp_path, platform):
    project, hub = PURGE_NAMES["aifProject"][0], PURGE_NAMES["aiHub"][0]
    result, _, purges = run_recorded_purge(
        tmp_path, platform, "aiHub", [hub, project],
        aiHubDeletedNames=json.dumps([hub]),
        aifProjectDeleted="true", aifProjectDeletedNames=json.dumps([project]),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(purges) == 2
    assert f"/workspaces/{project}?" in purges[0][purges[0].index("--url") + 1]
    assert f"/workspaces/{hub}?" in purges[1][purges[1].index("--url") + 1]
