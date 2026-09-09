"""Offline regressions for the storage discovery -> creation -> RBAC contract."""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup/aifactory/bicep"
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
ADO = BICEP / (
    "copy_to_local_settings/azure-devops/esml-yaml-pipelines/"
    "esml-infra-project/jobs/job-2-genai-services.yaml"
)


def section(content: str, start: str, end: str) -> str:
    return content.split(start, 1)[1].split(end, 1)[0]


class TestStorageDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = GHA.read_text(encoding="utf-8")
        discovery = textwrap.dedent(section(
            cls.workflow, "- name: 16_Check_Resource_Existence",
            "\n      - name:",
        ).split("run: |\n", 1)[1])
        functions = []
        for name in ("resource_exists_fuzzy", "set_env"):
            match = re.search(rf"(?ms)^{name}\(\)\s*\{{.*?^\}}", discovery)
            if match is None:
                raise AssertionError(f"Discovery function {name} not found")
            functions.append(match.group(0))
        assignments = re.findall(
            r"(?m)^(?:suffixStandard|suffixStandardNoDash|suffixStorage[12]|"
            r"storageAccount(?:1001|2001)Name)=.*$", discovery,
        )
        calls = re.findall(
            r'(?m)^set_env "storageAccount(?:1001|2001)Exists" .*$', discovery,
        )
        if len(calls) != 2:
            raise AssertionError("Expected two independent storage detection calls")
        cls.storage_script = "\n".join([*functions, *assignments, *calls]).replace(
            "${{ env.admin_prjResourceSuffix }}", "${resourceSuffix}"
        )

    def detect(
        self, names: list[str], project: str = "006", location: str = "eus2",
        environment: str = "dev", suffix: str = "-001",
    ) -> dict[str, str]:
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("Bash is required to exercise GitHub storage detection")
        setup = "\n".join(
            f"{key}={shlex.quote(value)}" for key, value in {
                "projectName": f"prj{project}",
                "locationSuffix": location,
                "envName": environment,
                "resourceSuffix": suffix,
                "targetRG": "custom-project-rg",
                "FAKE_STORAGE_NAMES": "\n".join(names),
            }.items()
        )
        # Only the Azure call is replaced; execute the workflow's real suffix
        # construction, query generation, boolean detection and GITHUB_ENV writes.
        fake_az = r"""
az() {
  if [ "$1 $2" != "resource list" ]; then return 90; fi
  shift 2
  local query="" rg="" type=""
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --query) query="$2"; shift 2 ;;
      --resource-group) rg="$2"; shift 2 ;;
      --resource-type) type="$2"; shift 2 ;;
      -o) shift 2 ;;
      *) return 91 ;;
    esac
  done
  [ "$rg" = "$targetRG" ] || return 92
  [ "$type" = "Microsoft.Storage/storageAccounts" ] || return 93
  local pattern="starts_with\(name, '([^']*)'\).*ends_with\(name, '([^']*)'\)"
  [[ "$query" =~ $pattern ]] || return 94
  local prefix="${BASH_REMATCH[1]}" suffix="${BASH_REMATCH[2]}"
  while IFS= read -r name; do
    if [ -n "$name" ] && [[ "$name" == "$prefix"* && "$name" == *"$suffix" ]]; then
      printf '%s\n' "$name"
    fi
  done <<< "$FAKE_STORAGE_NAMES"
}
GITHUB_ENV="$(mktemp)"
trap 'rm -f "$GITHUB_ENV"' EXIT
"""
        result = subprocess.run(
            [bash, "--noprofile", "--norc", "-s"],
            # Send bytes so Windows does not translate LF to CRLF for Bash.
            input=("set -euo pipefail\n" + setup + "\n" + fake_az
                   + self.storage_script + '\ncat "$GITHUB_ENV"\n').encode("utf-8"),
            capture_output=True,
            check=False, timeout=60,
        )
        stdout = result.stdout.decode("utf-8")
        stderr = result.stderr.decode("utf-8")
        self.assertEqual(0, result.returncode, stderr + stdout)
        return dict(re.findall(
            r"(?m)^(storageAccount(?:1001|2001)Exists)=(true|false)\r?$",
            stdout,
        ))

    def assert_flags(self, names: list[str], primary: bool, secondary: bool, **kwargs) -> None:
        self.assertEqual({
            "storageAccount1001Exists": str(primary).lower(),
            "storageAccount2001Exists": str(secondary).lower(),
        }, self.detect(names, **kwargs))

    def test_primary_only_does_not_suppress_missing_secondary_creation(self) -> None:
        self.assert_flags(["saprj006eus2ahbbc1001dev"], True, False)

    def test_secondary_only_does_not_suppress_missing_primary_creation(self) -> None:
        self.assert_flags(["saprj006eus2ahbbc2001dev"], False, True)

    def test_both_and_neither_accounts(self) -> None:
        self.assert_flags([], False, False)
        self.assert_flags(
            ["saprj006eus2ahbbc1001dev", "saprj006eus2ahbbc2001dev"], True, True,
        )

    def test_other_projects_environments_regions_and_suffixes_are_not_reused(self) -> None:
        self.assert_flags([
            "saprj007eus2ahbbc1001dev", "saprj007eus2ahbbc2001dev",
            "saprj006eus2ahbbc1001test", "saprj006eus2ahbbc2001prod",
            "saprj006sdcahbbc1001dev", "saprj006sdcahbbc2001dev",
            "saprj006eus2ahbbc1002dev", "saprj006eus2ahbbc2002dev",
            "customerstorage",
        ], False, False)

    def test_nondefault_project_suffix_and_all_environments(self) -> None:
        for environment in ("dev", "test", "prod"):
            with self.subTest(environment=environment):
                self.assert_flags(
                    [f"saprj017sdcabcde2002{environment}"], False, True,
                    project="017", location="sdc", environment=environment, suffix="-002",
                )

    def test_workflows_match_bicep_primary_and_secondary_naming(self) -> None:
        naming = (BICEP / "modules/common/CmnAIfactoryNaming.bicep").read_text(encoding="utf-8")
        ado = ADO.read_text(encoding="utf-8")
        for index, slot in ((1, "1001"), (2, "2001")):
            with self.subTest(slot=slot):
                self.assertIn(
                    f"var storageAccount{slot}Name = replace('sa${{projectName}}"
                    f"${{locationSuffix}}${{uniqueInAIFenv}}{index}"
                    "${prjResourceSuffixNoDash}${env}', '-', '')",
                    naming,
                )
                self.assertIn(f'"$suffixStorage{index}"', self.storage_script)
                self.assertIn(
                    f'"$storageAccount{slot}Name" "$suffixStorage{index}"', ado,
                )

    def test_creation_and_rbac_remain_enabled_instead_of_hiding_the_failure(self) -> None:
        for task, end, template, slot, module_name in (
            ("62-core-infrastructure", "63-cognitive-services", "02-core-infrastructure", "1001", "sacc"),
            ("63-cognitive-services", "64-databases", "03-cognitive-services", "2001", "sa4AIsearch"),
        ):
            with self.subTest(slot=slot):
                block = section(self.workflow, f"- name: {task}\n", f"- name: {end}\n")
                self.assertIn(
                    f'--parameters storageAccount{slot}Exists="${{{{ env.storageAccount{slot}Exists }}}}"',
                    block,
                )
                bicep = (BICEP / f"esml-genai-1/{template}.bicep").read_text(encoding="utf-8")
                self.assertIn(
                    f"module {module_name} '../modules/storageAccount.bicep' = if(!storageAccount{slot}Exists)",
                    bicep,
                )
        rbac_task = section(self.workflow, "- name: 100-rbac-security\n", "- name: 101-rbac-common-rg\n")
        self.assertNotIn("continue-on-error: true", rbac_task)
        rbac = (BICEP / "esml-genai-1/08-rbac-security.bicep").read_text(encoding="utf-8")
        storage_rbac = section(rbac, "module rbacStorageUsers ", "// ============== RBAC MODULES - RESOURCE GROUP")
        self.assertIn("storageAccountName2: storageAccount2001Name", storage_rbac)


if __name__ == "__main__":
    unittest.main()
