"""Project-vault secret-management opt-in and pipeline forwarding contracts."""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import unittest

import yaml

from .test_project_resource_group_rbac import module_block


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
ADO = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines"
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
KEY = "keyVaultSecretsOfficerForUsers"


class ProjectKeyVaultRbacTests(unittest.TestCase):
    def setUp(self):
        self.core = BICEP / "esml-genai-1/02-core-infrastructure.bicep"
        self.ado = yaml.safe_load(
            (ADO / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8")
        )
        self.gha = yaml.safe_load(GHA.read_text(encoding="utf-8"))
        self.step = next(s for s in self.ado["steps"] if s.get("displayName") == "62-core-infrastructure")

    def test_secret_management_is_explicit_opt_in_not_a_changed_update_flag(self):
        self.assertIn(f"param {KEY} bool = false", self.core.read_text(encoding="utf-8"))
        variables = yaml.safe_load((ADO / "variables/variables.yaml").read_text(encoding="utf-8"))["variables"]
        self.assertEqual("false", variables[KEY])
        block = module_block(self.core, "kvPrjRbacAssignments")
        self.assertIn("if(!keyvaultExists || updateKeyvaultRbac)", block.splitlines()[0])
        self.assertIn(
            f"keyVaultSecretsUserRoleId: {KEY} ? keyVaultSecretsOfficerRoleId : keyVaultSecretsUserRoleId",
            block,
        )
        self.assertIn("useAdGroups: useAdGroups", block)
        self.assertIn("userObjectIds: p011_genai_team_lead_array", block)
        for exists, update, expected in ((True, True, True), (True, False, False),
                                          (False, False, True), (False, True, True)):
            self.assertEqual(expected, not exists or update)

    def test_both_providers_pass_role_opt_in_and_correct_principal_type(self):
        self.assertIn(f'--parameters {KEY}="$KEY_VAULT_SECRETS_OFFICER_FOR_USERS"',
                      self.step["inputs"]["inlineScript"])
        self.assertIn('--parameters useAdGroups="$(use_ad_groups)"', self.step["inputs"]["inlineScript"])
        job = self.gha["jobs"]["deploy-project"]
        self.assertEqual("${{ vars.KEY_VAULT_SECRETS_OFFICER_FOR_USERS || 'false' }}", job["env"][KEY])
        step = next(s for s in job["steps"] if s.get("name") == "62-core-infrastructure")
        self.assertIn(f'--parameters {KEY}="${{{{ env.{KEY} }}}}"', step["run"])
        self.assertIn('--parameters useAdGroups="${{ env.use_groups }}"', step["run"])

    def test_ado_missing_or_legacy_variable_defaults_false_and_invalid_values_fail(self):
        self.assertEqual(f"$({KEY})", self.step["env"]["KEY_VAULT_SECRETS_OFFICER_FOR_USERS"])
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(git_bash) if os.name == "nt" and git_bash.is_file() else shutil.which("bash")
        self.assertIsNotNone(bash, "Bash is required for pipeline argument tests")
        prefix = self.step["inputs"]["inlineScript"].split("# Generate admin password first", 1)[0]
        for configured in ("true", "false", "", f"$({KEY})", "invalid"):
            with self.subTest(configured=configured):
                script = (
                    f"export KEY_VAULT_SECRETS_OFFICER_FOR_USERS={shlex.quote(configured)}\n"
                    "export UPDATE_COMMON_ACR=true ENABLE_APPLICATION_INSIGHTS=true\n"
                    + prefix + '\nprintf "selected=%s\\n" "$KEY_VAULT_SECRETS_OFFICER_FOR_USERS"\n'
                )
                result = subprocess.run([bash, "--noprofile", "--norc", "-s"], input=script,
                                        text=True, capture_output=True, timeout=15)
                if configured == "invalid":
                    self.assertNotEqual(0, result.returncode)
                else:
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("selected=" + ("true" if configured == "true" else "false"),
                                  result.stdout)


if __name__ == "__main__":
    unittest.main()
