"""Offline contracts for the reviewed, single-target MCP-only Azure DevOps pipeline."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest

try:
    import yaml
except ImportError:
    yaml = None


ROOT = Path(__file__).resolve().parents[3]
if not (ROOT / "environment_setup" / "aifactory" / "bicep" / "esml-genai-1" / "08-azure-mcp.bicep").is_file():
    ROOT = ROOT / "azure-enterprise-scale-ml"
PIPELINES = (
    ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings"
    / "azure-devops" / "esml-yaml-pipelines"
)
PROJECT = PIPELINES / "esml-infra-project"
PIPELINE = PROJECT / "infra-project-azure-mcp.yaml"
JOB = PROJECT / "jobs" / "stage-private-azure-mcp.yaml"
REVIEW = PROJECT / "jobs" / "job-0-reviewed-project-config.yaml"
REVIEWED_FILE = "aifactory/.reviewed-project-config.json"
TARGETS = (
    ("dev", "Dev_GenAI_Project", "dev", "dev", "Dev"),
    ("stage", "Stage_GenAI_Project", "test", "test", "Stage"),
    ("prod", "Prod_GenAI_Project", "prod", "prod", "Prod"),
)


@unittest.skipIf(yaml is None, "Install-free YAML contracts require an existing PyYAML")
class McpPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = yaml.safe_load(PIPELINE.read_text(encoding="utf-8"))
        cls.job = yaml.safe_load(JOB.read_text(encoding="utf-8"))
        cls.review = yaml.safe_load(REVIEW.read_text(encoding="utf-8"))
        cls.stages = [stage for stage in cls.pipeline["stages"] if stage["stage"].endswith("_GenAI_Project")]
        cls.deployment = cls.job["jobs"][0]
        cls.steps = cls.deployment["strategy"]["runOnce"]["deploy"]["steps"]

    def test_exact_reviewed_launcher_parameters_and_safe_defaults(self):
        parameters = {item["name"]: item for item in self.pipeline["parameters"]}
        self.assertEqual(
            {
                "deploymentTarget", "deploymentProjectNumber", "deploymentConfigHash",
                "deploymentSettings", "configFile", "useJsonConfigOverride",
                "runnerSelection",
            },
            set(parameters),
        )
        for name in ("deploymentTarget", "deploymentProjectNumber", "deploymentConfigHash"):
            self.assertEqual("", parameters[name]["default"])
            self.assertEqual("string", parameters[name]["type"])
        self.assertNotIn("values", parameters["deploymentTarget"])
        self.assertEqual("object", parameters["deploymentSettings"]["type"])
        self.assertEqual(REVIEWED_FILE, parameters["configFile"]["default"])
        self.assertEqual("boolean", parameters["useJsonConfigOverride"]["type"])
        self.assertIs(True, parameters["useJsonConfigOverride"]["default"])
        self.assertEqual("microsoft-hosted", parameters["runnerSelection"]["default"])
        self.assertEqual("none", self.pipeline["trigger"])
        self.assertEqual("none", self.pipeline["pr"])
        self.assertIn("AIFACTORY_PROJECT_DEPLOYMENT_CONTRACT=1", PIPELINE.read_text())

    def test_incomplete_or_unreviewed_runs_fail_before_deployment(self):
        guards = [stage for stage in self.pipeline["stages"] if stage["stage"] == "Validate_MCP_Request"]
        self.assertEqual(1, len(guards))
        steps = guards[0]["jobs"][0]["steps"]
        self.assertEqual({"checkout": "none"}, steps[0])
        for check in ("MCP_TARGET", "MCP_PROJECT", "MCP_CONFIG_HASH", "MCP_JSON_OVERRIDE", "MCP_CONFIG_FILE"):
            self.assertIn("$env:" + check, steps[1]["pwsh"])
        self.assertIn("throw 'MCP requires", steps[1]["pwsh"])

    def test_stages_are_independent_and_select_exactly_one_environment(self):
        self.assertEqual([row[1] for row in TARGETS], [stage["stage"] for stage in self.stages])
        for stage, (target, _, code, prefix, environment) in zip(self.stages, TARGETS):
            with self.subTest(target=target):
                self.assertEqual("Validate_MCP_Request", stage["dependsOn"])
                self.assertEqual(
                    "and(succeeded(), eq('${{ parameters.deploymentTarget }}', "
                    f"'{target}'))",
                    stage["condition"],
                )
                self.assertEqual(code, stage["variables"]["dev_test_prod"])
                self.assertEqual(
                    f"$({prefix}_sub_id)", stage["variables"]["dev_test_prod_sub_id"],
                )
                self.assertEqual(
                    "${{ parameters.configFile }}", stage["variables"]["configOverrideFile"],
                )
                self.assertEqual(1, len(stage["jobs"]))
                entry = stage["jobs"][0]
                self.assertEqual("./jobs/stage-private-azure-mcp.yaml", entry["template"])
                self.assertEqual(environment, entry["parameters"]["environment"])
                self.assertEqual(
                    "${{ variables." + prefix + "_service_connection }}",
                    entry["parameters"]["serviceConnection"],
                )
                for name in (
                    "deploymentTarget", "deploymentProjectNumber", "deploymentConfigHash",
                    "configFile", "runnerSelection",
                ):
                    self.assertEqual("${{ parameters." + name + " }}", entry["parameters"][name])

    def test_only_existing_runner_settings_are_consumed(self):
        self.assertEqual(
            {"template": "../variables/variables.yaml"}, self.pipeline["variables"][0],
        )
        settings = set(re.findall(r"parameters\.deploymentSettings\.(\w+)", PIPELINE.read_text()))
        self.assertEqual(
            {
                "useSelfHostedBuildAgent", "adminVMBuildAgentPool", "adminVMBuildAgentName",
                "admin_locationSuffix", "admin_commonResourceSuffix",
            },
            settings,
        )
        pool = self.deployment["pool"]
        self.assertEqual({"vmImage": "windows-2022"}, pool["${{ else }}"])
        expression = next(key for key in pool if key != "${{ else }}")
        self.assertEqual(
            "${{ if or(eq(parameters.runnerSelection, 'self-hosted'), "
            "and(eq(parameters.runnerSelection, 'from-config'), "
            "eq(variables.useSelfHostedBuildAgent, 'true'))) }}",
            expression,
        )
        self.assertEqual("$(adminVMBuildAgentPool)", pool[expression]["name"])
        self.assertIn("$(adminVMBuildAgentName)", str(pool[expression]["demands"]))
        self.assertIn(
            "dsvm-cmn-$(admin_locationSuffix)-$(dev_test_prod)$(admin_commonResourceSuffix)",
            str(pool[expression]["demands"]),
        )

    def test_mcp_is_the_only_deployment_template_and_cleanup_is_last(self):
        self.assertEqual(1, len(self.job["jobs"]))
        self.assertEqual("Private_Azure_MCP", self.deployment["deployment"])
        self.assertEqual("${{ parameters.environment }}", self.deployment["environment"])
        self.assertEqual(6, len(self.steps))
        self.assertEqual(
            [
                "./job-0-reviewed-project-config.yaml",
                "./job-private-azure-mcp.yaml",
                "./job-0-reviewed-project-config.yaml",
            ],
            [step["template"] for step in self.steps if "template" in step],
        )
        self.assertEqual("self", self.steps[0]["checkout"])
        self.assertEqual("recursive", self.steps[0]["submodules"])
        self.assertEqual(0, self.steps[0]["fetchDepth"])
        self.assertEqual(
            {
                "target": "${{ parameters.deploymentTarget }}",
                "project": "${{ parameters.deploymentProjectNumber }}",
                "configFile": "${{ parameters.configFile }}",
                "configHash": "${{ parameters.deploymentConfigHash }}",
                "serviceConnection": "${{ parameters.serviceConnection }}",
            },
            self.steps[1]["parameters"],
        )
        self.assertEqual(
            {"serviceConnection": "${{ parameters.serviceConnection }}", "phase": "foundry"},
            self.steps[-2]["parameters"],
        )
        self.assertEqual(
            {"target": "${{ parameters.deploymentTarget }}", "cleanup": True},
            self.steps[-1]["parameters"],
        )
        self.assertGreaterEqual(self.deployment["cancelTimeoutInMinutes"], 1)
        for path in (PIPELINE, JOB):
            self.assertNotRegex(path.read_text(), r"job-?[12]-|az deployment|deleteAll.*: ['\"]?true")

    def test_review_helper_checks_hash_identity_and_connection_and_always_cleans_up(self):
        cleanup, validation = self.review["steps"]
        cleanup_expression, cleanup_steps = next(iter(cleanup.items()))
        self.assertIn("eq(parameters.cleanup, true)", cleanup_expression)
        self.assertEqual("always()", cleanup_steps[0]["condition"])
        self.assertIn("Remove-Item -LiteralPath", cleanup_steps[0]["pwsh"])
        _, validation_steps = next(iter(validation.items()))
        materialize, connection = validation_steps
        self.assertEqual("$(AIFACTORY_CONFIG_JSON)", materialize["env"]["AIFACTORY_CONFIG_JSON"])
        for check in (
            "Reviewed configuration path mismatch", "Reviewed configuration hash mismatch",
            "Reviewed project identity mismatch", "Exact target subscription/tenant required",
        ):
            self.assertIn(check, materialize["pwsh"])
        self.assertEqual("AzureCLI@2", connection["task"])
        self.assertEqual(
            "${{ parameters.serviceConnection }}", connection["inputs"]["azureSubscription"],
        )
        self.assertIn("$account.id -ne $values[$key]", connection["inputs"]["inlineScript"])
        self.assertIn("$account.tenantId -ne $values.tenantId", connection["inputs"]["inlineScript"])

    def test_reviewed_variables_are_applied_before_mcp_without_full_project_prerequisites(self):
        apply = self.steps[2]
        self.assertEqual("PythonScript@0", apply["task"])
        self.assertTrue(apply["inputs"]["scriptPath"].endswith("/apply-json-config-overrides.py"))
        self.assertEqual(
            '--file "$(configOverrideFile)" --environment "$(dev_test_prod)" --format azure-devops',
            apply["inputs"]["arguments"],
        )
        self.assertEqual("$(System.DefaultWorkingDirectory)", apply["inputs"]["workingDirectory"])
        self.assertNotIn("condition", apply)
        gate = self.steps[3]
        self.assertIn("$env:MCP_ENABLED -cne 'true'", gate["pwsh"])
        self.assertIn("$env:MCP_DELETE_ALL -eq 'true'", gate["pwsh"])
        self.assertIn("$env:MCP_DELETE_SERVICES -eq 'true'", gate["pwsh"])
        self.assertEqual("$(enableAzureMcpServer)", gate["env"]["MCP_ENABLED"])
        self.assertNotIn("continueOnError", gate)

    def test_mcp_intent_gate_rejects_disabled_and_destructive_runs(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("Existing PowerShell is required to execute the pipeline intent gate")
        for enabled, delete_all, delete_services, expected_success in (
            ("true", "false", "false", True),
            ("false", "false", "false", False),
            ("$(enableAzureMcpServer)", "false", "false", False),
            ("true", "true", "false", False),
            ("true", "false", "true", False),
        ):
            with self.subTest(enabled=enabled, delete_all=delete_all, delete_services=delete_services):
                result = subprocess.run(
                    [pwsh, "-NoProfile", "-NonInteractive", "-Command", self.steps[3]["pwsh"]],
                    env={
                        **os.environ,
                        "MCP_ENABLED": enabled,
                        "MCP_DELETE_ALL": delete_all,
                        "MCP_DELETE_SERVICES": delete_services,
                    },
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                    check=False,
                )
                self.assertEqual(expected_success, result.returncode == 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
