"""Shell half of the aif-160 fix: the managed environment leaves only after its bound jobs and apps.

Kept apart from the helper tests because their autouse fixture forbids every subprocess, including Git Bash.
"""

from unit.test_project_deletion_shell import run_block


SHELL_PRELUDE = r"""
projectNumber=002; locationSuffix=sdc; envName=dev; projectName=prj002
projectResourceGroup=unit-project002-sdc-dev-rg
dev_test_prod_sub_id=11111111-1111-4111-8111-111111111111
deleteAllServicesForProject=true; enableContainerApps=true; containerAppsEnvExists=false
delete_private_endpoints() { printf 'PRIVATE_ENDPOINTS:%s\n' "$1"; }
az() { echo "Unexpected az invocation: $*" >&2; return 97; }
"""
ENV_BLOCK = ("# CONTAINER APPS ENVIRONMENT -", "# LOGIC APPS -")


def test_shell_deletes_bound_jobs_and_apps_through_the_helper_before_the_environment():
    result = run_block(*ENV_BLOCK, SHELL_PRELUDE + r"""
aif_delete() {
  printf 'HELPER:%s\n' "$*" >&2
  if [[ "$1" == names ]]; then echo aca-env-prj002-sdc-dev-salt-001; fi
}
""")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [line[len("HELPER:"):] for line in result.stderr.splitlines() if line.startswith("HELPER:")]
    assert calls == [
        "names --resource-type Microsoft.App/managedEnvironments --prefix aca-env-prj002-sdc-dev",
        "aca-environment-children --name aca-env-prj002-sdc-dev-salt-001",
        "resource --resource-type Microsoft.App/managedEnvironments --name aca-env-prj002-sdc-dev-salt-001",
    ]
    assert "Unexpected az invocation" not in result.stderr
    assert "##vso[task.setvariable variable=containerAppsEnvExists]false" in result.stdout


def test_shell_stops_before_the_environment_when_a_bound_job_is_not_confirmed_gone():
    result = run_block(*ENV_BLOCK, SHELL_PRELUDE + r"""
aif_delete() {
  printf 'HELPER:%s\n' "$*" >&2
  case "$1" in
    names) echo aca-env-prj002-sdc-dev-salt-001 ;;
    aca-environment-children) echo 'NestedResourcesRemain: job still bound' >&2; return 5 ;;
  esac
}
""")
    assert result.returncode == 5
    assert "resource --resource-type Microsoft.App/managedEnvironments" not in result.stderr
    assert "PRIVATE_ENDPOINTS:" not in result.stdout
    assert "variable=containerAppsEnvExists]false" not in result.stdout
