"""Offline contract: GHA 69b (Foundry account update) rides out a transient ARM RequestConflict.

aif-151 (2026-11-06): 69a waits up to 15 min for the account capability host and then proceeds anyway; 69b's single
`az deployment sub create` then failed with RequestConflict "Another operation is in progress on the resource
.../accounts/<name>" and cost one of the three infra-project attempts. ADO already retries the task
(retryCountOnTaskFailure); GHA has no step retry, so the step itself waits for the busy account and redeploys.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
GHA = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml"
ADO = (ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/esml-yaml-pipelines/"
       "esml-infra-project/jobs/job-2-genai-services.yaml")
STEP = "69b-aifoundry-2025-2ndOption-AccountUpdate"
ACCOUNT = ("/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/aif-151-esml-project002-sdc-dev-001-rg"
           "/providers/Microsoft.CognitiveServices/accounts/aif2fbas5780002dev")


def bash_executable() -> str | None:
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        return str(candidate) if candidate.is_file() else None
    return shutil.which("bash")


def gha_step(name: str) -> dict:
    document = yaml.safe_load(GHA.read_text(encoding="utf-8"))
    steps = document["jobs"]["deploy-project"]["steps"]
    return next(s for s in steps if s.get("name") == name)


def ado_task(name: str) -> dict:
    steps = yaml.safe_load(ADO.read_text(encoding="utf-8"))["steps"]
    return next(s for s in steps if s.get("displayName") == name)


# Fake az: deployment outcomes come from $OUTCOMES (one word per call: ok | conflict | fail); the busy account reports
# Updating once, then Succeeded. Every call is logged so the test can count deployments and polls.
FAKE = r"""
calls="$WORK/calls"; : > "$calls"
sleep() { echo "sleep $*" >> "$calls"; }
az() {
  echo "az $*" >> "$calls"
  case "$1 $2" in
    "account set") return 0 ;;
    "deployment sub")
      n=$(grep -c '^az deployment sub' "$calls")
      outcome=$(echo "$OUTCOMES" | cut -d' ' -f"$n")
      case "${outcome:-ok}" in
        ok) echo '{"properties":{"provisioningState":"Succeeded"}}'; return 0 ;;
        conflict) echo "ERROR: {\"code\": \"RequestConflict\", \"message\": \"Another operation is in progress on the resource '$ACCOUNT'. Please retry later.\"}" >&2; return 1 ;;
        *) echo 'ERROR: {"code": "InvalidTemplateDeployment", "message": "quota"}' >&2; return 1 ;;
      esac ;;
    "resource show")
      polls=$(grep -c '^az resource show' "$calls")
      if [ "$polls" -le 1 ]; then echo Updating; else echo Succeeded; fi ;;
    *) echo "unexpected az $*" >&2; return 9 ;;
  esac
}
"""


class FoundryAccountUpdateRetryTests(unittest.TestCase):
    def run_step(self, outcomes: str):
        bash = bash_executable()
        self.assertIsNotNone(bash, "bash is required (Git Bash on Windows)")
        script = re.sub(r"\$\{\{\s*env\.\w+\s*\}\}", "unused", gha_step(STEP)["run"])
        with tempfile.TemporaryDirectory() as work:
            # GitHub runs `shell: bash` as bash --noprofile --norc -eo pipefail.
            result = subprocess.run(
                [bash, "--noprofile", "--norc", "-eo", "pipefail", "-s"],
                input=(FAKE + script).encode("utf-8"),
                env=os.environ | {"WORK": work.replace("\\", "/"), "OUTCOMES": outcomes, "ACCOUNT": ACCOUNT},
                capture_output=True, check=False, timeout=60,
            )
            calls = Path(work, "calls").read_text(encoding="utf-8").splitlines()
        return result.returncode, result.stdout.decode() + result.stderr.decode(), calls

    def deployments(self, calls):
        return [c for c in calls if c.startswith("az deployment sub create")]

    def test_conflict_waits_for_the_busy_account_then_redeploys(self):
        code, output, calls = self.run_step("conflict ok")
        self.assertEqual(0, code, output)
        self.assertEqual(2, len(self.deployments(calls)), calls)
        polls = [c for c in calls if c.startswith("az resource show")]
        self.assertTrue(polls and all(ACCOUNT in c for c in polls), calls)
        self.assertIn("another operation is in progress", output.lower())

    def test_other_failures_are_not_retried(self):
        code, output, calls = self.run_step("fail ok")
        self.assertNotEqual(0, code, output)
        self.assertEqual(1, len(self.deployments(calls)), calls)
        self.assertFalse([c for c in calls if c.startswith("az resource show")], calls)

    def test_retries_are_bounded(self):
        code, output, calls = self.run_step(" ".join(["conflict"] * 20))
        self.assertNotEqual(0, code, output)
        self.assertEqual(6, len(self.deployments(calls)), calls)
        self.assertLessEqual(len([c for c in calls if c.startswith("sleep")]), 6 * 300, calls)

    def test_ado_keeps_its_task_retry(self):
        self.assertGreaterEqual(int(ado_task(STEP).get("retryCountOnTaskFailure", 0)), 2)


if __name__ == "__main__":
    unittest.main()
