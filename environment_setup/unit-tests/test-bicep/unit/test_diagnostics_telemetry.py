"""Offline source and emitted-ARM contracts for diagnostic defaults; no Azure writes."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
COGNITIVE_DIAGNOSTICS = BICEP / "modules/diagnostics/cognitiveServicesDiagnostics.bicep"
SEARCH_DIAGNOSTICS = BICEP / "modules/diagnostics/aiSearchDiagnostics.bicep"
OPENAI = BICEP / "modules/csOpenAI.bicep"
COGNITIVE_SERVICES = BICEP / "esml-genai-1/03-cognitive-services.bicep"
FOUNDRY_V4 = BICEP / "esml-genai-1/09-ai-foundry-2025-v4.bicep"
DIAGNOSTIC_MODULES = (
    "azureMachineLearningDiagnostics",
    "dataFactoryDiagnostics",
    "cognitiveServicesDiagnostics",
    "functionAppsDiagnostics",
)
GOLD_ENTRYPOINTS = (
    "03-cognitive-services.bicep",
    "05-compute-services.bicep",
    "07-ml-data-platform.bicep",
    "09-ai-foundry-2025-v3.bicep",
    "09-ai-foundry-2025-v4.bicep",
    "11-integration.bicep",
)


def evaluate_diagnostics(value, template, parameters):
    """Evaluate only the bounded expressions in these compiled diagnostic settings."""
    if isinstance(value, dict):
        return {key: evaluate_diagnostics(item, template, parameters) for key, item in value.items()}
    if isinstance(value, list):
        return [evaluate_diagnostics(item, template, parameters) for item in value]
    if not isinstance(value, str) or not value.startswith("["):
        return value

    def array_union(*arrays):
        result = []
        for array in arrays:
            for item in array:
                if item not in result:
                    result.append(item)
        return result

    calls = {
        "parameters": lambda name: parameters[name],
        "variables": lambda name: evaluate_diagnostics(template["variables"][name], template, parameters),
        "equals": lambda left, right: left == right,
        "union": array_union,
        "concat": lambda *arrays: [item for array in arrays for item in array],
        "flatten": lambda arrays: [item for array in arrays for item in array],
        "createArray": lambda *items: list(items),
        "createObject": lambda *items: dict(zip(items[::2], items[1::2], strict=True)),
        "true": lambda: True,
        "false": lambda: False,
    }

    def walk(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "choose":
                return walk(node.args[1] if walk(node.args[0]) else node.args[2])
            if node.func.id in calls:
                return calls[node.func.id](*(walk(arg) for arg in node.args))
        raise AssertionError("Unreviewed diagnostic expression: " + value)

    expression = re.sub(r"\bif\(", "choose(", value[1:-1])
    return walk(ast.parse(expression, mode="eval").body)


class TestDiagnosticsTelemetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cognitive_diagnostics = COGNITIVE_DIAGNOSTICS.read_text(encoding="utf-8")
        cls.search_diagnostics = SEARCH_DIAGNOSTICS.read_text(encoding="utf-8")
        cls.openai = OPENAI.read_text(encoding="utf-8")
        cls.cognitive_services = COGNITIVE_SERVICES.read_text(encoding="utf-8")
        cls.foundry_v4 = FOUNDRY_V4.read_text(encoding="utf-8")

    def test_foundry_usage_categories_are_enabled_at_every_tier(self) -> None:
        for category in ("RequestResponse", "Trace", "AzureOpenAIRequestUsage"):
            self.assertIn(f"category: '{category}'", self.cognitive_diagnostics)
        self.assertIn("param includeAzureOpenAIUsageTelemetry bool = false", self.cognitive_diagnostics)
        self.assertIn(
            "diagnosticSettingLevel == 'gold' ? goldLogs : "
            "(includeAzureOpenAIUsageTelemetry ? union(tierLogs, foundryRequiredLogs) : tierLogs)",
            self.cognitive_diagnostics,
        )
        self.assertIn(
            "includeAzureOpenAIUsageTelemetry: true", self.foundry_v4
        )

    def test_openai_collects_usage_metrics_and_logs_for_new_resources(self) -> None:
        self.assertIn("workspaceId: logAnalyticsWorkspace.id", self.openai)
        self.assertIn("category: 'AllMetrics'", self.openai)
        self.assertIn("categoryGroup: 'allLogs'", self.openai)
        self.assertIn("logAnalyticsDestinationType: null", self.openai)
        creation = re.search(
            r"module csAzureOpenAI '[^']+' = if\([^)]*\) \{(.*?)\n\}",
            self.cognitive_services, re.DOTALL,
        )
        self.assertIsNotNone(creation)
        self.assertIn("diagnosticSettingLevel: diagnosticSettingLevel", creation.group(1))

    def test_existing_openai_gets_the_same_telemetry_without_duplicate_settings(self) -> None:
        self.assertIn(
            "if (openaiExists && enableAzureOpenAI && !skipDiagAOAI)",
            self.cognitive_services,
        )
        self.assertIn(
            "includeAzureOpenAIUsageTelemetry: true", self.cognitive_services
        )
        self.assertNotIn(
            "if (!openaiExists && enableAzureOpenAI && !skipDiagAOAI)",
            self.cognitive_services,
        )

    def test_search_collects_requests_and_metrics_on_reruns(self) -> None:
        self.assertIn("category: 'OperationLogs'", self.search_diagnostics)
        self.assertIn("category: 'AllMetrics'", self.search_diagnostics)
        self.assertIn(
            "var privateFoundryStandardAgents = enableAIFoundry && !enablePublicGenAIAccess",
            self.cognitive_services,
        )
        self.assertIn(
            "var needsAISearch = enableAISearch || privateFoundryStandardAgents",
            self.cognitive_services,
        )
        condition = re.search(
            r"module\s+aiSearchDiagnostics\s+'[^']+'\s*=\s*if\s*\((.*?)\)\s*\{",
            self.cognitive_services,
            re.DOTALL,
        )
        self.assertIsNotNone(condition, "AI Search diagnostics must have an explicit condition")
        self.assertEqual(re.sub(r"\s+", "", condition.group(1)), "needsAISearch&&!skipDiagAISearch")
        self.assertNotIn("aiSearchExists", condition.group(1))

    def test_affected_entrypoints_default_to_gold_without_removing_tier_options(self) -> None:
        for name in GOLD_ENTRYPOINTS:
            with self.subTest(entrypoint=name):
                source = (BICEP / "esml-genai-1" / name).read_text(encoding="utf-8")
                self.assertIn("param diagnosticSettingLevel string = 'gold'", source)
                self.assertIn("@allowed(['gold', 'silver', 'bronze'])", source)

    def test_logic_app_standard_wires_diagnostics_without_touching_reused_or_consumption_apps(self) -> None:
        source = (BICEP / "esml-genai-1/11-integration.bicep").read_text(encoding="utf-8")
        module = re.search(
            r"module logicAppStandardDiagnostics '[^']+' = if \((.*?)\) \{(.*?)\n\}",
            source, re.DOTALL,
        )
        self.assertIsNotNone(module)
        self.assertEqual(
            "logiAppType=='Standard'&&!logicAppsExists&&enableLogicApps",
            re.sub(r"\s+", "", module.group(1)),
        )
        for binding in (
            "functionAppName: logicAppsName",
            "logAnalyticsWorkspaceId: logAnalyticsWorkspace.id",
            "diagnosticSettingLevel: diagnosticSettingLevel",
            "isLogicAppStandard: true",
        ):
            self.assertIn(binding, module.group(2))
        self.assertRegex(module.group(2), r"dependsOn:\s*\[\s*logicAppStandard\s*\]")

    def test_existing_resource_and_policy_skip_guards_are_preserved(self) -> None:
        guarded_modules = {
            "07-ml-data-platform.bicep": {
                "amlDiagnostics": "!amlExists&&enableAzureMachineLearning",
                "dataFactoryDiagnostics": "!dataFactoryExists&&enableDatafactory",
            },
            "05-compute-services.bicep": {
                "functionAppDiagnostics": "!functionAppExists&&enableFunction",
            },
        }
        for name, modules in guarded_modules.items():
            source = (BICEP / "esml-genai-1" / name).read_text(encoding="utf-8")
            for module, expected in modules.items():
                with self.subTest(module=module):
                    condition = re.search(rf"module {module} '[^']+' = if \((.*?)\)", source)
                    self.assertIsNotNone(condition)
                    self.assertEqual(expected, re.sub(r"\s+", "", condition.group(1)))
        self.assertIn("param skipDiagAOAI bool = true", self.cognitive_services)
        self.assertIn("param skipDiagAIServices bool = true", self.cognitive_services)


class TestCompiledDiagnosticDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("bicep")
        if not compiler:
            raise unittest.SkipTest("Standalone Bicep is required for emitted-ARM diagnostic tests")
        cls.templates = {}
        sources = {
            name: BICEP / "modules/diagnostics" / f"{name}.bicep"
            for name in DIAGNOSTIC_MODULES
        }
        sources["csOpenAI"] = OPENAI
        for name, source in sources.items():
            result = subprocess.run(
                [compiler, "build", str(source), "--stdout", "--no-restore"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode:
                raise AssertionError(f"{name}: {result.stderr}")
            cls.templates[name] = json.loads(result.stdout)

    def settings(self, name, **overrides):
        template = self.templates[name]
        parameters = {
            key: schema["defaultValue"]
            for key, schema in template["parameters"].items()
            if "defaultValue" in schema
        } | overrides
        settings = [
            resource for resource in template["resources"]
            if resource["type"] == "Microsoft.Insights/diagnosticSettings"
        ]
        self.assertEqual(1, len(settings))
        return template, parameters, settings[0]

    def test_gold_defaults_emit_only_all_logs_preserving_metrics_name_and_destination(self) -> None:
        for name in DIAGNOSTIC_MODULES:
            with self.subTest(module=name):
                template, params, setting = self.settings(name, logAnalyticsWorkspaceId="existing-workspace")
                self.assertEqual("gold", params["diagnosticSettingLevel"])
                self.assertEqual(
                    [{"categoryGroup": "allLogs", "enabled": True}],
                    evaluate_diagnostics(setting["properties"]["logs"], template, params),
                )
                self.assertEqual(
                    [{"category": "AllMetrics", "enabled": True}],
                    evaluate_diagnostics(setting["properties"]["metrics"], template, params),
                )
                self.assertEqual(
                    "existing-workspace",
                    evaluate_diagnostics(setting["properties"]["workspaceId"], template, params),
                )
                self.assertEqual("[parameters('diagnosticSettingName')]", setting["name"])
                self.assertNotIn("logAnalyticsDestinationType", setting["properties"])

    def test_explicit_lower_tiers_still_use_individual_supported_categories(self) -> None:
        for name in DIAGNOSTIC_MODULES:
            for tier in ("silver", "bronze"):
                with self.subTest(module=name, tier=tier):
                    template, params, setting = self.settings(name, diagnosticSettingLevel=tier)
                    logs = evaluate_diagnostics(setting["properties"]["logs"], template, params)
                    self.assertTrue(logs)
                    self.assertTrue(all(log["enabled"] and "category" in log for log in logs))
                    self.assertFalse(any("categoryGroup" in log for log in logs))
                    self.assertNotIn("AppServiceAppLogs", {log["category"] for log in logs})

    def test_foundry_telemetry_is_not_duplicated_under_all_logs(self) -> None:
        for tier in ("gold", "silver", "bronze"):
            with self.subTest(tier=tier):
                template, params, setting = self.settings(
                    "cognitiveServicesDiagnostics",
                    diagnosticSettingLevel=tier, includeAzureOpenAIUsageTelemetry=True,
                )
                logs = evaluate_diagnostics(setting["properties"]["logs"], template, params)
                if tier == "gold":
                    self.assertEqual([{"categoryGroup": "allLogs", "enabled": True}], logs)
                else:
                    categories = [log["category"] for log in logs]
                    self.assertTrue({"RequestResponse", "Trace", "AzureOpenAIRequestUsage"} <= set(categories))
                    self.assertEqual(len(categories), len(set(categories)))

    def test_logic_app_lower_tiers_collect_workflow_runtime_not_web_app_logs(self) -> None:
        for tier in ("silver", "bronze"):
            with self.subTest(tier=tier):
                template, params, setting = self.settings(
                    "functionAppsDiagnostics", diagnosticSettingLevel=tier, isLogicAppStandard=True,
                )
                logs = evaluate_diagnostics(setting["properties"]["logs"], template, params)
                self.assertIn("WorkflowRuntime", {log["category"] for log in logs})
                self.assertNotIn("AppServiceAppLogs", {log["category"] for log in logs})

    def test_new_openai_uses_the_existing_default_setting_and_azure_diagnostics_table(self) -> None:
        template, params, setting = self.settings("csOpenAI")
        self.assertEqual("default", setting["name"])
        self.assertEqual("gold", params["diagnosticSettingLevel"])
        self.assertEqual(
            [{"categoryGroup": "allLogs", "enabled": True}],
            evaluate_diagnostics(setting["properties"]["logs"], template, params),
        )
        self.assertEqual([{"category": "AllMetrics", "enabled": True}], setting["properties"]["metrics"])
        self.assertIsNone(setting["properties"]["logAnalyticsDestinationType"])

    def test_new_openai_respects_explicit_lower_tiers_without_losing_usage_telemetry(self) -> None:
        for tier in ("silver", "bronze"):
            with self.subTest(tier=tier):
                template, params, setting = self.settings("csOpenAI", diagnosticSettingLevel=tier)
                logs = evaluate_diagnostics(setting["properties"]["logs"], template, params)
                self.assertEqual(
                    [{"category": category, "enabled": True}
                     for category in ("RequestResponse", "Trace", "AzureOpenAIRequestUsage")],
                    logs,
                )


if __name__ == "__main__":
    unittest.main()