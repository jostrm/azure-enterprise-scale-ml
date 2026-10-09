"""Offline contracts for the shared ADO/GHA deletion entry point."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "delete-services-if-disabled.sh"


def run_block(start, end, prelude):
    text = SCRIPT.read_text(encoding="utf-8")
    block = text.split(start, 1)[1].split("\n", 1)[1].split(end, 1)[0]
    helper = "declare -A aif_deleted_names\n" + "\n".join(
        name + "() {" + text.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
        for name in ("aif_service_may_exist", "record_deleted_resource", "delete_arm_services",
                     "delete_orphan_service_endpoints")
    )
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    if not bash.is_file():
        pytest.skip("Git Bash or Bash is required for offline shell contracts")
    with tempfile.TemporaryDirectory(prefix=".deletion-shell-", dir=ROOT) as directory:
        script = Path(directory) / "case.sh"
        script.write_text("set -eo pipefail\n" + helper + prelude + "\n" + block, encoding="utf-8", newline="\n")
        return subprocess.run(
            [str(bash), "--noprofile", "--norc", script.as_posix()],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
        )


COMMON = r"""
projectNumber=002; locationSuffix=sdc; envName=dev
projectResourceGroup=unit-project002-sdc-dev-rg; projectName=prj002
dev_test_prod_sub_id=11111111-1111-4111-8111-111111111111
deleteAllServicesForProject=false; deleteAllForProject=false
preserve_foundation=false
delete_private_endpoints() { printf 'PRIVATE_ENDPOINTS:%s\n' "$1"; }
az() { echo "Unexpected extension invocation: $*" >&2; return 97; }
aif_delete() {
  printf 'HELPER:%s\n' "$*" >&2
  if [[ "$1" == names ]]; then printf '%s\n' "$MOCK_RESOURCE"; fi
}
"""


@pytest.mark.parametrize("enabled,expected", [("false", True), ("False", True), ("true", False)])
def test_databricks_uses_live_inventory_not_stale_exists_flag(enabled, expected):
    result = run_block(
        "# DATABRICKS -", "# AI FOUNDRY V1 PROJECT -",
        COMMON + f"\nenableDatabricks={enabled}; databricksExists=false; MOCK_RESOURCE=dbx-002-sdc-dev-salt-001\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert ("HELPER:resource --resource-type Microsoft.Databricks/workspaces --name dbx-002-sdc-dev-salt-001"
            in result.stderr) is expected
    assert "Unexpected extension" not in result.stderr


def test_failed_databricks_inventory_stops_before_any_delete():
    result = run_block(
        "# DATABRICKS -", "# AI FOUNDRY V1 PROJECT -",
        COMMON + """
enableDatabricks=false; databricksExists=true
aif_delete() { echo 'AuthorizationFailed: inventory unavailable' >&2; return 9; }
""",
    )
    assert result.returncode != 0
    assert "AuthorizationFailed" in result.stderr
    assert "PRIVATE_ENDPOINTS:" not in result.stdout


def test_databricks_absent_is_a_confirmed_noop():
    result = run_block(
        "# DATABRICKS -", "# AI FOUNDRY V1 PROJECT -",
        COMMON + "\nenableDatabricks=false; databricksExists=true; MOCK_RESOURCE=''\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HELPER:names" in result.stderr
    assert "HELPER:resource" not in result.stderr
    assert "PRIVATE_ENDPOINTS:" not in result.stdout


def test_ml_cleanup_never_invokes_or_installs_ml_extension():
    result = run_block(
        "# AZURE MACHINE LEARNING -", "# DATA FACTORY -",
        COMMON + "\nenableAzureMachineLearning=false; amlExists=false; MOCK_RESOURCE=aml-002-sdc-dev-salt-001\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HELPER:resource --resource-type Microsoft.MachineLearningServices/workspaces --name aml-002-sdc-dev-salt-001" in result.stderr
    assert "##vso[task.setvariable variable=amlActualName]aml-002-sdc-dev-salt-001" in result.stdout
    assert "##vso[task.setvariable variable=amlDeleted]true" in result.stdout
    assert "az ml " not in SCRIPT.read_text(encoding="utf-8")


def test_already_deleting_foundry_account_skips_child_mutations_and_waits():
    result = run_block(
        "# AI FOUNDRY V2 ACCOUNT", "# AI SERVICES ACCOUNT",
        COMMON + """
enableAIFoundry=false; aiFoundryV2Exists=false
aif_delete() {
  printf 'HELPER:%s\\n' "$*" >&2
  case "$1" in
    names) echo aif2-unit ;;
    state) echo deleting ;;
  esac
}
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HELPER:resource --resource-type Microsoft.CognitiveServices/accounts --name aif2-unit" in result.stderr
    assert "Unexpected extension invocation" not in result.stderr


def test_resource_failure_stops_before_next_matching_resource():
    result = run_block(
        "# DATABRICKS -", "# AI FOUNDRY V1 PROJECT -",
        COMMON + """
enableDatabricks=false; databricksExists=false
aif_delete() {
  if [[ "$1" == names ]]; then printf '%s\\n' dbx-first dbx-second
  else echo 'timed out waiting for dbx-first' >&2; return 6; fi
}
""",
    )
    assert result.returncode == 6
    assert "PRIVATE_ENDPOINTS:dbx-first" in result.stdout
    assert "PRIVATE_ENDPOINTS:dbx-second" not in result.stdout
    assert "variable=databricksExists]false" not in result.stdout


def test_all_confirmed_ml_names_survive_for_downstream_purge():
    result = run_block(
        "# AZURE MACHINE LEARNING -", "# DATA FACTORY -",
        COMMON + """
enableAzureMachineLearning=false; amlExists=false
aif_delete() {
  if [[ "$1" == names ]]; then printf '%s\\n' aml-first aml-second; fi
}
""",
    )
    assert result.returncode == 0, result.stderr
    lists = re.findall(r"variable=amlDeletedNames\](.*)", result.stdout)
    assert json.loads(lists[-1]) == ["aml-first", "aml-second"]


@pytest.mark.parametrize("start,end,enabled,exists,command,name", [
    ("# WEB APP -", "# FUNCTION APP -", "enableWebApp", "webAppExists", "webapp list", "webapp-prj002-sdc-dev-001"),
    ("# POSTGRESQL -", "# REDIS CACHE -", "enablePostgreSQL", "postgreSQLExists", "postgres flexible-server", "pg-prj002-sdc-dev-001"),
    ("# REDIS CACHE -", "# SQL DATABASE -", "enableRedisCache", "redisExists", "redis list", "redis-prj002-sdc-dev-001"),
])
def test_services_only_uses_live_lookup_despite_stale_flags(start, end, enabled, exists, command, name):
    result = run_block(start, end, COMMON + f"""
deleteAllServicesForProject=true; preserve_foundation=true
{enabled}=true; {exists}=false; byoASEv3=true
sleep() {{ :; }}
az() {{
  printf 'AZ:%s\\n' "$*" >&2
  if [[ "$1 $2" == "{command}" && "$*" == *list* ]]; then echo "{name}"; fi
}}
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AZ:" + command in result.stderr
    assert "delete" in result.stdout + result.stderr
    assert name in result.stdout + result.stderr


def test_failed_legacy_lookup_pipeline_is_not_silently_empty():
    result = run_block("# REDIS CACHE -", "# SQL DATABASE -", COMMON + """
deleteAllServicesForProject=true; enableRedisCache=false; redisExists=false
az() { echo 'AuthorizationFailed' >&2; return 7; }
""")
    assert result.returncode == 7
    assert "AuthorizationFailed" in result.stderr


@pytest.mark.parametrize("parent_state,endpoint_state,deletes", [
    ("absent", "absent", 2), ("succeeded", "absent", 0), ("deleting", "absent", 0),
    ("absent", "deleting", 1),
])
def test_foundation_preservation_cleans_only_confirmed_service_orphans(parent_state, endpoint_state, deletes):
    result = run_block(
        "# Retain GHA's service-owned orphan cleanup", "# COMPLETE DELETE MODE:",
        COMMON + f"""
preserve_foundation=true
aif_delete() {{
  printf 'HELPER:%s\\n' "$*" >&2
  if [[ "$1" == names ]]; then
    if [[ "$*" == *privateEndpoints* ]]; then echo aif2-unit-pend
    else echo aif2-unit-pend-nic; fi
  elif [[ "$1" == state ]]; then
    if [[ "$*" == *privateEndpoints* ]]; then echo {endpoint_state}
    else echo {parent_state}; fi
  fi
}}
""",
    )
    assert result.returncode == 0, result.stderr
    # The fixture returns the same pair for each legacy prefix, so both passes are covered.
    assert result.stderr.count("HELPER:resource") == deletes * 2


def test_ultra_mode_cannot_report_success_after_group_failure():
    result = run_block(
        "# ULTRA DELETE MODE: deleteAllForProject=true", 'echo "=== Deletion task completed ==="',
        COMMON + """
deleteAllForProject=true
aif_delete() { echo 'ResourceGroupDeletionBlocked: ApplianceBeingDeleted' >&2; return 1; }
""",
    )
    assert result.returncode != 0
    assert "ResourceGroupDeletionBlocked" in result.stderr
    assert "ULTRA DELETE MODE COMPLETED" not in result.stdout
    assert "running in background" not in result.stdout


def test_full_cleanup_verifies_network_and_group_completion():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'aif_delete group --confirm-resource-group "$projectResourceGroup"' in text
    assert 'aif_delete verify-network --network-resource-group "$commonResourceGroup"' in text
    assert 'rg_exists=$(az group exists --name "$projectResourceGroup" 2>/dev/null || echo "false")' not in text
    assert text.index('aif_delete group --confirm-resource-group "$projectResourceGroup"') < text.index(
        "variable=aifProjectGroupDeletionConfirmed]true")


@pytest.mark.parametrize("preserve,full,expected", [
    ("true", "false", "true"), ("True", "false", "true"),
    ("true", "true", "false"), ("false", "false", "false"), ("", "false", "false"),
])
def test_foundation_retention_normalizes_and_full_teardown_overrides(preserve, full, expected):
    result = run_block(
        "\npreserve_foundation=", "\ndeletion_script_dir=",
        COMMON + f'\nAIF_DELETE_PRESERVE_FOUNDATION="{preserve}"; deleteAllForProject="{full}"\n'
        + 'preserve_foundation=$(echo "${AIF_DELETE_PRESERVE_FOUNDATION:-false}" | tr \'[:upper:]\' \'[:lower:]\')\n'
        + 'trap \'echo "$preserve_foundation"\' EXIT\n',
    )
    assert result.returncode == 0 and result.stdout.strip() == expected, result.stderr


def test_preserved_foundation_blocks_vm_acr_and_complete_sweep():
    for start, end in (
        ("# VM / DSVM -", "# ACR PROJECT -"),
        ("# ACR PROJECT -", "# BING SEARCH"),
        ("# COMPLETE DELETE MODE: deleteAllServicesForProject=true", "# ULTRA DELETE MODE:"),
    ):
        result = run_block(start, end, COMMON + """
deleteAllServicesForProject=true; preserve_foundation=true
vmExists=true; acrProjectExists=true
""")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Unexpected extension" not in result.stderr
        assert "HELPER:" not in result.stderr


def test_windows_arm_ids_are_safe_before_first_azure_command():
    prefix = SCRIPT.read_text(encoding="utf-8").split("az account set", 1)[0]
    assert "export MSYS_NO_PATHCONV=1" in prefix
    assert "export MSYS2_ARG_CONV_EXCL='*'" in prefix
    assert 'cygpath -m "$deletion_script_dir"' in SCRIPT.read_text(encoding="utf-8")


@pytest.mark.parametrize("exit_code,status", [(0, "succeeded"), (7, "failed")])
def test_script_outcome_distinguishes_whole_task_from_last_helper(tmp_path, exit_code, status):
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    if not bash.is_file():
        pytest.skip("Bash required")
    source = SCRIPT.read_text(encoding="utf-8")
    callback = "aif_delete_exit() {" + source.split("aif_delete_exit() {", 1)[1].split("\ntrap ", 1)[0]
    result = subprocess.run(
        [str(bash), "--noprofile", "--norc", "-c",
         COMMON + "\n" + callback + f"\naif_delete_exit {exit_code}\n"],
        env={**os.environ, "AIF_DELETE_REPORT_DIR": str(tmp_path)},
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == exit_code, result.stderr
    report = json.loads((tmp_path / "deletion-result.json").read_text(encoding="utf-8"))
    assert report["status"] == status and report["exitCode"] == exit_code


def test_no_delete_mode_remains_a_safe_noop():
    bash = (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if os.name == "nt" else Path(shutil.which("bash") or "/unavailable"))
    if not bash.is_file():
        pytest.skip("Bash required")
    result = subprocess.run(
        [str(bash), "--noprofile", "--norc", "-c",
         'az() { [[ "$1 $2" == "account set" ]] || return 99; }; '
         f"source {shlex.quote(SCRIPT.as_posix())}"],
        cwd=ROOT, env={**os.environ, "enableDeleteForDisabledResources": "false",
                      "deleteAllForProject": "false", "deleteAllServicesForProject": "false"},
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Skipping all resource deletion" in result.stdout
