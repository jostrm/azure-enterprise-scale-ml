"""Offline contract: ADO task 69a-Poll-Deployment-Status checks the deployment from the start.

The task used to sleep 10 minutes (15 with agent network injection) before its first look at the Foundry account
deployment, and then looked once a minute. A deployment that finished early was only noticed when the blind wait
was over. The task now polls the deployment state every 10 seconds from the start and:

- returns once the deployment has been Succeeded for 300 s (the rehydration time the GitHub twin gives the
  account in step 69-Rehydrate), and never later than the old first check would have returned;
- acts on Failed or Canceled no earlier than before, so the self-heal purge and retry that follow keep the
  time the Microsoft-managed infrastructure had to stabilise;
- keeps the caps of 20 and 30 minutes, where a still-running deployment is treated as success.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
ADO = (ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/"
       "esml-infra-project/jobs/job-2-genai-services.yaml")
TASK = "69a-Poll-Deployment-Status"
SUCCEEDED = "##vso[task.setvariable variable=foundry_69a_deployment_succeeded]true"
REHYDRATE = 300
POLL = 10

# Fake az/sleep on a fake clock: `sleep` advances it and resets bash's SECONDS to it, so the time the test itself
# takes never leaks into the script's arithmetic. The deployment is Running until $SUCCEED_AT or $FAIL_AT seconds.
FAKE = r"""
calls="$WORK/calls"; : > "$calls"
fake_now=0; SECONDS=0
sleep() { echo "sleep $1" >> "$calls"; fake_now=$((fake_now + $1)); SECONDS=$fake_now; }
az() {
  echo "az@$fake_now $*" >> "$calls"
  case "$1 $2 $3" in
    "account set "*) return 0 ;;
    "deployment sub show")
      case "$*" in *properties.error*) echo '{}'; return 0 ;; esac
      if [ -n "${SUCCEED_AT:-}" ] && [ "$fake_now" -ge "$SUCCEED_AT" ]; then echo Succeeded
      elif [ -n "${FAIL_AT:-}" ] && [ "$fake_now" -ge "$FAIL_AT" ]; then echo Failed
      else echo Running; fi ;;
    "deployment sub operation") return 0 ;;
    *) echo "unexpected az $*" >&2; return 9 ;;
  esac
}
"""


def bash_executable() -> str | None:
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


def task_script(injection_disabled: bool) -> str:
    steps = yaml.safe_load(ADO.read_text(encoding="utf-8"))["steps"]
    script = next(s for s in steps if s.get("displayName") == TASK)["inputs"]["inlineScript"]
    script = script.replace("$(disableAgentNetworkInjection)", "true" if injection_disabled else "false")
    # Azure DevOps macros $(name) are replaced before bash runs; shell substitutions keep their spaces.
    return re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)", "x", script)


def run_task(*, injection_disabled: bool, succeed_at: int | None = None, fail_at: int | None = None):
    bash = bash_executable()
    if bash is None:
        pytest.skip("bash is required (Git Bash on Windows)")
    env = os.environ | {"SUCCEED_AT": "" if succeed_at is None else str(succeed_at),
                        "FAIL_AT": "" if fail_at is None else str(fail_at)}
    with tempfile.TemporaryDirectory() as work:
        result = subprocess.run(
            [bash, "--noprofile", "--norc", "-s"],
            input=(FAKE + task_script(injection_disabled)).encode("utf-8"),
            env=env | {"WORK": work.replace("\\", "/")}, capture_output=True, check=False, timeout=300,
        )
        calls = Path(work, "calls").read_text(encoding="utf-8").splitlines()
    output = result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
    sleeps = [int(c.split()[1]) for c in calls if c.startswith("sleep ")]
    return result.returncode, output, sleeps


def test_early_success_returns_after_the_rehydration_time_not_after_the_blind_wait():
    code, output, sleeps = run_task(injection_disabled=True, succeed_at=120)
    assert code == 0, output
    assert SUCCEEDED in output
    # Old behaviour: 600 s. New: noticed within one poll of 120 s, then 300 s of rehydration.
    assert 120 + REHYDRATE <= sum(sleeps) <= 120 + REHYDRATE + POLL, sum(sleeps)


def test_success_is_never_reported_later_than_the_old_first_check():
    code, output, sleeps = run_task(injection_disabled=True, succeed_at=540)
    assert code == 0, output
    assert SUCCEEDED in output
    assert 540 <= sum(sleeps) <= 600, sum(sleeps)


def test_with_network_injection_success_after_the_old_wait_is_noticed_within_one_poll():
    code, output, sleeps = run_task(injection_disabled=False, succeed_at=17 * 60 + 5)
    assert code == 0, output
    assert SUCCEEDED in output
    # Old behaviour: noticed at the next whole minute (1080 s).
    assert 17 * 60 + 5 <= sum(sleeps) <= 17 * 60 + 5 + POLL, sum(sleeps)


def test_failure_is_not_acted_on_earlier_than_before_and_never_fails_the_task():
    code, output, sleeps = run_task(injection_disabled=True, fail_at=60)
    assert code == 0, output
    assert SUCCEEDED not in output
    assert "Not failing this task" in output
    assert 600 <= sum(sleeps) <= 600 + POLL, sum(sleeps)


@pytest.mark.parametrize("injection_disabled,old_last_check,cap", [(False, 19 * 60, 20 * 60), (True, 29 * 60, 30 * 60)])
def test_still_running_at_the_cap_is_treated_as_success_and_the_cap_is_not_shorter(injection_disabled, old_last_check, cap):
    code, output, sleeps = run_task(injection_disabled=injection_disabled)
    assert code == 0, output
    assert SUCCEEDED in output
    assert old_last_check <= sum(sleeps) <= cap + POLL, sum(sleeps)


def test_the_agent_gets_a_log_line_at_least_once_a_minute():
    code, output, sleeps = run_task(injection_disabled=False)
    assert code == 0, output
    assert max(sleeps) <= 60
    assert len(re.findall(r"min\] Deployment status:", output)) >= 19
