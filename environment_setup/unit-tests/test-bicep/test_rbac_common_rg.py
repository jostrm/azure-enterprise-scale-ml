"""Offline regressions for task 101 inputs and BYO VNet RBAC scopes."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

from base.config import env_defaults, yaml_defaults


ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup/aifactory/bicep"
ADO = BICEP / (
    "copy_to_local_settings/azure-devops/esml-yaml-pipelines/"
    "esml-infra-project/jobs/job-2-genai-services.yaml"
)
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
COMMON_RBAC = BICEP / "esml-genai-1/08b-rbac-common-rg.bicep"


def section(content: str, start: str, end: str) -> str:
    return content.split(start, 1)[1].split(end, 1)[0]


class TestCommonRbacDefaults(unittest.TestCase):
    def test_bastion_defaults_present_and_empty_on_all_routes(self) -> None:
        ado = yaml_defaults()
        github = env_defaults()
        baseline = json.loads(
            (ROOT / "environment_setup/aifactory/variables.json").read_text(encoding="utf-8")
        )
        workflow = GHA.read_text(encoding="utf-8")
        for key in ("bastion_subscription_resource_group", "bastion_custom_name"):
            with self.subTest(key=key):
                self.assertEqual("", ado[key])
                self.assertEqual("", github[key.upper()])
                self.assertEqual("", baseline["dev"][key])
                self.assertIn(
                    f"{key}: ${{{{ vars.{key.upper()} || '' }}}}", workflow
                )
                self.assertIn(f'"${{{key}:-}}"', workflow)


class TestCommonRbacScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        task = section(
            ADO.read_text(encoding="utf-8"),
            "displayName: '101-rbac-common-rg'",
            "- task: AzureCLI@2",
        )
        cls.script = textwrap.dedent(section(task, "inlineScript: |\n", "    workingDirectory:"))
        cls.bindings = dict(re.findall(r"^    (RBAC_\w+): \$\((\w+)\)$", task, re.MULTILINE))
        cls.required = {
            "RBAC_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000001",
            "RBAC_ENV": "dev",
            "RBAC_PROJECT_NUMBER": "001",
            "RBAC_LOCATION": "swedencentral",
            "RBAC_RANDOM_VALUE": "0123456789",
            "RBAC_KEYVAULT": "seeding-kv",
            "RBAC_KEYVAULT_RG": "seeding-rg",
            "RBAC_KEYVAULT_SUBSCRIPTION": "00000000-0000-0000-0000-000000000002",
        }

    def run_script(
        self, values: dict[str, str], account_exit: int = 0, deployment_exit: int = 0
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        if os.name == "nt":
            bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
            command = str(bash) if bash.is_file() else None
        else:
            command = shutil.which("bash")
        if command is None:
            self.skipTest("Bash is required to exercise the AzureCLI inline script")
        environment = {k: v for k, v in os.environ.items() if not k.startswith("RBAC_")}
        environment.update(self.required)
        environment.update(values)
        # A shell function captures exact argv; no Azure CLI or cloud access is used.
        mock_az = (
            "az() {\n"
            "  printf 'AZ_ARG:%s\\0' \"$@\"\n"
            f'  if [ "$1" = account ]; then return {account_exit}; fi\n'
            f"  return {deployment_exit}\n"
            "}\n"
        )
        result = subprocess.run(
            [command, "--noprofile", "--norc", "-s"],
            input=mock_az + self.script,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        arguments = re.findall(r"AZ_ARG:([^\0]*)\0", result.stdout)
        return result, arguments

    def test_no_ado_macros_are_embedded_in_bash_source(self) -> None:
        self.assertNotRegex(self.script, r"\$\([A-Za-z_]\w*\)")
        referenced = set(re.findall(r"\bRBAC_[A-Z_]+\b", self.script))
        self.assertEqual(referenced, set(self.bindings))
        self.assertEqual("bastion_subscription_resource_group", self.bindings["RBAC_BASTION_RG"])
        self.assertEqual("bastion_custom_name", self.bindings["RBAC_BASTION_NAME"])

    def test_absent_empty_and_unexpanded_optional_inputs_use_defaults(self) -> None:
        cases = {
            "absent": {},
            "empty": {key: "" for key in self.bindings},
            "unexpanded": {key: f"$({source})" for key, source in self.bindings.items()},
        }
        for case, values in cases.items():
            with self.subTest(case=case):
                result, arguments = self.run_script(values | self.required)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", result.stderr)
                for expected in (
                    "bastionResourceGroup=", "bastionName=", "network_env=",
                    "projectPrefix=", "projectSuffix=", "existingAcrPushUserPrincipals=",
                    "existingAcrPushSPPrincipals=", "addBastionHost=false",
                    "enableAzureMachineLearning=false", "disableSubnetJoinAction=false",
                    "useCommonACR=true", "useAdGroups=true",
                ):
                    self.assertIn(expected, arguments)
                self.assertNotRegex("\n".join(arguments), r"\$\([A-Za-z_]\w*\)")

    def test_custom_values_and_shell_metacharacters_stay_literal(self) -> None:
        value = 'custom "\' $(echo SHOULD_NOT_RUN >&2) `echo SHOULD_NOT_RUN >&2`'
        result, arguments = self.run_script({
            "RBAC_BASTION_RG": "custom-bastion-rg",
            "RBAC_BASTION_NAME": value,
            "RBAC_ADMINS_EMAIL": value,
            "RBAC_VNET_RG": "vaip-dev-infra-rg",
            "RBAC_VNET_NAME": "vaip-dev-infra-sdc-vnet",
            "RBAC_COMMON_RG": "vaip-aifactory-esml-common-sdc-dev-002",
            "RBAC_LOCATION_SUFFIX": "sdc",
            "RBAC_COMMON_SUFFIX": "-002",
            "RBAC_ADD_BASTION": "true",
            "RBAC_DISABLE_SUBNET_JOIN": "true",
        })
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        for expected in (
            "bastionResourceGroup=custom-bastion-rg", f"bastionName={value}",
            f"technicalAdminsEmail={value}", "vnetResourceGroup_param=vaip-dev-infra-rg",
            "vnetNameFull_param=vaip-dev-infra-sdc-vnet",
            "commonResourceGroup_param=vaip-aifactory-esml-common-sdc-dev-002",
            "addBastionHost=true", "disableSubnetJoinAction=true",
            "esml-p001-dev-sdc--002PrjDepl-101-rbac-common-rg",
        ):
            self.assertIn(expected, arguments)

    def test_aml_effective_flag_preserves_existing_gate(self) -> None:
        for enabled, exists in (("true", "true"), ("true", "false"), ("false", "true")):
            with self.subTest(enabled=enabled, exists=exists):
                result, arguments = self.run_script({
                    "RBAC_ENABLE_AML": enabled, "RBAC_AML_EXISTS": exists,
                })
                self.assertEqual(0, result.returncode, result.stderr)
                expected = "true" if enabled == exists == "true" else "false"
                self.assertIn(f"enableAzureMachineLearning={expected}", arguments)

    def test_missing_required_input_reports_error_without_invoking_az(self) -> None:
        for value in ("", "$(dev_test_prod_sub_id)"):
            result, arguments = self.run_script({"RBAC_SUBSCRIPTION_ID": value})
            self.assertNotEqual(0, result.returncode)
            self.assertIn("##vso[task.logissue type=error]", result.stdout)
            self.assertIn("RBAC_SUBSCRIPTION_ID", result.stdout)
            self.assertEqual([], arguments)
            self.assertNotIn("command not found", result.stderr)

    def test_azure_failures_are_not_swallowed(self) -> None:
        result, arguments = self.run_script({}, account_exit=7)
        self.assertEqual(7, result.returncode)
        self.assertNotIn("deployment", arguments)
        result, arguments = self.run_script({}, deployment_exit=9)
        self.assertEqual(9, result.returncode)
        self.assertIn("deployment", arguments)


class TestCommonRbacNetworkScopes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.template = COMMON_RBAC.read_text(encoding="utf-8")

    def test_vnet_scope_uses_override_and_keeps_default_fallback(self) -> None:
        self.assertIn(
            "var vnetResourceGroupName = !empty(vnetResourceGroup_param) ? "
            "replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup",
            self.template,
        )
        module = section(self.template, "module cmnRbacVNet ", "// ============== LOG ANALYTICS")
        self.assertIn("if (!disableSubnetJoinAction)", module)
        self.assertIn("scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)", module)
        self.assertIn("vNetName: vnetNameFull", module)
        self.assertIn("assignBastionNsgRole: false", module)

    def test_common_resources_stay_in_common_rg_byo_reader_uses_network_rg(self) -> None:
        for name in ("rbacKeyvaultCommon4Users", "cmnRbacACR", "logAnalyticsReaderProjectMembers"):
            module = section(self.template, f"module {name} ", "\n}\n")
            self.assertIn("scope: resourceGroup(subscriptionIdDevTestProd, commonResourceGroup)", module)
        kv = section(self.template, "module rbacKeyvaultCommon4Users ", "\n}\n")
        self.assertIn("vNetName: vnetInCommonResourceGroup ? vnetNameFull : ''", kv)
        reader = section(self.template, "module rbacReaderByoVNet ", "\n}\n")
        self.assertIn("addBastionHost && !vnetInCommonResourceGroup", reader)
        self.assertIn("scope: resourceGroup(subscriptionIdDevTestProd, vnetResourceGroupName)", reader)
        self.assertIn("vnetRBACReaderOnly.bicep", reader)

    def test_bastion_nsg_is_optional_without_changing_other_callers_default(self) -> None:
        module = (BICEP / "modules/vnetRBACReader.bicep").read_text(encoding="utf-8")
        self.assertIn("param assignBastionNsgRole bool = true", module)
        for name in ("nsgBastion4project", "contributorUserBastionNSG"):
            resource = section(module, f"resource {name} ", "\n}")
            self.assertIn("if (assignBastionNsgRole)", resource)


if __name__ == "__main__":
    unittest.main()
