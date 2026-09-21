"""Offline legacy identity discovery and pipeline handoff regressions."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
SCRIPTS = BICEP / "scripts"
ADO = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location("identity_discovery", SCRIPTS / "resolve_managed_identities.py")
    ID = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ID
    spec.loader.exec_module(ID)
SUB = "11111111-2222-3333-4444-555555555555"
CFG = ID.Config(ID.Scope(SUB, "acme-project017-sdc-dev-007"),
                ID.Scope(SUB, "custom-common-rg"), "017", "sdc", "dev", "-001")


def identity(kind="project", tail="abcde0123456789-001"):
    name = CFG.prefix(kind) + tail
    return {"name": name, "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
            "id": f"{CFG.project_scope.id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{name}"}


def task(path, name):
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = document.get("steps") or document["jobs"]["deploy-project"]["steps"]
    return next(s for s in steps if s.get("displayName", s.get("name")) == name)


class TestManagedIdentityDiscovery(unittest.TestCase):
    def test_known_formats_recover_same_salt_and_preserve_exact_names(self):
        for tail in ("abcde0123456789-001", "abcde-0123456789-001", "abcde0123456789001",
                     "abcde0123456789-002", "abcde-0123456789-002", "abcde0d-bf29-48-001"):
            with self.subTest(tail=tail):
                project, aca = identity(tail=tail), identity("containerApps", tail)
                result = ID.resolve(CFG, [project, aca], [])
                self.assertEqual({"project": project["name"], "containerApps": aca["name"]},
                                 json.loads(result["resolvedManagedIdentityNames"]))
                self.assertEqual("abcde", result["aifactory_salt"])
                self.assertEqual("0d-bf29-48" if "bf29" in tail else "0123456789", result["aifactory_salt_random"])
                self.assertEqual("true", result["miPrjExists"])
                self.assertEqual("true", result["miACAExists"])

    def test_mixed_legacy_and_current_names_are_not_rewritten(self):
        project = identity(tail="abcde-0123456789-001")
        aca = identity("containerApps")
        result = ID.resolve(CFG, [project, aca], [])
        self.assertEqual(project["name"], json.loads(result["resolvedManagedIdentityNames"])["project"])
        self.assertEqual(aca["name"], json.loads(result["resolvedManagedIdentityNames"])["containerApps"])
        self.assertEqual("0123456789", result["aifactory_salt_random"])

    def test_missing_one_identity_preserves_survivor_and_its_salt(self):
        for kind, missing in (("project", "miACAExists"), ("containerApps", "miPrjExists")):
            with self.subTest(kind=kind):
                result = ID.resolve(CFG, [identity(kind)], [])
                self.assertEqual("false", result[missing])
                self.assertEqual("0123456789", result["aifactory_salt_random"])
                self.assertEqual({kind: identity(kind)["name"]}, json.loads(result["resolvedManagedIdentityNames"]))

    def test_new_then_existing_deployment_and_partial_legacy_migration_are_stable(self):
        first = ID.resolve(CFG, [], [])
        self.assertEqual("", first["aifactory_salt_random"])
        for initial in ([], [identity(tail="abcde-0123456789-001")]):
            existing = initial + [identity("containerApps")]
            if not initial:
                existing.append(identity())
            second = ID.resolve(CFG, existing, [])
            third = ID.resolve(CFG, list(reversed(existing)), [])
            self.assertEqual(second, third)
            self.assertEqual("0123456789", third["aifactory_salt_random"])

    def test_literal_identity_names_and_names_from_other_environments_cannot_be_confused(self):
        other = identity() | {"name": "mi-prj017-sdc-test-abcde0123456789-001"}
        result = ID.resolve(CFG, [other, identity()], [])
        self.assertEqual({"project": identity()["name"]}, json.loads(result["resolvedManagedIdentityNames"]))

    def test_new_project_ignores_manual_legacy_salt_and_uses_bicep_default_names(self):
        common = [{"name": "la-cmn-sdc-dev-abcde-001", "type": "Microsoft.OperationalInsights/workspaces"}]
        with patch.dict(os.environ, {"aifactory_salt_random": "manual-salt", "AIFACTORY_SALT_RANDOM": "manual-salt"}):
            result = ID.resolve(CFG, [], common)
        self.assertEqual("{}", result["resolvedManagedIdentityNames"])
        self.assertEqual("", result["aifactory_salt_random"])
        self.assertEqual("abcde", result["aifactory_salt"])
        self.assertEqual("false", result["miPrjExists"])
        self.assertEqual("false", result["miACAExists"])

    def test_ambiguous_identity_including_different_suffix_is_fatal(self):
        for kind in ("project", "containerApps"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Ambiguous"):
                ID.resolve(CFG, [identity(kind), identity(kind, "abcde0123456789-002")], [])

    def test_unknown_or_partial_salt_cannot_become_a_new_random_salt(self):
        for tail in ("abcde-001", "abcde12345-001", "abcde01234567890-001",
                     "abcde-01234-001", "0123456789-001", "odd-legacy-name"):
            with self.subTest(tail=tail), self.assertRaisesRegex(ValueError, "Cannot safely recover"):
                ID.resolve(CFG, [identity(tail=tail)], [])

    def test_conflicting_project_and_aca_salts_are_fatal(self):
        with self.assertRaisesRegex(ValueError, "conflicting"):
            ID.resolve(CFG, [identity(), identity("containerApps", "abcde9876543210-001")], [])

    def test_existing_workload_with_no_matching_identities_does_not_get_new_salt(self):
        for item in (
            {"name": "old-storage", "type": "Microsoft.Storage/storageAccounts"},
            identity(tail="abcde0123456789-001") | {"name": "mi-prj017-sdc-dev2-abcde0123456789-001"},
        ):
            with self.subTest(name=item["name"]), self.assertRaisesRegex(ValueError, "no recognizable"):
                ID.resolve(CFG, [item], [])

    def test_other_project_identities_are_not_adopted(self):
        other = identity() | {"name": "mi-prj018-sdc-dev-abcde0123456789-001"}
        result = ID.resolve(CFG, [identity(), other], [])
        self.assertEqual({"project": identity()["name"]}, json.loads(result["resolvedManagedIdentityNames"]))

    def test_scope_mismatch_and_unsafe_names_fail(self):
        for item in (
            identity() | {"id": identity()["id"].replace(SUB, "other-sub")},
            identity() | {"id": ""},
            identity(tail="abcde0123456789-001';echo"),
        ):
            with self.subTest(item=item["name"]), self.assertRaises(ValueError):
                ID.resolve(CFG, [item], [])

    def test_azure_reads_are_scoped_and_no_common_scan_for_existing_identities(self):
        az = Mock(side_effect=[True, [identity(), identity("containerApps")]])
        result = ID.discover(CFG, az)
        self.assertEqual("true", result["miPrjExists"])
        self.assertEqual([
            ("group", "exists", "--subscription", SUB, "--name", CFG.project_scope.resource_group),
            ("resource", "list", "--subscription", SUB, "--resource-group", CFG.project_scope.resource_group),
        ], [call.args for call in az.call_args_list])

    def test_scope_configuration_uses_custom_common_rg_and_treats_macros_as_unset(self):
        values = {
            "MI_DISCOVERY_SUBSCRIPTION": SUB, "MI_DISCOVERY_PROJECT_NUMBER": "017",
            "MI_DISCOVERY_LOCATION_SUFFIX": "sdc", "MI_DISCOVERY_ENVIRONMENT": "dev",
            "MI_DISCOVERY_RG_PREFIX": "acme-", "MI_DISCOVERY_RG_SUFFIX": "-007",
            "MI_DISCOVERY_PROJECT_PREFIX": "", "MI_DISCOVERY_PROJECT_SUFFIX": "",
            "MI_DISCOVERY_COMMON_RG": "custom-common-rg", "MI_DISCOVERY_COMMON_SUFFIX": "-001",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(CFG, ID.configuration())
        values["MI_DISCOVERY_COMMON_RG"] = "$(commonResourceGroup_param)"
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual("acme-esml-common-sdc-dev-007", ID.configuration().common_scope.resource_group)
        values["MI_DISCOVERY_SUBSCRIPTION"] = "$(dev_test_prod_sub_id)"
        with patch.dict(os.environ, values, clear=True), self.assertRaises(ValueError):
            ID.configuration()

    def test_first_deployment_checks_group_then_only_reads_common(self):
        az = Mock(side_effect=[False, []])
        self.assertEqual("{}", ID.discover(CFG, az)["resolvedManagedIdentityNames"])
        self.assertEqual(("resource", "list", "--subscription", SUB, "--resource-group", "custom-common-rg"),
                         az.call_args_list[1].args)

    def test_access_denied_or_malformed_response_is_not_treated_as_missing(self):
        for responses in ([RuntimeError("AuthorizationFailed")], ["false"], [True, {}], [False, None]):
            with self.subTest(responses=responses), self.assertRaises((ValueError, RuntimeError)):
                ID.discover(CFG, Mock(side_effect=responses))

    def test_failure_emits_no_success_variables_or_partial_github_output(self):
        for route in ("ado", "github"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "github-env"
                output.write_text("existing=keep\n", encoding="utf-8")
                with patch.object(sys, "argv", ["discovery", "--format", route]), \
                     patch.dict(os.environ, {"GITHUB_ENV": str(output)}), \
                     patch.object(ID, "configuration", return_value=CFG), \
                     patch.object(ID, "discover", side_effect=ValueError("Ambiguous project identity")), \
                     contextlib.redirect_stdout(io.StringIO()) as stdout, \
                     contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(1, ID.main())
                self.assertEqual("", stdout.getvalue())
                self.assertIn("Ambiguous", stderr.getvalue())
                self.assertEqual("existing=keep\n", output.read_text(encoding="utf-8"))

    def test_output_formats_share_identical_names_flags_and_salt(self):
        values = ID.resolve(CFG, [identity(tail="abcde-0123456789-001")], [])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            ID.publish(values, "ado")
        self.assertEqual(values, dict(re.findall(r"variable=(\w+)\](.*)", output.getvalue())))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-env"
            with patch.dict(os.environ, {"GITHUB_ENV": str(path)}):
                ID.publish(values, "github")
            self.assertEqual(values, dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()))


class TestIdentityPipelineWiring(unittest.TestCase):
    def test_loose_identity_existence_checks_are_not_used(self):
        for path, name in ((ADO, "05b_Check if resource exists"), (GHA, "16_Check_Resource_Existence")):
            step = task(path, name)
            source = step.get("inputs", {}).get("inlineScript", step.get("run", ""))
            self.assertNotRegex(source, r"variable=mi(?:Prj|ACA)Exists\]")
            self.assertNotIn('set_env "miPrjExists"', source)
            self.assertNotIn('set_env "miACAExists"', source)

    def test_both_routes_use_shared_resolver_and_propagate_errors(self):
        for path, name in ((ADO, "05b_Extract_and_set_aifactory_salt_values"), (GHA, "17_Extract_aifactory_salt_random")):
            with self.subTest(route=path.name):
                step = task(path, name)
                source = step.get("inputs", {}).get("inlineScript", step.get("run", ""))
                self.assertIn("resolve_managed_identities.py", source)
                self.assertIn("if ($LASTEXITCODE -ne 0) { throw", source)
                self.assertNotIn("head -n", source)
                self.assertNotIn("miPrjExists", source)
                self.assertIn("MI_DISCOVERY_SUBSCRIPTION", step["env"])
                self.assertNotIn("AIFACTORY_SALT_RANDOM", step["env"])
                self.assertFalse(step.get("continueOnError", step.get("continue-on-error", False)))

    def test_all_naming_aware_deployment_calls_receive_internal_names(self):
        for path in (ADO, GHA):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            steps = document.get("steps") or document["jobs"]["deploy-project"]["steps"]
            count = 0
            for step in steps:
                source = step.get("inputs", {}).get("inlineScript", step.get("run", ""))
                if "aifactorySalt10char=" not in source or "--template-file" not in source:
                    continue
                if "10-aifactory-dashboards.bicep" in source:
                    self.assertNotIn("resolvedManagedIdentityNames=", source)
                    continue
                self.assertIn("--parameters resolvedManagedIdentityNames=", source)
                count += 1
            self.assertEqual(12, count)
        for path in (BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml",
                     BICEP / "copy_to_local_settings/github-actions/.env.template",
                     ROOT / "environment_setup/aifactory/variables.json"):
            self.assertNotIn("resolvedManagedIdentityNames", path.read_text(encoding="utf-8"))

    def test_json_names_survive_bash_parameter_handoff(self):
        bash = str(Path(r"C:\Program Files\Git\bin\bash.exe")) if os.name == "nt" else shutil.which("bash")
        if not bash:
            self.skipTest("Bash is required")
        names = ID.resolve(CFG, [identity(tail="abcde-0123456789-001"), identity("containerApps")], [])["resolvedManagedIdentityNames"]
        for path, name in ((ADO, "65-compute-services"), (GHA, "65-compute-services")):
            step = task(path, name)
            source = step.get("inputs", {}).get("inlineScript", step.get("run", ""))
            line = next(line for line in source.splitlines() if "--parameters resolvedManagedIdentityNames=" in line)
            line = line.replace("$(resolvedManagedIdentityNames)", names).replace("${{ env.resolvedManagedIdentityNames }}", names)
            script = "az() { printf '%s\\n' \"$@\"; }\naz deployment sub create \\\n" + line + "\n--only-show-errors\n"
            result = subprocess.run([bash, "--noprofile", "--norc", "-s"], input=script.encode("utf-8"),
                                    capture_output=True, check=True, timeout=15)
            argument = next(line for line in result.stdout.decode("utf-8").splitlines()
                            if line.startswith("resolvedManagedIdentityNames="))
            self.assertEqual(json.loads(names), json.loads(argument.split("=", 1)[1]))

    def test_discovery_wrapper_passes_cloud_error_as_failed_task(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell is required")
        for path, name in ((ADO, "05b_Extract_and_set_aifactory_salt_values"), (GHA, "17_Extract_aifactory_salt_random")):
            step = task(path, name)
            source = step.get("inputs", {}).get("inlineScript", step.get("run", ""))
            for code in (0, 7):
                setup = f"""
$ErrorActionPreference = 'Stop'
$env:SYSTEM_DEFAULTWORKINGDIRECTORY = 'C:\\repo'
$env:GITHUB_WORKSPACE = 'C:\\repo'
function Fake-Python {{ $global:LASTEXITCODE = {code}; Write-Host ($args -join ' ') }}
function Get-Command {{ [pscustomobject]@{{ Source = 'Fake-Python' }} }}
"""
                result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", setup + source],
                                        capture_output=True, timeout=20)
                self.assertEqual(code == 0, result.returncode == 0, result.stderr.decode("utf-8"))
                self.assertIn(b"--format", result.stdout)


if __name__ == "__main__":
    unittest.main()
