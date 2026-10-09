"""Offline tests for AI Factory dashboard discovery, layout, and deployment."""
from __future__ import annotations

import importlib.util
import copy
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py"
TEMPLATE = ROOT / "environment_setup/aifactory/bicep/modules/aifactory-dash-01.bicep"
ADO_JOB = ROOT / (
    "environment_setup/aifactory/bicep/copy_to_local_settings/azure-devops/"
    "esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
)
GHA_JOB = ROOT / (
    "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"
    "infra-project-phase.yml"
)
GHA_VARIABLE_SYNC = ROOT / (
    "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/"
    "03a-GH-create-or-update-github-variables.sh"
)
spec = importlib.util.spec_from_file_location("aifactory_dashboard", SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

DEV_SUB = "11111111-1111-4111-8111-111111111111"
TEST_SUB = "22222222-2222-4222-8222-222222222222"
PROD_SUB = "33333333-3333-4333-8333-333333333333"
TENANT = "44444444-4444-4444-8444-444444444444"


def response(payload: object = None, error: str = "") -> subprocess.CompletedProcess[str]:
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess([], 1 if error else 0, stdout, error)


def environment() -> dict[str, str]:
    return {
        "DASHBOARD_CURRENT_SUBSCRIPTION_ID": DEV_SUB,
        "DASHBOARD_CURRENT_ENV": "dev",
        "DASHBOARD_PROJECT_NUMBER": "017",
        "DASHBOARD_LOCATION": "swedencentral",
        "DASHBOARD_LOCATION_SUFFIX": "sdc",
        "DASHBOARD_RG_PREFIX": "vaip-",
        "DASHBOARD_RG_SUFFIX": "-002",
        "DASHBOARD_PROJECT_PREFIX": "esml-",
        "DASHBOARD_PROJECT_SUFFIX": "-rg",
        "DASHBOARD_COMMON_NAME": "aifactory-esml-common",
        "DASHBOARD_DEV_SUBSCRIPTION_ID": DEV_SUB,
        "DASHBOARD_STAGE_SUBSCRIPTION_ID": TEST_SUB,
        "DASHBOARD_PROD_SUBSCRIPTION_ID": PROD_SUB,
        "DASHBOARD_TEMPLATE_FILE": str(TEMPLATE),
    }


class TestDashboardCliLauncher(unittest.TestCase):
    def test_native_cli_is_resolved_on_path(self) -> None:
        executable = str(Path("Azure CLI") / "az")
        result = response({"azure-cli": "test"})
        with (
            patch.object(module.shutil, "which", return_value=executable),
            patch.object(module.sys, "platform", "linux"),
            patch.object(module.subprocess, "run", return_value=result) as run,
        ):
            self.assertIs(result, module.az_cli("version", "--output", "json"))
        self.assertEqual([executable, "version", "--output", "json"], run.call_args.args[0])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertFalse(run.call_args.kwargs["check"])

    def test_windows_batch_launcher_uses_cli_python_and_literal_arguments(self) -> None:
        arguments = (
            "rest", "--url", "https://management.azure.com/resource?api-version=1&$skiptoken=a",
            "--headers", 'If-Match="etag"', "--body", "@C:\\dashboard files\\body.json",
        )
        installs = (
            Path("Program Files") / "Microsoft SDKs" / "Azure" / "CLI2",
            Path("Program Files (x86)") / "Microsoft SDKs" / "Azure" / "CLI2",
            Path("Self Hosted Tools") / "Azure CLI",
        )
        for install_path, extension in itertools.product(installs, (".cmd", ".CMD", ".bat")):
            with self.subTest(install=install_path, extension=extension), tempfile.TemporaryDirectory() as folder:
                install = Path(folder) / install_path
                (install / "wbin").mkdir(parents=True)
                cli_python = install / "python.exe"
                cli_python.touch()
                with (
                    patch.object(module.shutil, "which", return_value=str(install / "wbin" / f"az{extension}")),
                    patch.object(module.sys, "platform", "win32"),
                    patch.object(module.subprocess, "run", return_value=response()) as run,
                ):
                    module.az_cli(*arguments)
                self.assertEqual(
                    [str(cli_python), "-X", "utf8", "-IBm", "azure.cli", *arguments],
                    run.call_args.args[0],
                )
                self.assertFalse(run.call_args.kwargs.get("shell", False))
                self.assertEqual("utf-8", run.call_args.kwargs["encoding"])
                # Preserve the task's authenticated AZURE_CONFIG_DIR and environment.
                self.assertNotIn("env", run.call_args.kwargs)

    def test_windows_native_executable_does_not_require_bundled_python(self) -> None:
        with (
            patch.object(module.shutil, "which", return_value="az.exe"),
            patch.object(module.sys, "platform", "win32"),
            patch.object(module.subprocess, "run", return_value=response()) as run,
        ):
            module.az_cli("version")
        self.assertEqual(["az.exe", "version"], run.call_args.args[0])

    def test_missing_cli_is_an_explicit_error(self) -> None:
        with (
            patch.object(module.shutil, "which", return_value=None),
            patch.object(module.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "not found on PATH"):
                module.az_cli("version")
        run.assert_not_called()

    def test_missing_windows_cli_runtime_does_not_fall_back_to_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.object(module.shutil, "which", return_value=str(Path(folder) / "wbin" / "az.cmd")),
                patch.object(module.sys, "platform", "win32"),
                patch.object(module.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(RuntimeError, "Windows Azure CLI Python runtime"):
                    module.az_cli("version")
            run.assert_not_called()

    def test_launch_failure_has_context_instead_of_raw_traceback(self) -> None:
        with (
            patch.object(module.shutil, "which", return_value="az.exe"),
            patch.object(module.subprocess, "run", side_effect=FileNotFoundError("missing executable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "Unable to launch Azure CLI"):
                module.az_cli("version")

    def test_cli_failure_is_returned_to_reconciliation(self) -> None:
        result = response(error="authorization failed")
        with (
            patch.object(module.shutil, "which", return_value="az.exe"),
            patch.object(module.subprocess, "run", return_value=result),
        ):
            self.assertIs(result, module.az_cli("rest"))

    def test_usage_read_timeout_is_bounded_and_sanitized(self) -> None:
        with (
            patch.object(module.shutil, "which", return_value="az.exe"),
            patch.object(module.sys, "platform", "win32"),
            patch.object(module.usage, "is_read_command", return_value=True),
            patch.object(module.subprocess, "run",
                         side_effect=subprocess.TimeoutExpired("SECRET", 90)) as run,
        ):
            result = module.az_cli("rest", "--method", "get")
        self.assertEqual(90, run.call_args.kwargs["timeout"])
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual("UsageReadTimeout", json.loads(result.stderr)["error"]["code"])
        self.assertNotIn("SECRET", result.stderr)

    def test_main_reports_launch_failure_and_keeps_nonzero_exit(self) -> None:
        with (
            patch.dict(os.environ, environment(), clear=True),
            patch.object(module.shutil, "which", return_value=None),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(1, module.main())
        self.assertIn("not found on PATH", stderr.getvalue())
        self.assertNotIn("reconciled with", stdout.getvalue())


class TestDashboardAdoFailureHandling(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        content = ADO_JOB.read_text(encoding="utf-8-sig")
        cls.task = re.search(
            r"(?ms)^- task: AzureCLI@2\n  displayName: '10b_reconcile_aifactory_dashboard'\n.*?(?=^- task:|\Z)",
            content,
        ).group(0)
        cls.script = textwrap.dedent(
            cls.task.split("    inlineScript: |\n", 1)[1].split("  env:\n", 1)[0]
        )

    def test_optional_task_cannot_propagate_native_exit_or_stderr(self) -> None:
        self.assertIn("  continueOnError: true\n", self.task)
        self.assertIn("    powerShellIgnoreLASTEXITCODE: true\n", self.task)
        self.assertIn("    failOnStandardError: false\n", self.task)
        self.assertIn("exit 0", self.script)

    def test_actual_powershell_wrapper_handles_success_and_all_failure_paths(self) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell Core is required to execute the ADO wrapper")
        cases = (
            ("windows-2022 python on PATH", 0, False, False, False),
            ("reconciliation error", 37, False, False, False),
            ("unhandled Python error", None, False, False, False),
            ("Python absent", 0, True, False, False),
            ("Python launch failure", 0, False, True, False),
            ("self-hosted python3 fallback", 0, False, False, True),
        )
        for label, returncode, missing, launch_failure, fallback in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as folder:
                stub = Path(folder) / "dashboard stub.py"
                stub.write_text(
                    "raise RuntimeError('simulated dashboard exception')\n"
                    if returncode is None else
                    f"import sys\nprint('dashboard stub ran')\nsys.exit({returncode})\n",
                    encoding="utf-8",
                )
                executable = str(Path(folder) / "missing-python.exe") if launch_failure else sys.executable
                quoted_executable = executable.replace("'", "''")
                discovery = (
                    "function Get-Command { param($Name, $CommandType, $ErrorAction)\n"
                    + ("return $null\n" if missing else
                       ("if ($Name -eq 'python') { return $null }\n" if fallback else
                        "if ($Name -eq 'python3') { throw 'Use python.exe on windows-2022' }\n")
                       + f"return [pscustomobject]@{{Source='{quoted_executable}'}}\n")
                    + "}\n"
                )
                target = (
                    "$(System.DefaultWorkingDirectory)/azure-enterprise-scale-ml/"
                    "environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py"
                )
                quoted_stub = str(stub).replace("`", "``").replace("$", "`$").replace('"', '`"')
                script = self.script.replace(target, quoted_stub)
                self.assertNotIn("$(System.DefaultWorkingDirectory)", script)
                result = subprocess.run(
                    [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", discovery + script],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    check=False, timeout=30,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                if returncode != 0 or missing or launch_failure:
                    self.assertIn("##vso[task.logissue type=warning]", result.stdout)
                    self.assertIn("Continuing the pipeline.", result.stdout)
                else:
                    self.assertIn("dashboard stub ran", result.stdout)
                    self.assertNotIn("task.logissue", result.stdout)


class FakeAz:
    def __init__(self, config, existing=None, host_exists=True) -> None:
        self.config = config
        self.existing = existing
        self.host_exists = host_exists
        self.calls: list[tuple[str, ...]] = []
        self.deployment_parameters = None
        self.rest_body = None
        self.update_error = ""
        self.include_etag = True

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[:2] == ("group", "exists"):
            return response(self.host_exists)
        if args[:2] == ("group", "create"):
            self.host_exists = True
            return response()
        if args[0] == "rest":
            if module.usage.is_read_command(args):
                return response(error='{"error":{"code":"AuthorizationFailed"}}')
            if "--method" in args and args[args.index("--method") + 1] == "put":
                body_arg = args[args.index("--body") + 1]
                self.rest_body = json.loads(
                    Path(body_arg.removeprefix("@")).read_text(encoding="utf-8")
                )
                if self.update_error:
                    return response(error=self.update_error)
                return response({"etag": '"new"'})
            if self.existing is None:
                return response(
                    error='ERROR: {"error":{"code":"ResourceNotFound"}}'
                )
            payload = {
                "tags": {"AI-Factory-Dashboard": "true"},
                "properties": {
                    "metadata": {"aifactoryInventory": self.existing}
                },
            }
            if self.include_etag:
                payload["etag"] = '"current"'
            return response(payload)
        if args[:2] == ("group", "list"):
            subscription = args[args.index("--subscription") + 1]
            if subscription == TEST_SUB:
                return response(error="ERROR: authorization failed")
            if subscription == DEV_SUB:
                return response(
                    [
                        {
                            "name": "vaip-esml-project017-sdc-dev-002-rg",
                            "id": (
                                f"/subscriptions/{DEV_SUB}/resourceGroups/"
                                "vaip-esml-project017-sdc-dev-002-rg"
                            ),
                        }
                    ]
                )
            return response([])
        if args[:2] == ("resource", "list"):
            rg = args[args.index("--resource-group") + 1]
            root = f"/subscriptions/{DEV_SUB}/resourceGroups/{rg}/providers"
            return response(
                [
                    {
                        "id": f"{root}/Microsoft.KeyVault/vaults/project-kv",
                        "name": "project-kv",
                        "type": "Microsoft.KeyVault/vaults",
                        "kind": "",
                    },
                    {
                        "id": f"{root}/Microsoft.Storage/storageAccounts/projectsa",
                        "name": "projectsa",
                        "type": "Microsoft.Storage/storageAccounts",
                        "kind": "",
                    },
                ]
            )
        if args[:2] == ("account", "show"):
            return response(TENANT)
        if args[:3] == ("deployment", "group", "create"):
            parameter_arg = args[args.index("--parameters") + 1]
            self.deployment_parameters = json.loads(
                Path(parameter_arg.removeprefix("@")).read_text(encoding="utf-8")
            )
            return response("https://portal.azure.com/dashboard")
        raise AssertionError(f"Unexpected Azure CLI invocation: {args}")


class TestAifactoryDashboard(unittest.TestCase):
    def config(self):
        with patch.dict(os.environ, environment(), clear=True):
            return module.Config.from_env()

    def test_config_uses_dev_common_rg_as_stable_host(self) -> None:
        config = self.config()
        self.assertEqual(DEV_SUB, config.host_subscription)
        self.assertEqual(
            "vaip-aifactory-esml-common-sdc-dev-002",
            config.dashboard_resource_group,
        )
        self.assertEqual("AIFactory-vaip-sdc-002-dash-01", config.dashboard_name)
        self.assertTrue(
            config.project_pattern("test").fullmatch(
                "vaip-esml-project123-sdc-test-002-rg"
            )
        )
        self.assertFalse(
            config.project_pattern("test").fullmatch(
                "vaip-esml-project123-sdc-dev-002-rg"
            )
        )

    def test_literal_common_override_cannot_move_dashboard_host(self) -> None:
        values = environment() | {
            "DASHBOARD_CURRENT_SUBSCRIPTION_ID": TEST_SUB,
            "DASHBOARD_CURRENT_ENV": "test",
            "DASHBOARD_COMMON_RG": "customer-stage-common-rg",
        }
        with patch.dict(os.environ, values, clear=True):
            config = module.Config.from_env()
        self.assertEqual(DEV_SUB, config.host_subscription)
        self.assertEqual(
            "vaip-aifactory-esml-common-sdc-dev-002",
            config.dashboard_resource_group,
        )
        self.assertEqual(
            "vaip-aifactory-esml-common-sdc-dev-002",
            config.common_resource_group("dev"),
        )
        self.assertEqual(
            "customer-stage-common-rg",
            config.common_resource_group("test"),
        )

    def test_json_uses_environment_specific_common_rg_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "variables.json"
            path.write_text(
                json.dumps(
                    {
                        "dev": {
                            "dev_sub_id": DEV_SUB,
                            "test_sub_id": TEST_SUB,
                            "prod_sub_id": PROD_SUB,
                            "commonResourceGroup_param": "customer-dev-common",
                        },
                        "stage_prod": {
                            "commonResourceGroup_param": "customer-stage-prod-common",
                        },
                    }
                ),
                encoding="utf-8",
            )
            values = environment() | {
                "DASHBOARD_CURRENT_SUBSCRIPTION_ID": TEST_SUB,
                "DASHBOARD_CURRENT_ENV": "test",
                "DASHBOARD_CONFIG_FILE": str(path),
                "DASHBOARD_COMMON_RG": "customer-stage-prod-common",
                "DASHBOARD_DEV_SUBSCRIPTION_ID": "",
                "DASHBOARD_STAGE_SUBSCRIPTION_ID": "",
                "DASHBOARD_PROD_SUBSCRIPTION_ID": "",
            }
            with patch.dict(os.environ, values, clear=True):
                config = module.Config.from_env()
        self.assertEqual("customer-dev-common", config.common_resource_group("dev"))
        self.assertEqual(
            "customer-stage-prod-common", config.common_resource_group("test")
        )
        self.assertEqual(
            "customer-stage-prod-common", config.common_resource_group("prod")
        )
        self.assertEqual(DEV_SUB, config.host_subscription)

    def test_reconcile_replaces_readable_env_and_preserves_inaccessible_env(self) -> None:
        config = self.config()
        existing = {
            "schemaVersion": 1,
            "hubResourceGroups": [],
            "environments": [
                {
                    "name": "test",
                    "displayName": "STAGE",
                    "subscriptionId": TEST_SUB,
                    "commonResourceGroup": {
                        "name": "stage-common",
                        "id": f"/subscriptions/{TEST_SUB}/resourceGroups/stage-common",
                    },
                    "projects": [
                        {
                            "projectNumber": "009",
                            "name": "stage-project",
                            "id": f"/subscriptions/{TEST_SUB}/resourceGroups/stage-project",
                            "dashboardUrl": "https://portal/stage",
                            "shortcuts": [],
                        }
                    ],
                }
            ],
        }
        fake = FakeAz(config, existing)
        inventory, tenant, etag = module.reconcile(config, fake)
        by_name = {item["name"]: item for item in inventory["environments"]}
        self.assertEqual(TENANT, tenant)
        self.assertEqual('"current"', etag)
        self.assertEqual(["017"], [
            project["projectNumber"] for project in by_name["dev"]["projects"]
        ])
        self.assertEqual(["009"], [
            project["projectNumber"] for project in by_name["test"]["projects"]
        ])
        self.assertEqual(
            ["Storage", "Key Vault"],
            [shortcut["label"] for shortcut in by_name["dev"]["projects"][0]["shortcuts"]],
        )

    def test_layout_places_cost_to_right_and_shortcuts_below_project(self) -> None:
        config = self.config()
        fake = FakeAz(config)
        inventory, tenant, _ = module.reconcile(config, fake)
        parts = module.dashboard_parts(inventory, tenant)
        project_rg = next(
            part
            for part in parts
            if part["metadata"].get("asset", {}).get("type") == "ResourceGroup"
            and part["metadata"]["inputs"][0]["value"].endswith(
                "vaip-esml-project017-sdc-dev-002-rg"
            )
        )
        project_cost = next(
            part
            for part in parts
            if part["metadata"]["type"].endswith("CostAnalysisPinPart")
            and part["metadata"]["inputs"][1]["value"].endswith(
                "project017-sdc-dev-002-rg"
            )
        )
        self.assertEqual(
            project_rg["position"]["x"] + project_rg["position"]["colSpan"],
            project_cost["position"]["x"],
        )
        shortcut_parts = [
            part
            for part in parts
            if part["position"]["rowSpan"] == 1
            and part["metadata"].get("asset", {}).get("type")
            in {"Microsoft.Storage/storageAccounts", "Microsoft.KeyVault/vaults"}
        ]
        self.assertEqual(2, len(shortcut_parts))
        self.assertTrue(all(
            part["position"]["y"]
            == project_rg["position"]["y"] + project_rg["position"]["rowSpan"]
            for part in shortcut_parts
        ))

    def test_every_cost_has_an_adjacent_usage_snapshot_without_overlap(self) -> None:
        config = self.config()
        inventory, tenant, _ = module.reconcile(config, FakeAz(config))
        inventory["hubResourceGroups"] = [{
            "name": "hub", "id": module.arm_id(DEV_SUB, "hub"),
        }]
        parts = module.dashboard_parts(inventory, tenant)
        costs = [p for p in parts if p["metadata"]["type"].endswith("CostAnalysisPinPart")]
        for cost in costs:
            position = cost["position"]
            adjacent = [p for p in parts
                        if p["position"]["x"] == position["x"] + position["colSpan"]
                        and p["position"]["y"] == position["y"]]
            self.assertEqual(1, len(adjacent))
            card = adjacent[0]
            self.assertEqual("Extension/HubsExtension/PartType/MarkdownPart", card["metadata"]["type"])
            text = card["metadata"]["settings"]["content"]["settings"]["content"]
            self.assertIn("Activity & solution assets", text)
            self.assertIn("Unavailable", text)
            self.assertIn("Snapshot", text)
        for index, left in enumerate(parts):
            a = left["position"]
            for right in parts[index + 1:]:
                b = right["position"]
                self.assertTrue(
                    a["x"] + a["colSpan"] <= b["x"] or b["x"] + b["colSpan"] <= a["x"]
                    or a["y"] + a["rowSpan"] <= b["y"] or b["y"] + b["rowSpan"] <= a["y"]
                )

    def test_factory_map_is_immediately_right_of_connectivity_and_preserves_hub_cost(self) -> None:
        config = self.config()
        inventory, tenant, _ = module.reconcile(config, FakeAz(config))
        inventory["hubResourceGroups"] = [
            {"name": f"hub-{i}", "id": module.arm_id(DEV_SUB, f"hub-{i}")} for i in range(3)
        ]
        parts = module.dashboard_parts(inventory, tenant)
        maps = [p for p in parts if p["metadata"]["type"].endswith("/PinnedNotebookQueryPart")]
        self.assertEqual(1, len(maps))
        self.assertEqual({"x": 4, "y": 2, "colSpan": 12, "rowSpan": 4}, maps[0]["position"])
        for hub in inventory["hubResourceGroups"]:
            self.assertTrue(any(p["metadata"].get("asset", {}).get("type") == "ResourceGroup"
                                and p["metadata"]["inputs"][0]["value"] == hub["id"] for p in parts))
            self.assertTrue(any(p["metadata"]["type"].endswith("CostAnalysisPinPart")
                                and p["metadata"]["inputs"][0]["value"] == hub["id"] for p in parts))
        for index, left in enumerate(parts):
            a = left["position"]
            for right in parts[index + 1:]:
                b = right["position"]
                self.assertTrue(
                    a["x"] + a["colSpan"] <= b["x"] or b["x"] + b["colSpan"] <= a["x"]
                    or a["y"] + a["rowSpan"] <= b["y"] or b["y"] + b["rowSpan"] <= a["y"]
                )

    def test_factory_map_is_live_blue_inventory_across_exact_known_group_ids(self) -> None:
        config = self.config()
        inventory, _, _ = module.reconcile(config, FakeAz(config))
        hub = module.arm_id(PROD_SUB, "connectivity")
        inventory["hubResourceGroups"] = [
            {"id": hub}, {"id": hub.upper()},
            {"id": module.arm_id(DEV_SUB, "deleted"), "deploymentStatus": "not-deployed"},
            {"id": "/subscriptions/invalid/resourceGroups/foreign"},
        ]
        part = module.factory_map_part(inventory)
        inputs = {item["name"]: item["value"] for item in part["metadata"]["inputs"]}
        content = json.loads(inputs["StepSettings"])
        self.assertEqual("Number of resources by region", content["title"])
        self.assertEqual("map", content["visualization"])
        self.assertEqual(1, content["queryType"])
        self.assertIn(json.dumps(hub.lower()), content["query"])
        self.assertEqual(1, content["query"].count(hub.lower()))
        self.assertNotIn("deleted", content["query"])
        self.assertNotIn("invalid", content["query"])
        self.assertIn("GroupId in~ (", content["query"])
        self.assertEqual({}, inputs["ParameterValues"])
        self.assertIn(inputs["ComponentId"].lower(), [
            group["id"].lower() for group in module.inventory_groups(inventory)
            if group.get("deploymentStatus") != "not-deployed"
        ])
        self.assertEqual("microsoft.resources/subscriptions/resourcegroups", inputs["GalleryResourceType"])
        self.assertNotIn("ConfigurationId", inputs)
        self.assertNotIn("Health", content["query"])
        self.assertEqual("blue", content["mapSettings"]["itemColorSettings"]["thresholdsGrid"][0]["representation"])
        empty = module.factory_map_part({"hubResourceGroups": [], "environments": []})
        self.assertEqual("Extension/HubsExtension/PartType/MarkdownPart", empty["metadata"]["type"])
        self.assertIn("No known factory resource groups", empty["metadata"]["settings"]["content"]["settings"]["content"])

    def test_usage_tile_distinguishes_observed_zero_inventory_and_unavailable(self) -> None:
        resource = {
            "name": "project", "id": module.arm_id(DEV_SUB, "project"),
            "usageSnapshot": {
                "observedAt": "2026-10-08T20:00:00Z",
                "windowStart": "2026-09-08T20:00:00Z", "windowEnd": "2026-10-08T20:00:00Z",
                "metrics": {
                    "activity": {"status": "ok", "value": 1234, "detail": "private@example.com"},
                    "agents": {"status": "ok", "value": 3, "detail": "New agents: 2; classic: 1"},
                    "models": {"status": "ok", "value": 0, "detail": "Registered model names"},
                    "storage": {"status": "ok", "value": 1073741824, "detail": "Latest sample"},
                    "adf": {"status": "unavailable", "value": None, "detail": "No observations"},
                    "search": {"status": "not-deployed", "value": None, "detail": "Not deployed"},
                },
            },
        }
        card = module.usage_part(10, 12, resource, TENANT)
        content = card["metadata"]["settings"]["content"]["settings"]["content"]
        self.assertIn("1,234", content)
        self.assertIn("1.00 GiB", content)
        self.assertIn("**0**", content)
        self.assertIn("Unavailable", content)
        self.assertIn("Not deployed", content)
        self.assertIn("2026-10-08 20:00 UTC", content)
        self.assertIn("30d", content)
        self.assertIn("not runtime usage", content)
        self.assertIn("dashboard-only run", content)
        self.assertIn("activitylog", content)
        self.assertNotIn("private@example.com", content)

    def test_usage_collection_covers_all_retained_rg_records_once_in_scope(self) -> None:
        class Collector:
            def __init__(self):
                self.ids = []

            def collect(self, resource_id):
                self.ids.append(resource_id)
                return {"observedAt": "2026-10-08T20:00:00Z", "metrics": {}}

        current = {"id": module.arm_id(DEV_SUB, "project")}
        duplicate = {"id": current["id"].upper()}
        retained = {"id": module.arm_id(DEV_SUB, "retained")}
        foreign = {"id": module.arm_id(PROD_SUB, "foreign"), "usageSnapshot": {"stale": True}}
        absent = {"id": module.arm_id(DEV_SUB, "absent"), "deploymentStatus": "not-deployed"}
        inventory = {
            "hubResourceGroups": [current, foreign],
            "environments": [
                {"commonResourceGroup": duplicate, "projects": [retained]},
                {"commonResourceGroup": absent, "projects": []},
            ],
        }
        collector = Collector()
        module.collect_usage(inventory, collector, {DEV_SUB})
        self.assertEqual([current["id"], retained["id"]], collector.ids)
        self.assertEqual(current["usageSnapshot"], duplicate["usageSnapshot"])
        self.assertIn("usageSnapshot", retained)
        self.assertNotIn("usageSnapshot", foreign)
        self.assertNotIn("usageSnapshot", absent)

    def test_failed_refresh_retains_only_same_scope_last_success_with_original_time(self) -> None:
        previous = {
            "observedAt": "2026-10-08T22:32:00Z", "windowStart": "2026-09-08T22:32:00Z",
            "windowEnd": "2026-10-08T22:32:00Z",
            "metrics": {
                "agents": {"status": "ok", "value": 12},
                "models": {"status": "ok", "value": 63},
                "search": {"status": "ok", "value": 0},
                "adf": {"status": "unavailable", "value": None},
            },
        }
        fresh = {
            "observedAt": "2026-10-09T01:30:00Z", "windowStart": "2026-09-09T01:30:00Z",
            "windowEnd": "2026-10-09T01:30:00Z",
            "metrics": {
                "agents": {"status": "unavailable", "value": None, "errorCode": "NetworkAccessDenied"},
                "models": {"status": "ok", "value": 64},
                "search": {"status": "unavailable", "value": None, "errorCode": "AccessDenied"},
                "adf": {"status": "unavailable", "value": None},
            },
        }
        original = copy.deepcopy(previous)
        merged = module.merge_usage_snapshot(fresh, previous)
        self.assertEqual(original, previous)
        self.assertEqual("stale", merged["metrics"]["agents"]["status"])
        self.assertEqual(12, merged["metrics"]["agents"]["value"])
        self.assertEqual("2026-10-08T22:32:00Z", merged["metrics"]["agents"]["observedAt"])
        self.assertEqual("NetworkAccessDenied", merged["metrics"]["agents"]["refreshErrorCode"])
        self.assertEqual("2026-10-09T01:30:00Z", merged["metrics"]["agents"]["refreshAttemptedAt"])
        self.assertEqual("ok", merged["metrics"]["models"]["status"])
        self.assertEqual(64, merged["metrics"]["models"]["value"])
        self.assertEqual(0, merged["metrics"]["search"]["value"])
        self.assertEqual("unavailable", merged["metrics"]["adf"]["status"])
        failed_again = copy.deepcopy(fresh)
        failed_again["observedAt"] = "2026-10-09T02:00:00Z"
        repeated = module.merge_usage_snapshot(failed_again, merged)
        self.assertEqual("2026-10-08T22:32:00Z", repeated["metrics"]["agents"]["observedAt"])
        gone = copy.deepcopy(fresh)
        gone["metrics"]["agents"] = {"status": "not-deployed", "value": None}
        self.assertEqual("not-deployed", module.merge_usage_snapshot(gone, previous)["metrics"]["agents"]["status"])

    def test_failed_refresh_ignores_invalid_or_future_success_values(self) -> None:
        fresh = {"observedAt": "2026-10-09T01:30:00Z", "metrics": {"models": {"status": "unavailable", "value": None}}}
        for value in (None, True, -1, float("nan"), float("inf"), 63.25, 2 ** 10000):
            previous = {"observedAt": "2026-10-08T22:32:00Z", "metrics": {"models": {"status": "ok", "value": value}}}
            self.assertIsNone(module.merge_usage_snapshot(fresh, previous)["metrics"]["models"]["value"])
        for timestamp in ("", "not-a-time", "2026-10-10T01:00:00Z", "2026-10-08T22:32:00"):
            previous = {"observedAt": timestamp, "metrics": {"models": {"status": "ok", "value": 63}}}
            self.assertIsNone(module.merge_usage_snapshot(fresh, previous)["metrics"]["models"]["value"])

    def test_usage_refresh_history_is_exact_rg_scoped_and_never_shared_between_projects(self) -> None:
        one = {"id": module.arm_id(DEV_SUB, "one")}
        two = {"id": module.arm_id(DEV_SUB, "two")}
        fresh = {"observedAt": "2026-10-09T01:30:00Z", "metrics": {"models": {"status": "unavailable", "value": None}}}
        history = {
            "hubResourceGroups": [],
            "environments": [{
                "commonResourceGroup": {"id": ""},
                "projects": [{"id": one["id"], "usageSnapshot": {
                    "observedAt": "2026-10-08T22:32:00Z", "metrics": {"models": {"status": "ok", "value": 63}},
                }}],
            }],
        }
        collector = unittest.mock.Mock()
        collector.collect.return_value = fresh
        inventory = {"hubResourceGroups": [], "environments": [{"commonResourceGroup": {"id": ""}, "projects": [one, two]}]}
        module.collect_usage(inventory, collector, {DEV_SUB}, previous_inventory=history)
        self.assertEqual(63, one["usageSnapshot"]["metrics"]["models"]["value"])
        self.assertIsNone(two["usageSnapshot"]["metrics"]["models"]["value"])

    def test_usage_tile_explicitly_labels_last_known_values_and_read_failure(self) -> None:
        card = module.usage_part(10, 12, {
            "id": module.arm_id(DEV_SUB, "one"),
            "usageSnapshot": {
                "observedAt": "2026-10-09T01:30:00Z",
                "metrics": {
                    "agents": {"status": "stale", "value": 12, "observedAt": "2026-10-08T22:32:00Z",
                               "refreshErrorCode": "NetworkAccessDenied"},
                    "models": {"status": "ok", "value": 63},
                    "search": {"status": "unavailable", "value": None, "errorCode": "AccessDenied"},
                },
            },
        }, TENANT)
        text = card["metadata"]["settings"]["content"]["settings"]["content"]
        self.assertIn("**12**", text)
        self.assertIn("last known", text)
        self.assertIn("2026-10-08 22:32 UTC", text)
        self.assertIn("NetworkAccessDenied", text)
        self.assertIn("AccessDenied", text)
        self.assertIn("**63**", text)
        self.assertIn("not current", text)

    def test_eight_discovered_resource_shortcuts_are_kept_in_two_rows(self) -> None:
        config = self.config()
        fake = FakeAz(config)
        inventory, tenant, _ = module.reconcile(config, fake)
        project = inventory["environments"][0]["projects"][0]
        expected = [
            ("AI Foundry", "Microsoft.CognitiveServices/accounts", "foundry"),
            ("Storage", "Microsoft.Storage/storageAccounts", "storage2001"),
            ("Key Vault", "Microsoft.KeyVault/vaults", "vault"),
            ("AI Search", "Microsoft.Search/searchServices", "search"),
            ("Application Insights", "Microsoft.Insights/components", "insights"),
            ("Azure Machine Learning", "Microsoft.MachineLearningServices/workspaces", "aml"),
            ("Azure Databricks", "Microsoft.Databricks/workspaces", "dbx"),
            ("Azure Data Factory", "Microsoft.DataFactory/factories", "adf"),
        ]
        discovered = [
            {"id": f"{project['id']}/providers/{kind}/{name}", "type": kind, "name": name}
            for _, kind, name in expected
        ]
        with patch.object(module, "az_cli", return_value=response(discovered)) as az:
            project["shortcuts"] = module.resource_shortcuts(DEV_SUB, project["name"], [], az)
        self.assertEqual([label for label, _, _ in expected],
                         [item["label"] for item in project["shortcuts"]])
        self.assertEqual(DEV_SUB, az.call_args.args[az.call_args.args.index("--subscription") + 1])
        self.assertEqual(project["name"], az.call_args.args[az.call_args.args.index("--resource-group") + 1])
        parts = module.dashboard_parts(inventory, tenant)
        shortcuts = [
            part for part in parts
            if part["metadata"].get("asset", {}).get("type") in {kind for _, kind, _ in expected}
        ]
        self.assertEqual(8, len(shortcuts))
        for index, (part, resource) in enumerate(zip(shortcuts, discovered)):
            self.assertEqual(resource["id"], part["metadata"]["inputs"][0]["value"])
            self.assertEqual(
                {"x": index if index < 5 else index - 5, "y": 16 if index < 5 else 17,
                 "colSpan": 1, "rowSpan": 1}, part["position"])

    def test_deploy_passes_reconciled_inventory_and_parts_to_bicep(self) -> None:
        config = self.config()
        fake = FakeAz(config)
        inventory, tenant, etag = module.reconcile(config, fake)
        url = module.deploy(config, inventory, tenant, etag, fake)
        self.assertEqual("https://portal.azure.com/dashboard", url)
        parameters = fake.deployment_parameters["parameters"]
        self.assertEqual(inventory, parameters["aifactoryInventory"]["value"])
        self.assertGreater(len(parameters["dashboardParts"]["value"]), 1)
        deployment_call = fake.calls[-1]
        self.assertIn(str(TEMPLATE), deployment_call)
        self.assertIn(config.dashboard_resource_group, deployment_call)

    def test_optional_ml_data_shortcuts_use_second_row_even_without_base_services(self) -> None:
        config = self.config()
        inventory, tenant, _ = module.reconcile(config, FakeAz(config))
        project = inventory["environments"][0]["projects"][0]
        kinds = [
            ("Azure Machine Learning", "Microsoft.MachineLearningServices/workspaces", "aml", "Default"),
            ("Azure Databricks", "Microsoft.Databricks/workspaces", "dbx", ""),
            ("Azure Data Factory", "Microsoft.DataFactory/factories", "adf", ""),
        ]
        for enabled in itertools.product((False, True), repeat=3):
            with self.subTest(enabled=enabled):
                discovered = [
                    {"id": f"{project['id']}/providers/{kind}/{name}", "type": kind,
                     "name": name, "kind": workspace_kind}
                    for active, (_, kind, name, workspace_kind) in zip(enabled, kinds) if active
                ]
                # Foundry hubs/projects share the AML resource provider, but are not AML workspaces.
                discovered += [
                    {"id": f"{project['id']}/providers/{kinds[0][1]}/{kind}",
                     "type": kinds[0][1], "name": f"aaa-{kind}", "kind": kind}
                    for kind in ("Hub", "Project")
                ]
                with patch.object(module, "az_cli", return_value=response(discovered)) as az:
                    project["shortcuts"] = module.resource_shortcuts(DEV_SUB, project["name"], [], az)
                expected = [item for active, item in zip(enabled, kinds) if active]
                self.assertEqual([item[0] for item in expected], [s["label"] for s in project["shortcuts"]])
                # Include a following project to catch overlap with its heading.
                inventory["environments"][0]["projects"] = [
                    project, {**project, "projectNumber": "018", "shortcuts": []},
                ]
                parts = module.dashboard_parts(inventory, tenant)
                shortcuts = [p for p in parts if p["metadata"].get("asset", {}).get("type")
                             in {item[1] for item in kinds}]
                self.assertEqual(len(expected), len(shortcuts))
                for index, part in enumerate(shortcuts):
                    self.assertEqual({"x": index, "y": 17, "colSpan": 1, "rowSpan": 1}, part["position"])
                for index, left in enumerate(parts):
                    a = left["position"]
                    for right in parts[index + 1:]:
                        b = right["position"]
                        self.assertTrue(
                            a["x"] + a["colSpan"] <= b["x"] or b["x"] + b["colSpan"] <= a["x"]
                            or a["y"] + a["rowSpan"] <= b["y"] or b["y"] + b["rowSpan"] <= a["y"]
                        )

    def test_ml_discovery_keeps_legacy_kind_and_preserves_shortcuts_on_read_failure(self) -> None:
        workspace = {"id": "/workspace", "type": "Microsoft.MachineLearningServices/workspaces",
                     "name": "legacy-aml"}
        with patch.object(module, "az_cli", return_value=response([workspace])) as az:
            previous = module.resource_shortcuts(DEV_SUB, "project", [], az)
        self.assertEqual(["Azure Machine Learning"], [s["label"] for s in previous])
        with patch.object(module, "az_cli", return_value=response(error="AuthorizationFailed")) as az:
            self.assertEqual(previous, module.resource_shortcuts(DEV_SUB, "project", previous, az))
        with patch.object(module, "az_cli", return_value=response([])) as az:
            self.assertEqual([], module.resource_shortcuts(DEV_SUB, "project", previous, az))

    def test_existing_dashboard_update_uses_etag_and_rest_put(self) -> None:
        config = self.config()
        existing = {
            "schemaVersion": 1,
            "hubResourceGroups": [],
            "environments": [],
        }
        fake = FakeAz(config, existing)
        inventory, tenant, etag = module.reconcile(config, fake)
        url = module.deploy(config, inventory, tenant, etag, fake)
        update_call = fake.calls[-1]
        self.assertEqual("rest", update_call[0])
        self.assertEqual("put", update_call[update_call.index("--method") + 1])
        self.assertIn('If-Match="current"', update_call)
        self.assertEqual(inventory, fake.rest_body["properties"]["metadata"]["aifactoryInventory"])
        self.assertIn(config.dashboard_id, url)

    def test_existing_dashboard_without_provider_etag_uses_existence_guard(self) -> None:
        config = self.config()
        fake = FakeAz(config, {
            "schemaVersion": 1,
            "hubResourceGroups": [],
            "environments": [],
        })
        fake.include_etag = False
        inventory, tenant, etag = module.reconcile(config, fake)
        self.assertEqual("*", etag)
        module.deploy(config, inventory, tenant, etag, fake)
        update_call = fake.calls[-1]
        self.assertEqual("rest", update_call[0])
        self.assertIn("If-Match=*", update_call)

    def test_missing_dev_common_rg_is_not_created_by_dashboard_step(self) -> None:
        config = self.config()
        fake = FakeAz(config, host_exists=False)
        with self.assertRaisesRegex(RuntimeError, "DEV common resource group"):
            module.reconcile(config, fake)
        self.assertFalse(any(call[:2] == ("group", "create") for call in fake.calls))

    def test_etag_conflict_requests_full_reconciliation_retry(self) -> None:
        config = self.config()
        fake = FakeAz(config)
        fake.update_error = 'ERROR: {"error":{"code":"PreconditionFailed"}}'
        inventory = {
            "schemaVersion": 1,
            "hubResourceGroups": [],
            "environments": [],
        }
        with self.assertRaises(module.ConcurrentUpdate):
            module.deploy(config, inventory, TENANT, '"stale"', fake)

    def test_ado_and_github_run_the_same_reconciliation_script(self) -> None:
        ado = ADO_JOB.read_text(encoding="utf-8-sig")
        gha = GHA_JOB.read_text(encoding="utf-8-sig")
        script_name = "deploy-aifactory-dashboard.py"
        self.assertIn("10b_reconcile_aifactory_dashboard", ado)
        self.assertIn("10b-reconcile-aifactory-dashboard", gha)
        self.assertIn(script_name, ado)
        self.assertIn(script_name, gha)
        self.assertIn("continueOnError: true", ado)
        self.assertIn("continue-on-error: true", gha)
        self.assertIn("DASHBOARD_DEV_SUBSCRIPTION_ID: $(dev_sub_id)", ado)
        self.assertIn(
            "DASHBOARD_DEV_SUBSCRIPTION_ID: ${{ vars.DEV_SUBSCRIPTION_ID }}",
            gha,
        )
        self.assertNotIn(
            "debug_disable_10_aifactory_dashboards",
            ado[ado.index("10b_reconcile_aifactory_dashboard"):ado.index(
                "07_az_remove_ip_from_seeding_keyvault_FW_whitelist"
            )],
        )

    def test_github_syncs_all_environment_subscription_ids_at_repo_scope(self) -> None:
        content = GHA_VARIABLE_SYNC.read_text(encoding="utf-8-sig")
        start = content.index("repo_level_vars=(")
        repo_section = content[start:content.index("\n)", start)]
        for name in (
            "DEV_SUBSCRIPTION_ID",
            "STAGE_SUBSCRIPTION_ID",
            "PROD_SUBSCRIPTION_ID",
        ):
            self.assertIn(f'"{name}"', repo_section)


if __name__ == "__main__":
    unittest.main()
