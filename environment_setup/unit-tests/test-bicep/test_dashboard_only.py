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
            method = args[args.index("--method") + 1]
            assert args[args.index("--url") + 1].startswith(f"https://management.azure.com{self.cfg.dashboard_id}?")
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
    assert len(writes) == 3
    assert all("If-Match=" in " ".join(c) for c in writes[1:])
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
