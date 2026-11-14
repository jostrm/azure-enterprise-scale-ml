"""Offline contract: a transient Azure error does not fail a deployment step of the common or project run.

Before: in the GitHub workflows a single `az deployment sub create` that met throttling, a 5xx, "another operation
is in progress" or an identity that had not replicated yet failed the job and cost a whole run attempt; only 69b
had its own loop. In Azure DevOps five tasks retried on any failure (retryCountOnTaskFailure) and the others not
at all. Now every deployment step on the scenario 1 and 3 paths (infra-common, infra-project) either keeps the
retry it had or runs through `aif_retry_deployment` (scripts/modules/aif-retry.sh): transient errors only,
at most 4 attempts, the same deployment name and inputs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
SETTINGS = BICEP / "copy_to_local_settings"
GHA_PROJECT = SETTINGS / "github-actions/infra-project-phase.yml"
GHA_COMMON = SETTINGS / "github-actions/infra-common.yml"
ADO_PROJECT = SETTINGS / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
ADO_COMMON = SETTINGS / "azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-1-aif-cmn.yaml"
HELPER = BICEP / "scripts/modules/aif-retry.sh"
GHA_HELPER_PATH = "azure-enterprise-scale-ml/environment_setup/aifactory/bicep/scripts/modules/aif-retry.sh"
ADO_HELPER_PATH = "scripts/modules/aif-retry.sh"
DEPLOY = "az deployment sub create"

# Steps that already had a retry of their own; it stays as it is.
OWN_RETRY = {
    "68-integration": "deploy-integration-with-retry.py",       # Logic Apps plan capacity, 3 attempts
    "69b-aifoundry-2025-2ndOption-AccountUpdate": "for attempt in 1 2 3 4 5 6",   # RequestConflict loop (GitHub)
}


def gha_steps(path: Path) -> list[tuple[str, str, str]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    found = []
    for job_name, job in document["jobs"].items():
        for step in job.get("steps", []):
            if DEPLOY in (step.get("run") or ""):
                found.append((job_name, step["name"], step["run"]))
    return found


def ado_tasks(path: Path) -> list[tuple[str, str, dict]]:
    found = []
    for task in yaml.safe_load(path.read_text(encoding="utf-8"))["steps"]:
        script = (task.get("inputs") or {}).get("inlineScript") or ""
        if DEPLOY in script:
            found.append((task["displayName"], script, task))
    return found


GHA = [(path, *step) for path in (GHA_PROJECT, GHA_COMMON) for step in gha_steps(path)]
ADO = [(path, *task) for path in (ADO_PROJECT, ADO_COMMON) for task in ado_tasks(path)]


def wired(script: str, name: str, helper_path: str) -> bool:
    lines = [line.strip() for line in script.splitlines()]
    command = f'aif_retry_deployment --label "{name}" -- {DEPLOY} \\'
    if lines.count(command) != 1 or any(line.startswith(DEPLOY) for line in lines):
        return False
    return lines[lines.index(command) - 1] == f"source {helper_path}"


def test_the_expected_steps_exist():
    assert len(GHA) == 22 and len(ADO) == 16, (len(GHA), len(ADO))
    assert HELPER.is_file()


@pytest.mark.parametrize("path, job, name, script", GHA, ids=[f"{p.stem}:{j}:{n}" for p, j, n, _ in GHA])
def test_every_github_deployment_step_retries_transient_errors(path, job, name, script):
    if name in OWN_RETRY:
        assert OWN_RETRY[name] in script, f"{name} lost the retry it had"
        return
    assert wired(script, name, GHA_HELPER_PATH), (
        f"{path.name} step {name}: the deployment must run as\n  source {GHA_HELPER_PATH}\n"
        f'  aif_retry_deployment --label "{name}" -- {DEPLOY} \\')


@pytest.mark.parametrize("path, name, script, task", ADO, ids=[f"{p.stem}:{n}" for p, n, _, _ in ADO])
def test_every_azure_devops_deployment_task_has_a_retry(path, name, script, task):
    inputs = task["inputs"]
    assert inputs["scriptType"] == "bash"
    if task.get("retryCountOnTaskFailure"):
        return                                    # the task-level retry that was there stays
    if name in OWN_RETRY:
        assert OWN_RETRY[name] in script, f"{name} lost the retry it had"
        return
    assert str(inputs["workingDirectory"]).rstrip("'").endswith("/environment_setup/aifactory/bicep"), (
        f"{name}: the helper path is relative to the bicep folder")
    assert wired(script, name, ADO_HELPER_PATH), (
        f"{path.name} task {name}: the deployment must run as\n  source {ADO_HELPER_PATH}\n"
        f'  aif_retry_deployment --label "{name}" -- {DEPLOY} \\')


def test_task_level_retries_were_not_removed():
    retried = {name: task["retryCountOnTaskFailure"] for _, name, _, task in ADO if task.get("retryCountOnTaskFailure")}
    assert retried == {"62-core-infrastructure": 2, "63-cognitive-services": 2,
                       "69a-aifoundry-2025-2ndOption-Account": 3, "69b-aifoundry-2025-2ndOption-AccountUpdate": 2}


# ---- behavior: run real step scripts against a fake az ---------------------------------------------------------------

ERRORS = {
    "busy": '{"code": "AnotherOperationInProgress", "message": "Another operation on this or dependent resource is in progress."}',
    "identity": '{"code": "PrincipalNotFound", "message": "Principal 0f0f does not exist in the directory."}',
    "throttled": "ERROR: (TooManyRequests) Too many requests. Please retry after 30 seconds.",
    "invalid": '{"code": "InvalidTemplateDeployment", "message": "The template deployment failed because of policy violation."}',
    "active": ('{"code": "DeploymentActive", "message": "Unable to edit or replace deployment: previous deployment '
               "from '11/14/2026 8:00:00 AM' is still active (expiration time is '11/21/2026 8:00:00 AM').\"}"),
}
# $OUTCOMES: one word per deployment call (ok or a key of ERRORS). Calls and sleeps are logged; sleeps return at once.
FAKE = r"""
calls="$WORK/calls"; : > "$calls"
sleep() { echo "sleep $*" >> "$calls"; }
az() {
  echo "az $*" >> "$calls"
  case "$1 $2 $3" in
    "account set "*) return 0 ;;
    "deployment sub create")
      n=$(grep -c '^az deployment sub create' "$calls")
      outcome=$(echo "$OUTCOMES" | cut -d' ' -f"$n")
      if [ "${outcome:-ok}" = ok ]; then echo '{"properties":{"provisioningState":"Succeeded"}}'; return 0; fi
      echo "ERROR: $(cat "$WORK/errors/$outcome")" >&2; return 1 ;;
    "deployment sub show")
      # The earlier deployment with the same name: its states come from $STATES, one word per look.
      n=$(grep -c '^az deployment sub show' "$calls")
      state=$(echo "${STATES:-}" | cut -d' ' -f"$n")
      [ "$state" != lookup-fails ] || return 3
      echo "${state:-Succeeded}" ;;
    *) echo "unexpected az $*" >&2; return 9 ;;
  esac
}
"""
# Only steps whose lines before the deployment are plain shell (no other script or az call) run here.
SIMPLE_PREAMBLE = re.compile(r"^(?:#.*|set -[a-z]+(?: pipefail)?|az account set .*|source \S+|)$")


def bash_executable() -> str | None:
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


def runnable(script: str) -> bool:
    lines = [line.strip() for line in script.splitlines()]
    start = next(index for index, line in enumerate(lines) if DEPLOY in line)
    return all(SIMPLE_PREAMBLE.match(line) for line in lines[:start])


def run_step(tmp_path: Path, script: str, outcomes: str, *, strict_shell: bool, directory: Path, states: str = ""):
    bash = bash_executable()
    if not bash:
        pytest.skip("bash is required (Git Bash on Windows)")
    errors = tmp_path / "errors"
    errors.mkdir()
    for name, text in ERRORS.items():
        (errors / name).write_text(text + "\n", encoding="utf-8")
    result = subprocess.run(
        [bash, "--noprofile", "--norc", *(["-eo", "pipefail"] if strict_shell else []), "-s"],
        input=(FAKE + script).encode("utf-8"), capture_output=True, check=False, timeout=60, cwd=directory,
        env={key: value for key, value in os.environ.items() if not key.startswith(("AIF_", "GITHUB_", "TF_BUILD"))}
        | {"WORK": tmp_path.as_posix(), "OUTCOMES": outcomes, "STATES": states})
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    deployments = [line for line in calls if line.startswith("az deployment sub create")]
    return result.returncode, result.stdout.decode() + result.stderr.decode(), deployments, calls


def github_script(script: str) -> str:
    # The step runs in the consumer root, where the accelerator is the submodule folder; here it is this checkout.
    script = script.replace("azure-enterprise-scale-ml/", ROOT.as_posix() + "/")
    # GitHub replaces every ${{ ... }} expression before bash sees the script.
    return re.sub(r"\$\{\{.*?\}\}", "unused", script)


def azure_devops_script(script: str) -> str:
    # Azure DevOps expands $(name) macros before bash sees the script.
    return re.sub(r"\$\((?!mktemp\b|pwd\b|date\b)[A-Za-z_][\w.]*\)", "unused", script)


GHA_RUNNABLE = [(path, name, script) for path, _, name, script in GHA if name not in OWN_RETRY and runnable(script)]
ADO_RUNNABLE = [(path, name, script) for path, name, script, task in ADO
                if name not in OWN_RETRY and not task.get("retryCountOnTaskFailure") and runnable(script)]


def test_enough_real_steps_are_exercised():
    assert len({name for _, name, _ in GHA_RUNNABLE}) >= 7, [name for _, name, _ in GHA_RUNNABLE]
    assert len({name for _, name, _ in ADO_RUNNABLE}) >= 5, [name for _, name, _ in ADO_RUNNABLE]


@pytest.mark.parametrize("path, name, script", GHA_RUNNABLE, ids=[f"{p.stem}:{n}:{i}" for i, (p, n, _) in enumerate(GHA_RUNNABLE)])
@pytest.mark.parametrize("error", ["busy", "identity", "throttled"])
def test_a_github_step_redeploys_after_a_transient_error(tmp_path, path, name, script, error):
    code, output, deployments, calls = run_step(tmp_path, github_script(script), f"{error} ok", strict_shell=True,
                                                directory=tmp_path)
    assert code == 0, output[-600:]
    assert len(deployments) == 2 and deployments[0] == deployments[1], "the same deployment is run again"
    assert sum(1 for line in calls if line.startswith("sleep ")) == 1
    assert f"'{name}' attempt 1 of 4" in output


@pytest.mark.parametrize("path, name, script", GHA_RUNNABLE[:4], ids=[f"{p.stem}:{n}:{i}" for i, (p, n, _) in enumerate(GHA_RUNNABLE[:4])])
def test_a_github_step_fails_at_once_on_any_other_error_and_is_bounded(tmp_path, path, name, script):
    code, output, deployments, calls = run_step(tmp_path, github_script(script), "invalid ok", strict_shell=True,
                                                directory=tmp_path)
    assert code != 0 and len(deployments) == 1, output[-600:]
    assert not [line for line in calls if line.startswith("sleep ")]
    bounded = tmp_path / "bounded"
    bounded.mkdir()
    code, output, deployments, _ = run_step(bounded, github_script(script), " ".join(["busy"] * 12), strict_shell=True,
                                            directory=bounded)
    assert code != 0 and len(deployments) == 4, output[-600:]
    assert f"'{name}' failed after 4 attempts" in output and "AnotherOperationInProgress" in output


@pytest.mark.parametrize("path, name, script", ADO_RUNNABLE, ids=[f"{p.stem}:{n}" for p, n, _ in ADO_RUNNABLE])
def test_an_azure_devops_task_redeploys_after_a_transient_error_and_not_otherwise(tmp_path, path, name, script):
    script = azure_devops_script(script)
    code, output, deployments, _ = run_step(tmp_path, script, "busy ok", strict_shell=False, directory=BICEP)
    assert code == 0 and len(deployments) == 2 and deployments[0] == deployments[1], output[-600:]
    other = tmp_path / "other"
    other.mkdir()
    code, output, deployments, calls = run_step(other, script, "invalid ok", strict_shell=False, directory=BICEP)
    assert len(deployments) == 1 and not [line for line in calls if line.startswith("sleep ")], output[-600:]


# ---- self-heal: a deployment with the same name that an earlier run left active ----------------------------------------

def first_github_step() -> tuple[str, str]:
    _, name, script = GHA_RUNNABLE[0]
    return name, github_script(script)


def test_a_deployment_left_active_by_an_earlier_run_is_waited_for_and_then_replaced(tmp_path):
    """A cancelled or timed-out run can leave its deployment running in Azure. The next run uses the same deployment
    name and is refused with DeploymentActive. The step now waits for the earlier deployment to end and deploys again."""
    name, script = first_github_step()
    code, output, deployments, calls = run_step(tmp_path, script, "active ok", strict_shell=True, directory=tmp_path,
                                                states="Running Accepted Running Succeeded")
    assert code == 0, output[-800:]
    assert len(deployments) == 2
    looks = [line for line in calls if line.startswith("az deployment sub show")]
    assert len(looks) == 4, calls
    deployment_name = re.search(r"--name (\S+)", deployments[0]).group(1)
    subscription = re.search(r"--subscription (\S+)", deployments[0]).group(1)
    assert all(f"--name {deployment_name}" in look and f"--subscription {subscription}" in look for look in looks)
    assert "still active" in output and "is now Succeeded" in output
    # The looks come before the second deployment, about every 10 s; then the ordinary failure backoff.
    order = [line.split()[0] + " " + " ".join(line.split()[1:4]) for line in calls if not line.startswith("az account")]
    assert order.index("az deployment sub show") < len(order) - 1 and order[-1] == "az deployment sub create"
    assert [line for line in calls if line == "sleep 10"], calls


def test_the_wait_for_an_active_deployment_is_bounded(tmp_path):
    name, script = first_github_step()
    code, output, deployments, calls = run_step(
        tmp_path, "export AIF_DEPLOY_ACTIVE_WAIT_SECONDS=60\n" + script, " ".join(["active"] * 9),
        strict_shell=True, directory=tmp_path, states=" ".join(["Running"] * 500))
    assert code != 0 and len(deployments) == 4, output[-600:]
    looks = [line for line in calls if line.startswith("az deployment sub show")]
    assert 3 * 6 <= len(looks) <= 3 * 7, len(looks)       # 60 s of 10 s looks before each of the 3 new attempts
    assert "DeploymentActive" in output and "failed after 4 attempts" in output


def test_a_failed_lookup_does_not_hold_the_retry_up(tmp_path):
    name, script = first_github_step()
    code, output, deployments, calls = run_step(tmp_path, script, "active ok", strict_shell=True, directory=tmp_path,
                                                states="lookup-fails")
    assert code == 0 and len(deployments) == 2, output[-600:]
    assert len([line for line in calls if line.startswith("az deployment sub show")]) == 1
