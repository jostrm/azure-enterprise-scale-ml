"""Offline dashboard-only safety, CI routing, compiled-template and command tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts"
SPEC = importlib.util.spec_from_file_location("dashboard_only", SCRIPTS / "deploy-dashboards-only.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
TEMPLATES = SCRIPTS.parent / "copy_to_local_settings"
ADO = TEMPLATES / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-project" / "infra-project-dashboards.yaml"
GHA = TEMPLATES / "github-actions" / "infra-project-dashboards.yml"
DEV = "11111111-1111-4111-8111-111111111111"
STAGE = "22222222-2222-4222-8222-222222222222"
PROD = "33333333-3333-4333-8333-333333333333"
TENANT = "44444444-4444-4444-8444-444444444444"
FACTORY = "opaque:factory/registered"
SCALE = "opaque:scale/registered"


def payload():
    dev = {
        "tenantId": TENANT, "dev_sub_id": DEV, "test_sub_id": STAGE, "prod_sub_id": PROD,
        "project_number_000": "001", "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "admin_aifactoryPrefixRG": "fixture-", "admin_aifactorySuffixRG": "-001",
        "dev_service_connection": "existing-dev", "test_service_connection": "existing-stage",
        "prod_service_connection": "existing-prod", "useSelfHostedBuildAgent": "true",
        "adminVMBuildAgentPool": "Default", "selfHostedRunnerLabel": "aifactory-admin-vm",
        "myProjectCoverage": {"questions": True, "billing": True},
        "AZURE_CLIENT_SECRET": "SECRET-MUST-NOT-BE-PRINTED",
        "arbitraryCommand": "az group create --name forbidden",
    }
    return {"dev": dev, "stage_prod": {**dev, "enableAISearch": "true"}}


@pytest.fixture
def workspace(monkeypatch):
    path = ROOT / f".dashboard-only-tests-{uuid4().hex}"
    path.mkdir()
    monkeypatch.setattr(runner, "ROOT", path)
    yield path
    shutil.rmtree(path)


@pytest.fixture(autouse=True)
def no_live_azure(monkeypatch):
    def fail(*args):
        pytest.fail("Live Azure commands are forbidden in dashboard-only tests")
    monkeypatch.setattr(runner.shared, "az_cli", fail)


@pytest.fixture(scope="module")
def compiled():
    # Exercise the boundary independently of concurrently edited workbook modules.
    names = re.findall(r"^param (\w+) ", (SCRIPTS.parent / "modules" / "projectDash01.bicep").read_text(encoding="utf-8"), re.M)
    return {
        "parameters": {name: {"defaultValue": ""} for name in names},
        "resources": [
            {"type": "Microsoft.Portal/dashboards"},
            {"type": "Microsoft.Resources/deployments", "properties": {
                "mode": "Incremental", "template": {"resources": []}}},
            {"type": "Microsoft.Resources/deployments", "properties": {
                "mode": "Incremental", "template": {"resources": [{"type": "Microsoft.Insights/workbooks"}]}}},
        ],
    }


def test_actual_bicep_compiled_resource_allowlist():
    bicep = shutil.which("bicep")
    if not bicep:
        pytest.skip("Bicep CLI required for compiled dashboard integration checks")
    result = subprocess.run([bicep, "build", str(SCRIPTS.parent / "modules" / "projectDash01.bicep"),
                             "--stdout"], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    azure = fake_azure(payload(), "dev", {})
    values, cfg, _ = runner.configuration(payload(), "dev", "001")
    params = runner.project_parameters(values, cfg, azure.resources, azure.resources[1]["id"], azure.workspace)
    runner.validate_template(json.loads(result.stdout), params)


def test_supplied_real_azure_cli_compiled_resource_allowlist():
    source = os.environ.get("DASHBOARD_COMPILED_TEMPLATE")
    if not source:
        pytest.skip("Set DASHBOARD_COMPILED_TEMPLATE to validate an actual az bicep build --stdout artifact")
    template = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    azure = fake_azure(payload(), "dev", {})
    values, cfg, _ = runner.configuration(payload(), "dev", "001")
    params = runner.project_parameters(values, cfg, azure.resources, azure.resources[1]["id"], azure.workspace)
    runner.validate_template(template, params)


def arguments(workspace, mode="plan", environment="dev", document=None, project="001"):
    path = workspace / "azurefactory" / "factories" / "fixture" / "projects" / f"project{project}" / "variables.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document or payload(), indent=2), encoding="utf-8")
    args = runner.parse_args([
        "--consumer-root", str(workspace), "--repo-root", ".",
        "--variables-json", str(path.relative_to(workspace)),
        "--environment", environment, "--project", project, "--mode", mode,
    ])
    return args, path


def response(value=None, code=""):
    return subprocess.CompletedProcess([], int(bool(code)), json.dumps(value),
                                       json.dumps({"error": {"code": code}}) if code else "")


class Azure:
    def __init__(self, cfg, template):
        self.cfg, self.template, self.commands = cfg, template, []
        self.current_account = {"id": cfg.current_subscription, "tenantId": TENANT}
        self.resources = [
            {"type": "Microsoft.ManagedIdentity/userAssignedIdentities",
             "name": f"mi-prj{cfg.current_project_number}-sdc-{cfg.current_environment}-abcde0123456789-001"},
            {"type": "Microsoft.Insights/components", "name": "existing-insights",
             "id": f"/subscriptions/{cfg.current_subscription}/resourceGroups/{cfg.current_project_resource_group}"
                   "/providers/Microsoft.Insights/components/existing-insights"},
        ]
        self.workspace = (
            f"/subscriptions/{cfg.current_subscription}/resourceGroups/{cfg.common_resource_group(cfg.current_environment)}"
            "/providers/Microsoft.OperationalInsights/workspaces/existing-workspace"
        )
        self.inventory = {
            "schemaVersion": 1, "hubResourceGroups": [],
            "environments": [{
                "name": env, "displayName": env.upper(), "subscriptionId": sub,
                "commonResourceGroup": {"name": cfg.common_resource_group(env),
                                       "id": runner.shared.arm_id(sub, cfg.common_resource_group(env))},
                "projects": [self.project("005", env, sub)],
            } for env, sub in cfg.subscriptions.items()],
        }
        self.factory = None
        self.parameters = None
        self.conflicts = 0
        self.missing_group = False
        self.existing_groups = None
        self.fail_deployment = False
        self.foreign_tenant = ""
        self.finops = None
        self.fail_finops = False

    def project(self, number, environment, subscription):
        name = f"fixture-esml-project{number}-sdc-{environment}-001-rg"
        return {"name": name, "projectNumber": number,
                "id": runner.shared.arm_id(subscription, name), "shortcuts": [], "dashboardUrl": "https://portal.azure.com/"}

    def __call__(self, *args):
        self.commands.append(args)
        sub = args[args.index("--subscription") + 1] if "--subscription" in args else None
        if args[:2] == ("account", "show"):
            if "--query" in args:
                return subprocess.CompletedProcess([], 0, TENANT, "")
            return response({"id": sub, "tenantId": self.foreign_tenant or TENANT}
                            if sub else self.current_account)
        if args[:2] == ("group", "exists"):
            return response(True)
        if args[:2] == ("group", "show"):
            name = args[args.index("--name") + 1]
            missing = self.missing_group or (self.existing_groups is not None and name not in self.existing_groups)
            return response({"name": name}, "ResourceGroupNotFound" if missing else "")
        if args[:2] == ("group", "list"):
            if self.existing_groups is not None:
                return response([{"name": name} for name in sorted(self.existing_groups)])
            return response([{"name": self.cfg.current_project_resource_group}]
                            if sub == self.cfg.current_subscription else [])
        if args[:2] == ("resource", "list"):
            group = args[args.index("--resource-group") + 1]
            return response(self.resources if group == self.cfg.current_project_resource_group else [])
        if args[:2] == ("resource", "show"):
            return response({"properties": {"WorkspaceResourceId": self.workspace}})
        if args[:2] == ("bicep", "build"):
            return response(self.template)
        if args[:3] == ("deployment", "group", "create"):
            assert args[args.index("--mode") + 1] == "Incremental"
            assert sub == self.cfg.current_subscription
            self.parameters = json.loads(Path(args[args.index("--parameters") + 1][1:]).read_text())
            return response({}, "AuthorizationFailed" if self.fail_deployment else "")
        if args[:1] == ("rest",):
            if runner.shared.usage.is_read_command(args):
                return response(None, "AuthorizationFailed")
            method = args[args.index("--method") + 1]
            url = args[args.index("--url") + 1]
            if url.startswith(f"https://management.azure.com{getattr(self.cfg, 'finops_workbook_id', 'not-yet')}?"):
                assert sub == self.cfg.host_subscription
                assert url == runner.shared.finops_command(self.cfg, method)[6]
                if method == "get":
                    return response(self.finops, "" if self.finops else "ResourceNotFound")
                assert method == "put"
                assert not any(a.startswith("If-None-Match=") for a in args)
                body = json.loads(Path(args[args.index("--body") + 1][1:]).read_text(encoding="utf-8"))
                if self.finops is not None:
                    assert f"If-Match={self.finops['etag']}" in args
                    assert body["etag"] == self.finops["etag"]
                else:
                    assert not any(a.startswith("If-Match=") for a in args)
                    assert "etag" not in body
                    assert self.commands[-2] == runner.shared.finops_command(self.cfg, "get")
                if self.fail_finops:
                    return response({}, "AuthorizationFailed")
                self.finops = body
                self.finops["etag"] = '"finops-v1"'
                return response(self.finops)
            assert url == f"https://management.azure.com{self.cfg.dashboard_id}?api-version={runner.shared.API_VERSION}"
            if method == "get":
                return response({"etag": '"v1"', "properties": {"metadata": {"aifactoryInventory": self.inventory}}})
            assert method == "put" and 'If-Match="v1"' in args
            self.factory = json.loads(Path(args[args.index("--body") + 1][1:]).read_text())
            if self.conflicts:
                self.conflicts -= 1
                self.inventory["environments"][0]["projects"].append(self.project("008", "dev", DEV))
                return response({}, "PreconditionFailed")
            return response({})
        pytest.fail(f"Unexpected command family: {args[:3]}")


def fake_azure(document, environment, template, project="001"):
    _, cfg, _ = runner.configuration(document, environment, project)
    return Azure(cfg, template)


@pytest.mark.parametrize("environment,subscription", [("dev", DEV), ("stage", STAGE), ("test", STAGE), ("prod", PROD)])
def test_exact_environment_subscription(environment, subscription):
    values, cfg, tenant = runner.configuration(payload(), environment, "001")
    assert cfg.current_subscription == subscription
    assert tenant == TENANT
    assert cfg.current_environment == ("test" if environment == "stage" else environment)
    assert values.get("enableAISearch") == (None if environment == "dev" else "true")


@pytest.mark.parametrize("enabled", [False, True])
def test_ml_data_shortcut_flags_reach_dashboard_only_template(enabled):
    flags = ("enableAzureMachineLearning", "addAzureMachineLearning", "enableDatabricks", "enableDatafactory")
    document = payload()
    document["dev"].update({flag: enabled for flag in flags})
    values, cfg, _ = runner.configuration(document, "dev", "001")
    azure = fake_azure(document, "dev", {})
    params = runner.project_parameters(values, cfg, azure.resources, azure.resources[1]["id"], azure.workspace)
    assert {flag: params[flag] for flag in flags} == {flag: enabled for flag in flags}


@pytest.mark.parametrize("key", ["test_sub_id", "tenantId"])
def test_no_dev_fallback_for_stage_identity(key):
    document = payload()
    del document["stage_prod"][key]
    with pytest.raises(ValueError):
        runner.configuration(document, "stage", "001")


@pytest.mark.parametrize("number", ["", "000", "1", "002", None])
def test_required_exact_project001(number):
    document = payload()
    document["dev"]["project_number_000"] = number
    with pytest.raises(ValueError):
        runner.configuration(document, "dev", "001")


def test_cli_requires_project_and_defaults_plan():
    args = runner.parse_args(["--environment", "dev", "--project", "001"])
    assert args.mode == "plan"
    with pytest.raises(SystemExit):
        runner.parse_args(["--environment", "dev"])


@pytest.mark.parametrize("value", ["../variables.json", r"..\variables.json", r"C:\variables.json",
                                  r"C:variables.json", "/variables.json", r"\variables.json",
                                  r"\\server\share\variables.json", "variables.json:stream"])
def test_reject_unbounded_paths(workspace, value):
    with pytest.raises(ValueError):
        runner.bounded_path(workspace, value)


def test_nested_config_is_read_unchanged_and_unknown_keys_never_exported(workspace, capsys):
    args, path = arguments(workspace)
    before = path.read_bytes()
    args.ci_output = "ado"
    result = runner.run(args)
    assert result["pool"] == "Default"
    assert path.read_bytes() == before
    stdout = capsys.readouterr().out
    assert stdout.count("##vso[task.setvariable") == 2
    assert "SECRET" not in stdout and "arbitraryCommand" not in stdout


def test_ephemeral_reviewed_config_is_rejected(workspace):
    args, path = arguments(workspace)
    new = path.with_name(".reviewed-project-config.json")
    path.rename(new)
    args.variables_json = str(new.relative_to(workspace))
    with pytest.raises(ValueError, match="persistent"):
        runner.run(args)


@pytest.mark.parametrize("environment,connection", [("dev", "existing-dev"), ("stage", "existing-stage"), ("prod", "existing-prod")])
def test_service_connection_matches_exact_environment(workspace, environment, connection):
    args, _ = arguments(workspace, environment=environment)
    args.service_connection = connection
    runner.load_configuration(args)
    args.service_connection = "wrong-existing-connection"
    with pytest.raises(ValueError, match="service connection"):
        runner.load_configuration(args)


def register(workspace, document=None):
    value = document or {
        "schema_version": 2,
        "factories": [{"id": FACTORY, "prefix": "fixture-", "region": "swedencentral",
                       "scale_sets": [{"id": SCALE, "suffix": "001", "environment": "stage",
                                       "tenant_id": TENANT, "subscription_id": STAGE}],
                       "projects": [{"id": "logical-project", "number": "001",
                                     "placements": [{"environment": "stage", "scale_set_id": SCALE}]}]}],
    }
    path = workspace / "azurefactory" / "register.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


def test_real_placement_ids_not_path_or_rg_guesses(workspace):
    args, config = arguments(workspace, environment="stage")
    path, _ = register(workspace)
    before = path.read_bytes(), config.read_bytes()
    assert runner.load_configuration(args)[-2:] == (FACTORY, SCALE)
    assert (path.read_bytes(), config.read_bytes()) == before
    args.factory_id = "guessed-prefix"
    with pytest.raises(ValueError, match="placement"):
        runner.load_configuration(args)


@pytest.mark.parametrize("key,bad", [("subscription_id", DEV), ("environment", "dev"), ("suffix", "002"),
                                    ("tenant_id", DEV)])
def test_registered_placement_must_match_target(workspace, key, bad):
    args, _ = arguments(workspace, environment="stage")
    _, document = register(workspace)
    document["factories"][0]["scale_sets"][0][key] = bad
    register(workspace, document)
    with pytest.raises(ValueError, match="placement"):
        runner.load_configuration(args)


def test_absent_register_does_not_fabricate_ids(workspace):
    args, _ = arguments(workspace)
    assert runner.load_configuration(args)[-2:] == ("", "")


@pytest.mark.parametrize("project,relative", [
    ("001", "aifactory/variables.json"),
    ("002", "aifactory/projects/project-002/variables.json"),
])
def test_published_config_and_explicit_ids_need_no_private_register(compiled, workspace, project, relative):
    document = shared_subscription_payload(project)
    args, original = arguments(workspace, "deploy", "dev", document, project)
    published = workspace / relative
    published.parent.mkdir(parents=True, exist_ok=True)
    original.rename(published)
    args.variables_json = relative
    args.factory_id, args.scale_set_id = FACTORY, SCALE
    before = published.read_bytes()
    assert not (workspace / "azurefactory" / "register.json").exists()
    azure = fake_azure(document, "dev", compiled, project)
    azure.existing_groups = EXISTING_DEV_GROUPS
    runner.run(args, azure)
    params = azure.parameters["parameters"]
    assert params["myProjectFactoryId"]["value"] == FACTORY
    assert params["myProjectScaleSetId"]["value"] == SCALE
    assert published.read_bytes() == before
    assert not (workspace / "azurefactory" / "register.json").exists()


@pytest.mark.parametrize("provider,selection,self_hosted", [
    ("ado", "from-config", True), ("ado", "microsoft-hosted", False), ("ado", "self-hosted", True),
    ("github", "github-hosted", False), ("github", "self-hosted-linux", True),
    ("github", "self-hosted-windows", True), ("github", "from-config", True),
])
def test_exact_runner_options(provider, selection, self_hosted):
    settings = runner.runner_settings(payload()["dev"], provider, selection)
    assert settings["use_self_hosted"] == str(self_hosted).lower()
    assert settings["pool"] == "Default"
    if selection == "self-hosted-linux":
        assert json.loads(settings["runs_on"]) == ["self-hosted", "Linux", "aifactory-admin-vm"]


@pytest.mark.parametrize("bad", ["pool\n##vso[task.setvariable variable=x]secret", "$(command)", "bad;pool", "bad]pool"])
def test_ci_routing_cannot_inject_commands(bad):
    document = payload()["dev"]
    document["adminVMBuildAgentPool"] = bad
    with pytest.raises(ValueError):
        runner.runner_settings(document, "ado", "self-hosted")


def test_github_output_is_only_runs_on(workspace, monkeypatch):
    args, _ = arguments(workspace)
    args.ci_output = "github"
    output = workspace / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runner.run(args)
    assert output.read_text() == 'runs_on=["self-hosted","Windows","aifactory-admin-vm"]\n'


def registered_binding(workspace, runner_value, *, on_target=True):
    path, document = register(workspace)
    binding = {"contract_version": 1, "orchestrator": "gha", "writer_id": "dev-writer",
               "repository": "https://github.com/org/consumer", "ref": "refs/heads/main", "shared_remote": False,
               "auth_namespace": "Dev", "locks": {},
               "targets": [{"scale_set_id": SCALE, "resource_group_ids": ["/subscriptions/x/resourceGroups/y"]}]}
    if on_target:
        binding["targets"][0]["execution"] = {"writer_id": "dev-writer", "auth_namespace": "Dev",
                                              "deployment_object_id": DEV, "runner": runner_value}
    else:
        binding["runner"] = runner_value
    document["bindings"] = {FACTORY: {"gha": binding}}
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.mark.parametrize("on_target", [True, False])
def test_registered_github_routing_takes_runner_os_from_the_binding(workspace, monkeypatch, on_target):
    # Observed 2026-10-25 in a registered repository: variables.json has no selfHostedRunnerOS, the Linux runner is
    # only in register.json's binding, and from-config asked for a Windows runner that never picked the job up.
    args, _ = arguments(workspace, environment="stage")
    registered_binding(workspace, {"kind": "self-hosted", "os": "linux",
                                   "labels": ["self-hosted", "linux", "aifactory-admin-vm"]}, on_target=on_target)
    args.ci_output = "github"
    output = workspace / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runner.run(args)
    assert output.read_text() == 'runs_on=["self-hosted","Linux","aifactory-admin-vm"]\n'


def test_explicit_runner_os_in_variables_wins_over_the_binding(workspace, monkeypatch):
    document = payload()
    document["stage_prod"]["selfHostedRunnerOS"] = "Windows"
    args, _ = arguments(workspace, environment="stage", document=document)
    registered_binding(workspace, {"kind": "self-hosted", "os": "linux", "labels": ["self-hosted", "linux"]})
    args.ci_output = "github"
    output = workspace / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runner.run(args)
    assert output.read_text() == 'runs_on=["self-hosted","Windows","aifactory-admin-vm"]\n'


def test_registered_routing_without_a_binding_keeps_the_windows_default(workspace, monkeypatch):
    args, _ = arguments(workspace, environment="stage")
    register(workspace)
    args.ci_output = "github"
    output = workspace / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runner.run(args)
    assert output.read_text() == 'runs_on=["self-hosted","Windows","aifactory-admin-vm"]\n'


def test_compiled_current_module_passes_and_parameters_are_allowlisted(compiled):
    azure = fake_azure(payload(), "dev", compiled)
    values, cfg, _ = runner.configuration(payload(), "dev", "001")
    params = runner.project_parameters(values, cfg, azure.resources, azure.resources[1]["id"], azure.workspace)
    runner.validate_template(compiled, params)
    assert params["aifactorySalt10char"] == "0123456789"
    assert params["myProjectCoverage"] == {}
    assert "arbitraryCommand" not in params and "AZURE_CLIENT_SECRET" not in params
    assert params["myProjectFactoryId"] == params["myProjectScaleSetId"] == ""


def test_explicit_agent_navigation_passes_only_selected_common_workbook(compiled):
    azure = fake_azure(payload(), "dev", compiled)
    values, cfg, _ = runner.configuration(payload(), "dev", "001")
    workbook = f"/subscriptions/{DEV}/resourceGroups/{cfg.common_resource_group('dev')}/providers/Microsoft.Insights/workbooks/55555555-5555-4555-8555-555555555555"
    values["agentMonitoringWorkbookResourceId"] = workbook
    params = runner.project_parameters(values, cfg, azure.resources, azure.resources[1]["id"], azure.workspace)
    assert params["agentMonitoringWorkbookResourceId"] == workbook
    assert "enableAgentMonitoring" not in params
    runner.validate_template(compiled, params)
    values["agentMonitoringWorkbookResourceId"] = workbook.replace(DEV, STAGE)
    with pytest.raises(ValueError, match="outside"):
        runner.project_parameters(values, cfg, azure.resources, azure.resources[1]["id"], azure.workspace)


@pytest.mark.parametrize("mutation", ["role", "rg", "storage", "nested-role", "complete", "linked", "cross-scope", "expression"])
def test_compiled_guard_rejects_nondashboard_writes(compiled, mutation):
    template = copy.deepcopy(compiled)
    if mutation in {"role", "rg", "storage", "expression"}:
        kind = {"role": "Microsoft.Authorization/roleAssignments", "rg": "Microsoft.Resources/resourceGroups",
                "storage": "Microsoft.Storage/storageAccounts", "expression": "[parameters('resourceType')]"}[mutation]
        template["resources"].append({"type": kind})
    elif mutation == "nested-role":
        template["resources"][0]["resources"] = [{"type": "Microsoft.Authorization/roleAssignments"}]
    elif mutation == "cross-scope":
        template["resources"][0]["subscriptionId"] = DEV
    else:
        module = next(r for r in template["resources"] if r["type"] == "Microsoft.Resources/deployments")
        if mutation == "complete":
            module["properties"]["mode"] = "Complete"
        else:
            module["properties"]["templateLink"] = {"uri": "https://example.invalid/unsafe.json"}
    with pytest.raises(RuntimeError):
        runner.validate_template(template, {})


@pytest.mark.parametrize("mutation", ["existing-false", "existing-string", "properties", "other-type", "other-scope",
                                    "arm-v1", "foreign-subscription-binding", "foreign-rg-binding",
                                    "unresolved-subscription-binding"])
def test_existing_reference_cannot_hide_new_resources(compiled, mutation):
    template = copy.deepcopy(compiled)
    module = template["resources"][1]["properties"]
    embedded = module["template"]
    embedded["languageVersion"] = "2.0"
    parameters = {"subscriptionIdDevTestProd": DEV, "commonResourceGroupName": "existing-common-rg"}
    module["parameters"] = {name: {"value": f"[parameters('{name}')]"} for name in parameters}
    group = {
        "existing": True, "type": "Microsoft.Resources/resourceGroups", "apiVersion": "2024-07-01",
        "name": "[parameters('commonResourceGroupName')]",
        "subscriptionId": "[parameters('subscriptionIdDevTestProd')]",
    }
    embedded["resources"] = [group]
    runner.validate_template(template, parameters)
    if mutation == "existing-false":
        group["existing"] = False
    elif mutation == "existing-string":
        group["existing"] = "true"
    elif mutation == "properties":
        group["properties"] = {}
    elif mutation == "other-type":
        group["type"] = "Microsoft.Storage/storageAccounts"
    elif mutation == "other-scope":
        group["subscriptionId"] = PROD
    elif mutation == "foreign-subscription-binding":
        module["parameters"]["subscriptionIdDevTestProd"]["value"] = PROD
    elif mutation == "foreign-rg-binding":
        module["parameters"]["commonResourceGroupName"]["value"] = "different-common-rg"
    elif mutation == "unresolved-subscription-binding":
        module["parameters"]["subscriptionIdDevTestProd"]["value"] = "[variables('arbitrarySubscription')]"
    else:
        embedded.pop("languageVersion")
    with pytest.raises(RuntimeError):
        runner.validate_template(template, parameters)


@pytest.mark.parametrize("environment", ["dev", "stage", "prod"])
def test_plan_reads_existing_telemetry_no_cloud_writes(compiled, workspace, capsys, environment):
    args, path = arguments(workspace, environment=environment)
    azure = fake_azure(payload(), environment, compiled)
    before = path.read_bytes()
    summary = runner.run(args, azure)
    assert summary["mode"] == "plan" and summary["workspaceId"] == azure.workspace
    assert summary["azureWritesPerformed"] is False
    assert summary["existingResourceGroupsVerified"] is True
    assert summary["deploymentMode"] == "Incremental"
    assert summary["preserveExistingFactoryTiles"] is True
    assert path.read_bytes() == before
    assert not any(c[:3] == ("deployment", "group", "create") or "put" in c for c in azure.commands)
    assert "SECRET" not in capsys.readouterr().out


def test_finops_plan_reports_exact_common_workbook_without_writes(compiled, workspace):
    args, _ = arguments(workspace, environment="stage")
    azure = fake_azure(payload(), "stage", compiled)
    summary = runner.run(args, azure)
    assert summary["aiGatewayFinopsWorkbookId"] == azure.cfg.finops_workbook_id
    assert f"/subscriptions/{DEV}/resourceGroups/{azure.cfg.dashboard_resource_group}/" in azure.cfg.finops_workbook_id
    assert "AI Gateway FinOps" in " ".join(summary["writes"])
    assert azure.finops is None
    assert not any("put" in c or c[:3] == ("deployment", "group", "create") for c in azure.commands)


@pytest.mark.parametrize("value", ["missing.json", "../outside.json", r"C:\outside.json"])
def test_finops_bad_config_fails_offline_preflight(workspace, value):
    document = payload()
    document["dev"]["aiGatewayFinopsConfigFile"] = value
    args, _ = arguments(workspace, "deploy", document=document)
    azure = fake_azure(document, "dev", {})
    with pytest.raises(ValueError):
        runner.run(args, azure)
    assert azure.commands == []


def test_finops_duplicate_configuration_keys_fail_offline_preflight(workspace):
    (workspace / "finops.json").write_text(
        '{"applications":[],"applications":[],"rates":[],"trustedTelemetryResourceIds":[]}',
        encoding="utf-8",
    )
    document = payload()
    document["dev"]["aiGatewayFinopsConfigFile"] = "finops.json"
    args, _ = arguments(workspace, "deploy", document=document)
    azure = fake_azure(document, "dev", {})
    with pytest.raises(ValueError):
        runner.run(args, azure)
    assert azure.commands == []


def test_finops_is_shared_across_projects_and_environments():
    ids = set()
    for project in ("001", "002"):
        document = payload()
        for section in document.values():
            section["project_number_000"] = project
        for environment in ("dev", "stage", "prod"):
            _, cfg, _ = runner.configuration(document, environment, project)
            ids.add(cfg.finops_workbook_id)
    assert len(ids) == 1


def test_finops_configuration_uses_dev_common_ownership_not_project_or_stage():
    document = payload()
    document["dev"]["tagsProject"] = {
        "aifactory.factory_id": "factory-a", "aifactory.scaleset_id": "dev-scale",
        "aifactory.project_id": "project001",
    }
    document["stage_prod"]["tagsProject"] = {
        "aifactory.factory_id": "factory-a", "aifactory.scaleset_id": "stage-scale",
        "aifactory.project_id": "project001",
    }
    _, dev, _ = runner.configuration(document, "dev", "001")
    _, stage, _ = runner.configuration(document, "stage", "001")
    assert dev.ownership == {"factory_id": "factory-a", "scaleset_id": "dev-scale"}
    assert stage.ownership == {}


def test_finops_workbook_retains_factory_ownership_on_stage_refresh(compiled, workspace):
    args, _ = arguments(workspace, "deploy", "stage")
    azure = fake_azure(payload(), "stage", compiled)
    azure.inventory["ownership"] = {"factory_id": "factory-a", "scaleset_id": "dev-scale"}
    runner.run(args, azure)
    assert azure.finops["tags"]["aifactory.factory_id"] == "factory-a"
    assert azure.finops["tags"]["aifactory.scaleset_id"] == "dev-scale"
    assert "aifactory.project_id" not in azure.finops["tags"]


def test_finops_failure_stops_before_publishing_common_link(compiled, workspace):
    args, _ = arguments(workspace, "deploy")
    azure = fake_azure(payload(), "dev", compiled)
    azure.fail_finops = True
    with pytest.raises(RuntimeError, match="FinOps"):
        runner.run(args, azure)
    assert azure.parameters is not None
    assert azure.factory is None
    assert not list(workspace.glob(".dashboard-only-*"))


@pytest.mark.parametrize("mutation", ["workbook", "subscription", "method", "extra-argument", "plan"])
def test_finops_boundary_allows_only_its_exact_workbook(workspace, mutation):
    cloud = fake_azure(payload(), "dev", {})
    calls = []

    def transport(*args):
        calls.append(args)
        assert args == runner.shared.finops_command(cloud.cfg, "get")
        return response(None, "ResourceNotFound")

    path = workspace / "body.json"
    path.write_text("{}", encoding="utf-8")
    command = [*runner.shared.finops_command(cloud.cfg, "put"), "--headers",
               "Content-Type=application/json", "--body", f"@{path}"]
    azure = runner.DashboardAzure(cloud.cfg, "plan" if mutation == "plan" else "deploy", transport)
    azure(*runner.shared.finops_command(cloud.cfg, "get"))
    if mutation == "workbook":
        command[command.index("--url") + 1] = command[command.index("--url") + 1].replace(cloud.cfg.finops_workbook_id.split("/")[-1], "another-workbook")
    elif mutation == "subscription":
        command[command.index("--subscription") + 1] = STAGE
    elif mutation == "method":
        command[command.index("--method") + 1] = "patch"
    elif mutation == "extra-argument":
        command.extend(["--url", "https://management.azure.com/other"])
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*command)
    assert calls == [runner.shared.finops_command(cloud.cfg, "get")]


@pytest.mark.parametrize("mutation", ["workbook", "subscription", "extra-argument"])
def test_finops_read_boundary_is_exact_in_plan(mutation):
    _, cfg, _ = runner.configuration(payload(), "dev", "001")
    accepted = []
    azure = runner.DashboardAzure(cfg, "plan", lambda *args: accepted.append(args) or response({}))
    command = list(runner.shared.finops_command(cfg, "get"))
    azure(*command)
    if mutation == "workbook":
        command[6] = command[6].replace(cfg.finops_workbook_id.split("/")[-1], "another-workbook")
    elif mutation == "subscription":
        command[2] = STAGE
    else:
        command.extend(["--url", "https://management.azure.com/other"])
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*command)
    assert len(accepted) == 1


def test_finops_uses_documented_api_and_fetches_full_saved_content():
    _, cfg, _ = runner.configuration(payload(), "dev", "001")
    endpoint = f"https://management.azure.com{cfg.finops_workbook_id}?api-version=2021-08-01"
    assert runner.shared.finops_command(cfg, "get") == (
        "rest", "--subscription", DEV, "--method", "get", "--url",
        endpoint + "&canFetchContent=true", "--only-show-errors",
    )
    assert runner.shared.finops_command(cfg, "put") == (
        "rest", "--subscription", DEV, "--method", "put", "--url",
        endpoint, "--only-show-errors",
    )

@pytest.mark.parametrize("failure", ["exact", "foreign", "forbidden", "invalid"])
def test_finops_boundary_classifies_only_exact_codeless_404_before_sanitizing(workspace, failure):
    cloud = fake_azure(payload(), "dev", {})
    cfg = cloud.cfg
    resource = cfg.finops_workbook_id if failure != "foreign" else "/foreign/SECRET"
    stderr = "ERROR: Not Found(" + json.dumps({"Message": f"Resource '{resource}' is not found."}) + ")"
    if failure == "forbidden":
        stderr = stderr.replace("Not Found", "Forbidden")
    elif failure == "invalid":
        stderr = "ERROR: Not Found({SECRET unparseable})"

    def transport(*args):
        if args == runner.shared.finops_command(cfg, "get"):
            cloud.commands.append(args)
            return subprocess.CompletedProcess(args, 1, "", stderr)
        return cloud(*args)

    azure = runner.DashboardAzure(cfg, "deploy", transport)
    safe = azure(*runner.shared.finops_command(cfg, "get"))
    assert safe.stdout == "" and "SECRET" not in safe.stderr
    assert runner.shared.error_code(safe) == ("ResourceNotFound" if failure == "exact" else "AzureCommandFailed")
    if failure == "exact":
        prepared = runner.shared.prepare_finops_workbook(cfg, {}, azure)
        runner.shared.deploy_finops_workbook(cfg, prepared, azure, directory=workspace)
        assert cloud.finops is not None
    else:
        with pytest.raises(RuntimeError, match="Unable to read"):
            runner.shared.prepare_finops_workbook(cfg, {}, azure)
        assert not any("put" in c for c in cloud.commands)


@pytest.mark.parametrize("outcome", ["success", "failed", "exception"])
def test_finops_boundary_create_requires_instance_missing_read_and_consumes_it(workspace, outcome):
    cloud = fake_azure(payload(), "dev", {})
    cfg = cloud.cfg
    path = workspace / "body.json"
    path.write_text(json.dumps({"properties": {}}), encoding="utf-8")
    command = (*runner.shared.finops_command(cfg, "put"), "--headers",
               "Content-Type=application/json", "--body", f"@{path}")
    calls = []

    def transport(*args):
        calls.append(args)
        if args == runner.shared.finops_command(cfg, "get"):
            return response(None, "ResourceNotFound")
        if outcome == "exception":
            raise OSError("uncertain transport failure")
        return response({}, "NotImplemented" if outcome == "failed" else "")

    azure = runner.DashboardAzure(cfg, "deploy", transport)
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*command)
    assert calls == []
    azure(*runner.shared.finops_command(cfg, "get"))
    if outcome == "exception":
        with pytest.raises(OSError):
            azure(*command)
    else:
        azure(*command)
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*command)
    assert calls == [runner.shared.finops_command(cfg, "get"), command]


def test_finops_boundary_does_not_share_missing_read_between_instances(workspace):
    cloud = fake_azure(payload(), "dev", {})
    first = runner.DashboardAzure(cloud.cfg, "deploy", cloud)
    first(*runner.shared.finops_command(cloud.cfg, "get"))
    second = runner.DashboardAzure(cloud.cfg, "deploy", cloud)
    path = workspace / "body.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="prohibited"):
        second(*runner.shared.finops_command(cloud.cfg, "put"), "--headers",
               "Content-Type=application/json", "--body", f"@{path}")
    assert cloud.commands == [runner.shared.finops_command(cloud.cfg, "get")]


@pytest.mark.parametrize("body", ['{"etag":"stale"}', '{"etag":null}', "{invalid}", "[]"])
def test_finops_boundary_create_rejects_etag_or_invalid_body_after_missing_read(workspace, body):
    cloud = fake_azure(payload(), "dev", {})
    azure = runner.DashboardAzure(cloud.cfg, "deploy", cloud)
    azure(*runner.shared.finops_command(cloud.cfg, "get"))
    path = workspace / "body.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*runner.shared.finops_command(cloud.cfg, "put"), "--headers",
              "Content-Type=application/json", "--body", f"@{path}")
    assert cloud.commands == [runner.shared.finops_command(cloud.cfg, "get")]


@pytest.mark.parametrize("latest", ["present", "forbidden", "invalid", "exception"])
def test_finops_boundary_recheck_invalidates_prior_missing_read(workspace, latest):
    cloud = fake_azure(payload(), "dev", {})
    responses = [response(None, "ResourceNotFound")]
    if latest == "present":
        responses.append(response({"etag": '"new"'}))
    elif latest == "forbidden":
        responses.append(response(None, "AuthorizationFailed"))
    elif latest == "invalid":
        responses.append(subprocess.CompletedProcess([], 0, "invalid", ""))
    calls = []

    def transport(*args):
        calls.append(args)
        if latest == "exception" and len(calls) == 2:
            raise OSError("read failed")
        return responses.pop(0)

    azure = runner.DashboardAzure(cloud.cfg, "deploy", transport)
    azure(*runner.shared.finops_command(cloud.cfg, "get"))
    if latest == "exception":
        with pytest.raises(OSError):
            azure(*runner.shared.finops_command(cloud.cfg, "get"))
    else:
        azure(*runner.shared.finops_command(cloud.cfg, "get"))
    path = workspace / "body.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*runner.shared.finops_command(cloud.cfg, "put"), "--headers",
              "Content-Type=application/json", "--body", f"@{path}")
    assert len(calls) == 2


@pytest.mark.parametrize("header,body_etag", [
    ("If-None-Match=*", None), ("If-Match=*", "*"), ('If-Match="v1"', None),
    ('If-Match="v1"', '"v2"'), ("If-Match=", ""),
])
def test_finops_boundary_rejects_unsupported_or_mismatched_preconditions(workspace, header, body_etag):
    cloud = fake_azure(payload(), "dev", {})
    azure = runner.DashboardAzure(cloud.cfg, "deploy", lambda *a: pytest.fail("Unsafe write reached Azure"))
    path = workspace / "body.json"
    path.write_text(json.dumps({"etag": body_etag}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*runner.shared.finops_command(cloud.cfg, "put"), "--headers", header,
              "Content-Type=application/json", "--body", f"@{path}")


def finops_settings():
    gateway = f"/subscriptions/{DEV}/resourceGroups/existing/providers/Microsoft.ApiManagement/service/gateway"
    return {
        "applications": [{"gatewayResourceId": gateway, "apimSubscriptionId": "consumer-17",
                          "applicationId": "app-a", "teamId": "team-a"}],
        "rates": [{"gatewayResourceId": gateway, "backendHost": "existing.openai.azure.com",
                   "deployment": "reviewed-deployment", "model": "reviewed-model",
                   "validFrom": "2026-01-01T00:00:00Z", "validTo": "2027-01-01T00:00:00Z",
                   "currency": "USD", "meter": "openai-text-tokens", "billingMode": "consumption",
                   "inputPerMillion": 2, "cachedInputPerMillion": 1, "outputPerMillion": 8}],
        "trustedTelemetryResourceIds": [],
    }


def finops_parameters(workbook):
    return {p["name"]: p for item in workbook["items"]
            for p in item.get("content", {}).get("parameters", [])}


def test_finops_repeat_preserves_saved_pricing_mapping_and_viewer_defaults(compiled, workspace):
    args, _ = arguments(workspace, "deploy")
    azure = fake_azure(payload(), "dev", compiled)
    runner.run(args, azure)
    saved = json.loads(azure.finops["properties"]["serializedData"])
    parameters = finops_parameters(saved)
    parameters["Configuration"]["value"] = json.dumps(runner.shared.finops_renderer().validate_config(finops_settings()))
    parameters["Workspaces"]["value"] = [azure.workspace]
    parameters["GroupBy"]["value"] = "User"
    parameters["TimeRange"]["value"] = {"durationMs": 86400000}
    azure.finops["properties"]["displayName"] = "Operator-owned FinOps title"
    # Upgrade content, but not the operator-owned settings.
    saved["items"].insert(0, {"type": 1, "content": {"json": "old workbook version"}})
    azure.finops["properties"]["serializedData"] = json.dumps(saved)
    before = len(azure.commands)
    runner.run(args, azure)
    assert azure.finops["properties"]["displayName"] == "Operator-owned FinOps title"
    new = finops_parameters(json.loads(azure.finops["properties"]["serializedData"]))
    for key in ("Configuration", "Workspaces", "GroupBy", "TimeRange"):
        if key == "Configuration":
            assert json.loads(new[key]["value"]) == json.loads(parameters[key]["value"])
        else:
            assert new[key]["value"] == parameters[key]["value"]
    writes = [c for c in azure.commands[before:] if "put" in c and azure.cfg.finops_workbook_id in c[c.index("--url") + 1]]
    assert len(writes) == 1 and 'If-Match="finops-v1"' in writes[0]
    assert "old workbook version" not in azure.finops["properties"]["serializedData"]
    before = len(azure.commands)
    runner.run(args, azure)
    assert not any("put" in c and azure.cfg.finops_workbook_id in c[c.index("--url") + 1] for c in azure.commands[before:])


def test_finops_explicit_dev_configuration_is_canonical_for_stage(compiled, workspace):
    settings = finops_settings()
    (workspace / "finops.json").write_text(json.dumps(settings), encoding="utf-8")
    document = payload()
    document["dev"]["aiGatewayFinopsConfigFile"] = "finops.json"
    document["stage_prod"]["aiGatewayFinopsConfigFile"] = "must-not-use-project-stage-settings.json"
    args, path = arguments(workspace, "deploy", "stage", document)
    before = path.read_bytes()
    azure = fake_azure(document, "stage", compiled)
    runner.run(args, azure)
    saved = json.loads(azure.finops["properties"]["serializedData"])
    assert json.loads(finops_parameters(saved)["Configuration"]["value"]) == runner.shared.finops_renderer().validate_config(settings)
    saved_parameters = finops_parameters(saved)
    saved_parameters["Configuration"]["value"] = json.dumps({"applications": [], "rates": [], "trustedTelemetryResourceIds": []})
    azure.finops["properties"]["serializedData"] = json.dumps(saved)
    runner.run(args, azure)
    updated = json.loads(azure.finops["properties"]["serializedData"])
    assert json.loads(finops_parameters(updated)["Configuration"]["value"]) == runner.shared.finops_renderer().validate_config(settings)
    assert path.read_bytes() == before


@pytest.mark.parametrize("failure", ["read-denied", "unmanaged", "invalid-config", "no-etag"])
def test_finops_saved_settings_fail_closed_before_project_writes(compiled, workspace, failure):
    args, _ = arguments(workspace, "deploy")
    azure = fake_azure(payload(), "dev", compiled)
    runner.run(args, azure)
    if failure == "unmanaged":
        azure.finops["tags"] = {}
    elif failure == "invalid-config":
        notebook = json.loads(azure.finops["properties"]["serializedData"])
        finops_parameters(notebook)["Configuration"]["value"] = "{invalid-json"
        azure.finops["properties"]["serializedData"] = json.dumps(notebook)
    elif failure == "no-etag":
        azure.finops.pop("etag")
        azure.finops["properties"]["category"] = "older category"
    before = len(azure.commands)

    def request(*args):
        if failure == "read-denied" and args == runner.shared.finops_command(azure.cfg, "get"):
            return response({}, "AuthorizationFailed")
        return azure(*args)

    with pytest.raises((ValueError, RuntimeError)):
        runner.run(args, request)
    assert not any("put" in c or c[:3] == ("deployment", "group", "create") for c in azure.commands[before:])


def test_finops_saved_settings_errors_do_not_echo_configuration(compiled, workspace):
    args, _ = arguments(workspace, "deploy")
    azure = fake_azure(payload(), "dev", compiled)
    runner.run(args, azure)
    notebook = json.loads(azure.finops["properties"]["serializedData"])
    finops_parameters(notebook)["Configuration"]["value"] = '{"SECRET-KEY":1,"SECRET-KEY":2}'
    azure.finops["properties"]["serializedData"] = json.dumps(notebook)
    with pytest.raises((ValueError, RuntimeError)) as error:
        runner.run(args, azure)
    assert "SECRET" not in str(error.value)


def shared_subscription_payload(project="001"):
    document = payload()
    for section in document.values():
        section.update(project_number_000=project, dev_sub_id=DEV, test_sub_id=DEV, prod_sub_id=DEV)
    return document


EXISTING_DEV_GROUPS = {
    "fixture-esml-common-sdc-dev-001",
    "fixture-esml-project001-sdc-dev-001-rg",
    "fixture-esml-project002-sdc-dev-001-rg",
}


@pytest.mark.parametrize("environment,project", [("stage", "001"), ("prod", "001"), ("dev", "003")])
@pytest.mark.parametrize("mode", ["plan", "deploy"])
def test_missing_selected_group_fails_first_without_creating_anything(workspace, environment, project, mode):
    document = shared_subscription_payload(project)
    args, path = arguments(workspace, mode, environment, document, project)
    before = path.read_bytes()
    azure = fake_azure(document, environment, {}, project)
    azure.existing_groups = EXISTING_DEV_GROUPS
    with pytest.raises(RuntimeError) as error:
        runner.run(args, azure)
    assert azure.cfg.current_project_resource_group in str(error.value)
    assert "does not exist" in str(error.value) and "No Azure writes were attempted" in str(error.value)
    assert "never creates RGs or changes roles" in str(error.value)
    assert path.read_bytes() == before
    group_reads = [c for c in azure.commands if c[:2] == ("group", "show")]
    assert len(group_reads) == 1
    assert all(c[:2] in {("account", "show"), ("group", "show")} for c in azure.commands)


def test_shared_subscription_dev001_then_dev002_preserves_factory_inventory(compiled, workspace, capsys):
    previous_inventory = None
    for project in ("001", "002"):
        document = shared_subscription_payload(project)
        args, path = arguments(workspace, "deploy", "dev", document, project)
        before = path.read_bytes()
        azure = fake_azure(document, "dev", compiled, project)
        azure.existing_groups = EXISTING_DEV_GROUPS
        if previous_inventory is not None:
            azure.inventory = previous_inventory
        else:
            for environment in azure.inventory["environments"]:
                environment["projects"] = []
        summary = runner.run(args, azure)
        assert summary["project"] == project and summary["environment"] == "dev"
        assert summary["projectResourceGroup"] in EXISTING_DEV_GROUPS
        assert summary["commonResourceGroupStatus"] == {"dev": "deployed", "test": "not-deployed", "prod": "not-deployed"}
        assert path.read_bytes() == before
        previous_inventory = azure.factory["properties"]["metadata"]["aifactoryInventory"]
        environments = {e["name"]: e for e in previous_inventory["environments"]}
        assert {p["projectNumber"] for p in environments["dev"]["projects"]} == {"001", "002"}
        assert environments["test"]["projects"] == environments["prod"]["projects"] == []
        write = next(c for c in azure.commands if c[:3] == ("deployment", "group", "create"))
        assert write[write.index("--resource-group") + 1] == azure.cfg.current_project_resource_group
    assert "SECRET" not in capsys.readouterr().out


def test_missing_common_tiles_are_marked_without_dropping_project_history():
    cloud = fake_azure(shared_subscription_payload(), "dev", {})
    cloud.existing_groups = EXISTING_DEV_GROUPS
    azure = runner.DashboardAzure(cloud.cfg, "plan", cloud)
    inventory, tenant, _ = runner.reconcile(azure)
    body = runner.factory_resource(cloud.cfg, inventory, tenant)
    parts = body["properties"]["lenses"][0]["parts"]
    serialized_parts = json.dumps(parts)
    for environment in inventory["environments"][1:]:
        common = environment["commonResourceGroup"]
        assert common["deploymentStatus"] == "not-deployed"
        assert common["id"] not in serialized_parts
        assert common["id"] in json.dumps(body["properties"]["metadata"]["aifactoryInventory"])
        assert f"{environment['displayName']} common resources not deployed" in serialized_parts
        old_project = next(p for p in environment["projects"] if p["projectNumber"] == "005")
        assert old_project["id"] in serialized_parts
    assert not any("put" in command for command in cloud.commands)


def test_common_group_access_failure_is_not_reported_as_not_deployed():
    cloud = fake_azure(shared_subscription_payload(), "dev", {})
    common = cloud.cfg.common_resource_group("test")

    def denied(*args):
        if args[:2] == ("group", "show") and common in args:
            return response(None, "AuthorizationFailed")
        return cloud(*args)

    azure = runner.DashboardAzure(cloud.cfg, "plan", denied)
    inventory, tenant, _ = runner.reconcile(azure)
    stage = next(e for e in inventory["environments"] if e["name"] == "test")
    assert stage["commonResourceGroup"]["deploymentStatus"] == "unverified"
    parts = runner.factory_resource(cloud.cfg, inventory, tenant)["properties"]["lenses"][0]["parts"]
    assert stage["commonResourceGroup"]["id"] in json.dumps(parts)


def test_previously_missing_common_group_reappears_without_losing_history():
    cloud = fake_azure(shared_subscription_payload(), "dev", {})
    cloud.existing_groups = EXISTING_DEV_GROUPS
    azure = runner.DashboardAzure(cloud.cfg, "plan", cloud)
    inventory, _, _ = runner.reconcile(azure)
    cloud.inventory = inventory
    cloud.existing_groups = EXISTING_DEV_GROUPS | {cloud.cfg.common_resource_group("test")}
    inventory, tenant, _ = runner.reconcile(azure)
    stage = next(e for e in inventory["environments"] if e["name"] == "test")
    assert stage["commonResourceGroup"]["deploymentStatus"] == "deployed"
    parts = runner.factory_resource(cloud.cfg, inventory, tenant)["properties"]["lenses"][0]["parts"]
    assert stage["commonResourceGroup"]["id"] in json.dumps(parts)
    assert any(p["projectNumber"] == "005" for p in stage["projects"])


def test_deploy_only_incremental_dashboard_writes_with_etag_retry(compiled, workspace, capsys):
    args, path = arguments(workspace, "deploy", "stage")
    register(workspace)
    before = path.read_bytes()
    azure = fake_azure(payload(), "stage", compiled)
    azure.conflicts = 1
    azure.inventory["environments"][1]["projects"].append(azure.project("001", "test", STAGE))
    azure.inventory["environments"][1]["projects"][-1]["shortcuts"] = [{
        "id": f"/subscriptions/{STAGE}/resourceGroups/previous/providers/Microsoft.Search/searchServices/retained",
        "type": "Microsoft.Search/searchServices", "label": "AI Search",
    }]
    runner.run(args, azure)
    writes = [c for c in azure.commands if c[:3] == ("deployment", "group", "create") or "put" in c]
    assert len(writes) == 4
    assert not any(arg.startswith("If-") for arg in writes[1])
    assert all("If-Match=" in " ".join(c) for c in writes[2:])
    assert sum(azure.cfg.finops_workbook_id in c[c.index("--url") + 1] for c in writes if "--url" in c) == 1
    assert "AI Gateway" in json.dumps(azure.factory)
    assert "estimated" in json.dumps(azure.factory).lower()
    assert azure.parameters["parameters"]["myProjectFactoryId"]["value"] == FACTORY
    assert azure.parameters["parameters"]["myProjectScaleSetId"]["value"] == SCALE
    assert azure.parameters["parameters"]["myProjectCoverage"]["value"] == {}
    environments = azure.factory["properties"]["metadata"]["aifactoryInventory"]["environments"]
    assert all(any(p["projectNumber"] == "005" for p in e["projects"]) for e in environments)
    assert any(p["projectNumber"] == "008" for p in environments[0]["projects"])
    shortcuts = next(p for p in environments[1]["projects"] if p["projectNumber"] == "001")["shortcuts"]
    assert {s["label"] for s in shortcuts} == {"AI Search", "Application Insights"}
    assert next(s for s in shortcuts if s["label"] == "Application Insights")["id"] == azure.resources[1]["id"]
    assert next(s for s in shortcuts if s["label"] == "AI Search")["id"].endswith("/searchServices/retained")
    assert path.read_bytes() == before
    assert not list(workspace.glob(".dashboard-only-*"))
    assert "SECRET" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["account", "tenant", "missing-rg", "mi", "appinsights", "template"])
def test_preflight_failures_stop_before_any_writes(compiled, workspace, failure):
    args, _ = arguments(workspace, "deploy")
    azure = fake_azure(payload(), "dev", copy.deepcopy(compiled))
    if failure == "account":
        azure.current_account["id"] = PROD
    elif failure == "tenant":
        azure.foreign_tenant = PROD
    elif failure == "missing-rg":
        azure.missing_group = True
    elif failure == "mi":
        azure.resources[0]["name"] = "mi-wrong-no-fallback"
    elif failure == "appinsights":
        azure.resources.append(azure.resources[1].copy())
    else:
        azure.template["resources"].append({"type": "Microsoft.Storage/storageAccounts"})
    with pytest.raises(RuntimeError):
        runner.run(args, azure)
    assert not any(c[:3] == ("deployment", "group", "create") or "put" in c for c in azure.commands)


def test_deployment_failure_does_not_update_factory_and_cleans_artifacts(compiled, workspace):
    args, _ = arguments(workspace, "deploy")
    azure = fake_azure(payload(), "dev", compiled)
    azure.fail_deployment = True
    with pytest.raises(RuntimeError, match="No factory update"):
        runner.run(args, azure)
    assert not any("put" in c for c in azure.commands)
    assert not list(workspace.glob(".dashboard-only-*"))


def test_azure_boundary_rejects_general_mutation_and_sanitizes_errors():
    _, cfg, _ = runner.configuration(payload(), "dev", "001")
    azure = runner.DashboardAzure(cfg, "deploy", lambda *args: response(None, "SECRET raw CLI text"))
    for command in [("group", "create"), ("role", "assignment", "create"), ("account", "set"),
                    ("deployment", "sub", "create"), ("rest", "--method", "delete"),
                    ("vm", "start"), ("vm", "create")]:
        with pytest.raises(RuntimeError, match="prohibited"):
            azure(*command)
    result = azure("account", "show", "--output", "json", "--only-show-errors")
    assert "SECRET" not in result.stderr and result.stdout == ""


def test_usage_reads_pass_existing_boundary_and_keep_failures_unavailable():
    cloud = fake_azure(payload(), "dev", {})
    azure = runner.DashboardAzure(cloud.cfg, "plan", cloud)
    group_id = runner.shared.arm_id(DEV, cloud.cfg.current_project_resource_group)
    snapshot = azure.usage_collector.collect(group_id)
    reads = [args for args in cloud.commands if args[:1] == ("rest",)]
    assert reads
    assert all(runner.shared.usage.is_read_command(args) for args in reads)
    assert snapshot["metrics"]["activity"]["status"] == "unavailable"
    assert snapshot["metrics"]["activity"]["value"] is None
    before = len(cloud.commands)
    assert azure.usage_collector.collect(group_id) == snapshot
    assert len(cloud.commands) == before
    command = list(reads[0])
    command[command.index("--subscription") + 1] = PROD
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*command)
    command = list(reads[0])
    command[command.index("--method") + 1] = "post"
    with pytest.raises(RuntimeError, match="prohibited"):
        azure(*command)


def test_dashboard_only_retains_previous_same_project_measurements_on_failed_refresh():
    cloud = fake_azure(payload(), "dev", {})
    previous = cloud.project("001", "dev", DEV)
    previous["usageSnapshot"] = {
        "observedAt": "2026-10-08T22:32:00Z",
        "metrics": {
            "agents": {"status": "ok", "value": 12},
            "models": {"status": "ok", "value": 63},
        },
    }
    cloud.inventory["environments"][0]["projects"].append(previous)
    azure = runner.DashboardAzure(cloud.cfg, "plan", cloud)

    class FailedRefresh:
        def collect(self, group):
            return {"observedAt": "2026-10-09T01:30:00Z", "metrics": {
                "agents": {"status": "unavailable", "value": None, "errorCode": "AccessDenied"},
                "models": {"status": "ok", "value": 64},
            }}

    azure.usage_collector = FailedRefresh()
    inventory, _, _ = runner.reconcile(azure)
    project = next(p for p in inventory["environments"][0]["projects"] if p["projectNumber"] == "001")
    metrics = project["usageSnapshot"]["metrics"]
    assert metrics["agents"]["status"] == "stale" and metrics["agents"]["value"] == 12
    assert metrics["agents"]["observedAt"] == "2026-10-08T22:32:00Z"
    assert metrics["models"]["status"] == "ok" and metrics["models"]["value"] == 64
    assert all("put" not in command for command in cloud.commands)


@pytest.mark.parametrize("stderr,code,transient,delay", [
    ('ERROR: {"error":{"code":"403","message":"Public network access is disabled. SECRET"}}', "NetworkAccessDenied", False, None),
    ("ERROR: Forbidden SECRET", "AccessDenied", False, None),
    ('{"error":{"code":"429"}} Retry-After: 12 SECRET', "Throttled", True, 12),
    ('{"error":{"code":"501"}} SECRET', "ReadFailed", False, None),
    ('{"error":{"code":"503"}} Retry-After: 99 SECRET', "ServiceUnavailable", True, 0),
])
def test_usage_boundary_preserves_safe_failure_class_and_retry_budget(stderr, code, transient, delay):
    cloud = fake_azure(payload(), "dev", {})
    captured = []

    def denied(*args):
        captured.append(args)
        return subprocess.CompletedProcess(args, 1, "", stderr)

    azure = runner.DashboardAzure(cloud.cfg, "plan", denied)
    collector = runner.shared.usage.Collector(azure, sleeper=lambda seconds: None)
    snapshot = collector.collect(runner.shared.arm_id(DEV, cloud.cfg.current_project_resource_group))
    command = next(args for args in captured if args[:1] == ("rest",))
    result = azure(*command)
    assert runner.shared.usage.read_failure_code(result) == code
    assert runner.shared.usage.is_transient_read_failure(result) is transient
    assert "SECRET" not in result.stderr
    assert "SECRET" not in json.dumps(snapshot)
    safe = json.loads(result.stderr)
    assert safe.get("retry-after") == delay


def test_workflows_are_manual_plan_default_safe_oidc_and_shared_runner():
    ado = yaml.load(ADO.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    gha = yaml.load(GHA.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert ado["trigger"] == ado["pr"] == "none"
    assert set(gha["on"]) == {"workflow_dispatch"}
    ado_params = {p["name"]: p for p in ado["parameters"]}
    assert ado_params["mode"]["default"] == "plan"
    assert ado_params["runnerSelection"]["default"] == "from-config"
    assert ado_params["selfHostedPool"]["default"] == "Default"
    assert gha["on"]["workflow_dispatch"]["inputs"]["mode"]["default"] == "plan"
    for name in ("factory_id", "scale_set_id"):
        assert ado_params[name]["default"] == ""
        assert gha["on"]["workflow_dispatch"]["inputs"][name]["default"] == ""
        assert gha["on"]["workflow_dispatch"]["inputs"][name]["required"] == "false"
    assert gha["permissions"] == {"contents": "read", "id-token": "write"}
    assert set(gha["jobs"]["configure"]["outputs"]) == {"runs_on"}
    for path in (ADO, GHA):
        source = path.read_text()
        assert "DEV common dashboard + AI Gateway FinOps workbook read/write" in source
        assert "dev.aiGatewayFinopsConfigFile" in source
        assert "No APIM, network, RBAC or diagnostics changes" in source
        assert source.count("deploy-dashboards-only.py") == 2
        assert "--mode $env:DASHBOARD_MODE" in source
        assert "az deployment" not in source and "az group create" not in source
        assert "create-or-update" not in source and "AIFACTORY_CONFIG_JSON" not in source
        assert "continueOnError" not in source
        assert "e5c353e7" not in source and "f0fe8b33" not in source
        assert source.count("'--factory-id', $env:FACTORY_ID") == 2
        assert source.count("'--scale-set-id', $env:SCALE_SET_ID") == 2
    assert "variables.test_service_connection" in ADO.read_text()
    login = next(s for s in gha["jobs"]["dashboards"]["steps"] if s.get("uses") == "azure/login@v2")
    assert login["with"]["client-id"] == "${{ secrets.AZURE_CLIENT_ID }}"


def test_explicit_ado_hosted_override_bypasses_offline_self_hosted_pool(workspace, capsys):
    args, _ = arguments(workspace)
    args.ci_output = "ado"
    args.runner_selection = "microsoft-hosted"
    settings = runner.run(args)
    assert settings["use_self_hosted"] == "false"
    assert "variable=use_self_hosted;isOutput=true]false" in capsys.readouterr().out
    doc = yaml.load(ADO.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    configure_pool = doc["jobs"][0]["pool"]
    assert configure_pool["${{ else }}"]["vmImage"] == "windows-2022"
    assert "from-config" in next(key for key in configure_pool if key.startswith("${{ elseif"))
    job = next(iter(doc["jobs"][1].values()))[0]
    assert job["${{ else }}"]["pool"]["vmImage"] == "windows-2022"
    assert "resolve.use_self_hosted'], 'false'" in job["${{ else }}"]["condition"]
    assert "resolve.use_self_hosted'], 'true'" in job["${{ if eq(runner, 'self_hosted') }}"]["condition"]
    assert "az vm" not in ADO.read_text(encoding="utf-8")


def test_workflow_powershell_parses():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core required for workflow command syntax checks")
    docs = [yaml.load(p.read_text(encoding="utf-8"), Loader=yaml.BaseLoader) for p in (ADO, GHA)]
    scripts = []

    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"pwsh", "inlineScript", "run"} and isinstance(value, str):
                    scripts.append(value)
                else:
                    collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)
    collect(docs)
    assert len(scripts) == 4
    command = (
        "$errors = $null; $tokens = $null; "
        "[System.Management.Automation.Language.Parser]::ParseInput("
        "$env:DASHBOARD_SCRIPT, [ref]$tokens, [ref]$errors) > $null; "
        "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 }"
    )
    for script in scripts:
        subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                       env={**os.environ, "DASHBOARD_SCRIPT": script},
                       capture_output=True, text=True, check=True)


@pytest.mark.parametrize("file", [ADO, GHA])
@pytest.mark.parametrize("exit_code", [0, 37])
@pytest.mark.parametrize("explicit_ids", [False, True])
def test_workflow_command_preserves_literal_arguments_and_failure(workspace, file, exit_code, explicit_ids):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell Core required for workflow command execution checks")
    doc = yaml.load(file.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if file == GHA:
        script = doc["jobs"]["dashboards"]["steps"][-1]["run"]
    else:
        job = next(iter(doc["jobs"][1].values()))[0]
        script = job["steps"][-1]["inputs"]["inlineScript"]
    stub = workspace / "azure-enterprise-scale-ml" / "environment_setup" / "aifactory" / "bicep" / "scripts" / "deploy-dashboards-only.py"
    stub.parent.mkdir(parents=True)
    record = workspace / "arguments.json"
    stub.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "Path(os.environ['ARGUMENT_RECORD']).write_text(json.dumps(sys.argv[1:]))\n"
        f"sys.exit({exit_code})\n", encoding="utf-8",
    )
    discover = (
        "function Get-Command { param($Name, $CommandType, $ErrorAction); "
        "return [pscustomobject]@{Source=$env:PYTHON_TEST_EXECUTABLE} }\n"
    )
    env = {
        **os.environ, "CONSUMER_ROOT": str(workspace), "ARGUMENT_RECORD": str(record),
        "PYTHON_TEST_EXECUTABLE": sys.executable, "DASHBOARD_MODE": "plan",
        "CONFIG_FILE": "azurefactory/factories/space folder/projects/project001/variables.json",
        "TARGET_ENVIRONMENT": "stage", "PROJECT_NUMBER": "001", "SERVICE_CONNECTION": "existing-stage",
        "FACTORY_ID": FACTORY if explicit_ids else "", "SCALE_SET_ID": SCALE if explicit_ids else "",
    }
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", discover + script],
                            env=env, capture_output=True, text=True)
    assert result.returncode == exit_code, result.stderr
    args = json.loads(record.read_text())
    assert args[args.index("--variables-json") + 1] == env["CONFIG_FILE"]
    assert args[args.index("--mode") + 1] == "plan"
    assert args[args.index("--project") + 1] == "001"
    if explicit_ids:
        assert args[args.index("--factory-id") + 1] == FACTORY
        assert args[args.index("--scale-set-id") + 1] == SCALE
    else:
        assert "--factory-id" not in args and "--scale-set-id" not in args
