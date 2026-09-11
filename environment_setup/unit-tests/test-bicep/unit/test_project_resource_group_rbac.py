"""Offline contracts for project RG access in infra and Foundry-only deployments."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
ADO = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines"
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
FOUNDRY = tuple(BICEP / f"esml-genai-1/09-ai-foundry-2025-{v}.bicep" for v in ("v3", "v4"))
CUSTOM_ROLE = "11111111-2222-3333-4444-555555555555"


def module_block(path, symbol):
    source = path.read_text(encoding="utf-8")
    match = re.search(rf"(?m)^module {symbol} .*?(?=^(?:module|resource|var|param|output)\s|\Z)",
                      source, re.S | re.M)
    if match is None:
        raise AssertionError(f"{path.name} has no {symbol} module")
    return match.group()


class TestProjectResourceGroupRbac(unittest.TestCase):
    def test_foundry_reuses_rg_module_without_service_or_existing_project_gates(self):
        for path in FOUNDRY:
            with self.subTest(path=path.name):
                block = module_block(path, "rbacResourceGroupUsers")
                self.assertEqual(
                    "module rbacResourceGroupUsers '../modules/resourceGroupRbacUsers.bicep' "
                    "= if (enableAIFoundry && !foundryV22AccountOnly) {",
                    block.splitlines()[0],
                )
                for value in (
                    "scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)",
                    "resourceGroupId: resourceId(subscriptionIdDevTestProd, 'Microsoft.Resources/resourceGroups', targetResourceGroup)",
                    "userObjectIds: union(p011_genai_team_lead_array, p011_genai_team_lead_array)",
                    "servicePrincipleAndMIArray: union(spAndMiArray, spAndMiArray)",
                    "contributorRoleId: contributorRoleId",
                    "useAdGroups: useAdGroups",
                    "disableContributorAccessForUsers: disableContributorAccessForUsers",
                    "disableRBACAdminOnRGForUsers: disableRBACAdminOnRGForUsers",
                ):
                    self.assertIn(value, block)

    def test_general_rg_reconciliation_is_not_skipped_by_update_flag(self):
        block = module_block(BICEP / "esml-genai-1/08-rbac-security.bicep", "rbacResourceGroupUsers")
        self.assertEqual(
            "module rbacResourceGroupUsers '../modules/resourceGroupRbacUsers.bicep' = {",
            block.splitlines()[0],
        )
        variables = yaml.safe_load((ADO / "variables/variables.yaml").read_text(encoding="utf-8"))["variables"]
        self.assertEqual("false", variables["updateRbac"])

    def test_ado_rbac_handles_older_variables_and_preserves_explicit_update_flag(self):
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
        if bash is None:
            self.skipTest("Bash is required")
        steps = yaml.safe_load((ADO / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8"))["steps"]
        step = next(s for s in steps if s.get("displayName") == "100-rbac-security")
        self.assertEqual("$(updateRbac)", step["env"]["RBAC_UPDATE"])
        for configured in ("true", "false", "", "$(updateRbac)"):
            with self.subTest(configured=configured):
                # Apply ADO macro expansion before execution, including inside quoted strings.
                source = re.sub(r"\$\((\w+)\)",
                                lambda m: configured if m[1] == "updateRbac" else "false",
                                step["inputs"]["inlineScript"])
                script = (
                    f"export RBAC_UPDATE={shlex.quote(configured)}\n"
                    "az() { for arg; do case \"$arg\" in updateRbac=*) echo \"$arg\";; esac; done; }\n"
                    + source
                )
                result = subprocess.run([bash, "--noprofile", "--norc", "-s"], input=script.encode("utf-8"),
                                        capture_output=True, timeout=15)
                self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
                expected = configured if configured in ("true", "false") else "false"
                self.assertIn(f"updateRbac={expected}", result.stdout.decode("utf-8"))

    def test_existing_custom_role_scope_names_and_opt_outs_remain(self):
        source = (BICEP / "modules/resourceGroupRbacUsers.bicep").read_text(encoding="utf-8")
        for principal in ("userObjectIds", "servicePrincipleAndMIArray"):
            self.assertIn(f"name: guid(resourceGroupId, contributorRoleId, {principal}[i])", source)
        self.assertIn("roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)", source)
        self.assertIn("principalType: useAdGroups ? 'Group' : 'User'", source)
        self.assertIn("principalType: 'ServicePrincipal'", source)
        self.assertIn("if(!disableContributorAccessForUsers)", source)
        self.assertIn("if(!disableRBACAdminOnRGForUsers)", source)
        self.assertIn("scope: resourceGroup()", source)

    def test_both_pipelines_pass_role_and_opt_outs_to_all_rbac_entrypoints(self):
        ado = yaml.safe_load((ADO / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8"))["steps"]
        gha = yaml.safe_load(GHA.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["steps"]
        for steps, is_ado in ((ado, True), (gha, False)):
            matched = 0
            for step in steps:
                source = step.get("inputs", {}).get("inlineScript", "") if is_ado else step.get("run", "")
                if "--template-file" not in source or not any(
                    filename in source for filename in ("08-rbac-security.bicep", "09-ai-foundry-2025-v4.bicep")
                ):
                    continue
                matched += 1
                for parameter, config in (
                    ("contributorRoleId", "BYOContributorRoleID"),
                    ("disableContributorAccessForUsers", "disableContributorAccessForUsers"),
                    ("disableRBACAdminOnRGForUsers", "disableRBACAdminOnRGForUsers"),
                ):
                    value = f"$({config})" if is_ado else "${{ env." + config + " }}"
                    self.assertIn(f'--parameters {parameter}="{value}"', source, step.get("displayName", step.get("name")))
            self.assertEqual(3, matched)

    def test_github_canonical_json_and_env_alias_keep_custom_contributor_role(self):
        spec = importlib.util.spec_from_file_location("rbac_config_overrides", BICEP / "scripts/apply-json-config-overrides.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        runtime_env = yaml.safe_load(GHA.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["env"]
        self.assertIn("vars.BYO_CONTRIBUTOR_ROLE_ID", runtime_env["BYOContributorRoleID"])
        mappings = helper.github_runtime_names(str(GHA))
        self.assertIn("BYOContributorRoleID", mappings["BYO_CONTRIBUTOR_ROLE_ID"])
        for name in ("BYOContributorRoleID", "BYO_CONTRIBUTOR_ROLE_ID"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "github-env"
                values, _ = helper.selected_values({"dev": {name: CUSTOM_ROLE}}, "dev")
                with patch.dict(os.environ, {"GITHUB_ENV": str(output)}):
                    helper.apply(values, "github", str(GHA))
                assignments = re.findall(r"(?m)^(\w+)<<(\w+)\n([^\n]*)\n\2$", output.read_text(encoding="utf-8"))
                actual = {key: value for key, _, value in assignments}
                self.assertEqual(CUSTOM_ROLE, actual["BYOContributorRoleID"])
        for source, target in (
            ("DISABLE_CONTRIBUTOR_ACCESS_FOR_USERS", "disableContributorAccessForUsers"),
            ("DISABLE_CONTRIBUTOR_ACCESS_FORUSERS", "disableContributorAccessForUsers"),
            ("DISABLE_RBAC_ADMIN_ON_RG_FOR_USERS", "disableRBACAdminOnRGForUsers"),
            ("DISABLE_RBAC_ADMIN_ON_RG_FORUSERS", "disableRBACAdminOnRGForUsers"),
        ):
            self.assertIn(target, mappings[source])


if __name__ == "__main__":
    unittest.main()
