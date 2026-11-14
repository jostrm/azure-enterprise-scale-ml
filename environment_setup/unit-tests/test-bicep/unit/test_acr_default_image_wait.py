"""Offline contract: ADO task 05d polls the registry for the default image instead of sleeping 2 x 30 s.

The task opens the registry firewall for the build agent, then looked up `containerapps-default:latest` after a
fixed `sleep 30`, and verified it after a second fixed `sleep 30`. The lookup itself is the real condition: a
successful `az acr repository show` proves the rules are active and the image is there. The task now polls that
lookup and gives up no earlier than the old fixed wait, so a run can only get faster, never less patient.
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
TASK = "05d_Build default image offline, to private registry (ACR) if not exists"
OLD_FIXED_WAIT = 30

# Fake az/curl/sleep. `sleep` advances bash's SECONDS clock instead of waiting. The image lookup succeeds once
# $VISIBLE_AFTER seconds have passed since the first lookup, or (VISIBLE_AFTER=import) once the image was imported,
# or never (VISIBLE_AFTER=never).
FAKE = r"""
calls="$WORK/calls"; : > "$calls"
sleep() { echo "sleep $1" >> "$calls"; SECONDS=$((SECONDS + $1)); }
curl() { echo "203.0.113.7"; }
az() {
  echo "az $*" >> "$calls"
  case "$1 $2" in
    "account set"|"rest --method"|"acr update"|"acr network-rule"|"acr build") return 0 ;;
    "acr show") echo "rg-common" ;;
    "acr import") : > "$WORK/imported" ;;
    "acr repository")
      [ -n "${first_lookup:-}" ] || first_lookup=$SECONDS
      case "$VISIBLE_AFTER" in
        never) return 1 ;;
        import) [ -f "$WORK/imported" ] ;;
        *) [ $((SECONDS - first_lookup)) -ge "$VISIBLE_AFTER" ] ;;
      esac ;;
    *) echo "unexpected az $*" >&2; return 9 ;;
  esac
}
"""


def bash_executable() -> str | None:
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


def task_script() -> str:
    steps = yaml.safe_load(ADO.read_text(encoding="utf-8"))["steps"]
    script = next(s for s in steps if s.get("displayName") == TASK)["inputs"]["inlineScript"]
    # Azure DevOps macros $(name) are replaced before bash runs; shell substitutions keep their spaces.
    return re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)", "x", script)


def run_task(visible_after: str):
    bash = bash_executable()
    if bash is None:
        pytest.skip("bash is required (Git Bash on Windows)")
    with tempfile.TemporaryDirectory() as work:
        result = subprocess.run(
            [bash, "--noprofile", "--norc", "-s"],
            input=(FAKE + task_script()).encode("utf-8"),
            env=os.environ | {"WORK": work.replace("\\", "/"), "VISIBLE_AFTER": visible_after},
            capture_output=True, check=False, timeout=120,
        )
        calls = Path(work, "calls").read_text(encoding="utf-8").splitlines()
    return result.returncode, result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace"), calls


def slept(calls: list[str]) -> int:
    return sum(int(c.split()[1]) for c in calls if c.startswith("sleep "))


def lookup_window(calls: list[str]) -> list[str]:
    """Calls after the last firewall rule was added: the two waits this contract is about."""
    last_rule = max(i for i, c in enumerate(calls) if c.startswith("az acr network-rule add"))
    return calls[last_rule + 1:]


def test_no_fixed_thirty_second_sleep_is_left_in_the_task():
    assert not re.search(r"^\s*sleep 30\s*$", task_script(), flags=re.MULTILINE)


def test_existing_image_is_found_and_verified_without_waiting():
    code, output, calls = run_task("0")
    assert code == 0, output
    assert "Image verified successfully" in output
    assert slept(lookup_window(calls)) == 0, calls
    assert not [c for c in calls if c.startswith("az acr import")]


def test_slow_rule_propagation_ends_the_wait_as_soon_as_the_image_is_visible():
    code, output, calls = run_task("10")
    assert code == 0, output
    assert 10 <= slept(lookup_window(calls)) < OLD_FIXED_WAIT, calls
    assert not [c for c in calls if c.startswith("az acr import")], "a visible image must not be imported again"


def test_missing_image_is_imported_only_after_the_full_old_wait_and_verified_at_once():
    code, output, calls = run_task("import")
    assert code == 0, output
    window = lookup_window(calls)
    first_import = next(i for i, c in enumerate(window) if c.startswith("az acr import"))
    assert slept(window[:first_import]) >= OLD_FIXED_WAIT, "the lookup must stay as patient as the old sleep 30"
    assert slept(window[first_import:]) == 0, "an image that is visible after the import needs no wait"
    assert "Image verified successfully" in output


def test_image_that_never_appears_still_fails_after_the_full_old_wait():
    code, output, calls = run_task("never")
    assert code == 1, output
    assert "Failed to verify image in ACR" in output
    window = lookup_window(calls)
    last_import = max(i for i, c in enumerate(window) if c.startswith("az acr import"))
    assert slept(window[last_import:]) >= OLD_FIXED_WAIT, "verification must not give up earlier than before"
