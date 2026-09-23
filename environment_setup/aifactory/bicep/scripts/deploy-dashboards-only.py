#!/usr/bin/env python3
"""Manual dashboard refresh: existing RGs/telemetry only; plan is read-only.

Requires Azure CLI (with Bicep) and Python 3.10+. The selected account must
match variables.json. Grant resource discovery/read at the relevant existing
RGs, dashboard write at the DEV common RG, and deployment/dashboard/workbook
write at the selected project RG. This command never grants permissions.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from uuid import uuid4


SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
spec = importlib.util.spec_from_file_location(
    "dashboard_only_reconciler", SCRIPTS / "deploy-aifactory-dashboard.py"
)
shared = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = shared
spec.loader.exec_module(shared)

BOOL_PARAMETERS = frozenset("""
addAIFoundry enableAIFoundry enableAIFoundryHub addAIFoundryHub
enableAFoundryCaphost enableAISearch addAISearch enableCosmosDB
enableAzureOpenAI enableAIServices enableAzureAIVision enableAzureSpeech
enableAIDocIntelligence enableContentSafety enableBing enableBingCustomSearch
enableAzureMachineLearning addAzureMachineLearning enableAKS enableAksForAzureML
enableDatafactory enableDatabricks enableContainerApps enableFunction enableWebApp
enableLogicApps enableEventHubs enableBotService enablePostgreSQL enableRedisCache
enableSQLDatabase enableElasticsearch allowPublicAccessWhenBehindVnet
enablePublicGenAIAccess enablePublicAccessWithPerimeter cmk useCommonACR
""".split())
SKU_PARAMETERS = frozenset(
    f"sku{service}{environment}"
    for service in (
        "AISearch", "AIServices", "OpenAI", "ContentSafety", "Vision", "Speech",
        "DocIntelligence", "PostgreSQL", "Redis", "SQLDatabase", "Elastic",
        "WebApp", "Function",
    )
    for environment in ("Dev", "StageProd")
)
TEXT_PARAMETERS = SKU_PARAMETERS | {"cosmosKind", "aksSkuName"}
RESOURCE_ID = re.compile(
    r"/subscriptions/([0-9a-f-]{36})/resourceGroups/([^/]+)/providers/"
    r"([^/]+/[^/]+)/([^/]+)", re.I
)
ALLOWED_TYPES = {
    "microsoft.resources/deployments",
    "microsoft.portal/dashboards",
    "microsoft.insights/workbooks",
}


def bounded_path(root: Path, value: str, *, directory: bool = False) -> Path:
    text(value, "Repository-relative path")
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or PureWindowsPath(value).drive or PureWindowsPath(value).root:
        raise ValueError("Paths must be repository-relative.")
    if ".." in candidate.parts or ":" in value:
        raise ValueError("Paths must not contain parent traversal or alternate streams.")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Path must remain inside the checked-out consumer repository.")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError("Required checked-out directory/file was not found.")
    return path


def text(value: object, key: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not empty):
        raise ValueError(f"{key} must be a string.")
    if len(value) > 2048 or any(ord(c) < 32 for c in value) or "$(" in value:
        raise ValueError(f"{key} contains unresolved variables or control characters.")
    return value


def guid(value: object, key: str) -> str:
    result = text(value, key)
    if not shared.GUID.fullmatch(result):
        raise ValueError(f"{key} must be an Azure GUID.")
    return result


def boolean(value: object, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError(f"{key} must be true or false.")


def selected_values(payload: dict, environment: str) -> dict:
    # Same dev baseline + stage_prod overlay as apply-json-config-overrides.py.
    if not isinstance(payload, dict) or not isinstance(payload.get("dev"), dict):
        raise ValueError("variables.json must contain a dev object.")
    stage = payload.get("stage_prod", {} if environment == "dev" else None)
    if not isinstance(stage, dict):
        raise ValueError("stage_prod must be an object.")
    return {**payload["dev"], **(stage if environment != "dev" else {})}


def configuration(payload: dict, environment: str, project: str = "") -> tuple[dict, object, str]:
    environment = "test" if environment == "stage" else environment
    if environment not in {"dev", "test", "prod"}:
        raise ValueError("Select exactly one environment: dev, test (stage), or prod.")
    values = selected_values(payload, environment)
    number = str(values.get("project_number_000", ""))
    if not shared.PROJECT_NUMBER.fullmatch(number) or number == "000":
        raise ValueError("project_number_000 must be a three-digit project number.")
    if not project or not shared.PROJECT_NUMBER.fullmatch(project) or project != number:
        raise ValueError("--project must match project_number_000 in the selected configuration.")
    section = payload["dev" if environment == "dev" else "stage_prod"]
    tenant = guid(section.get("tenantId"), "tenantId in the selected environment section")
    subscriptions = {}
    overrides = {}
    for env, key in (("dev", "dev_sub_id"), ("test", "test_sub_id"), ("prod", "prod_sub_id")):
        env_values = {**payload["dev"], **payload.get("stage_prod", {})} if env != "dev" else payload["dev"]
        exact = payload.get("dev" if env == "dev" else "stage_prod", {})
        raw = exact.get(key, "")
        # An unconfigured, nonselected environment is preserved, never targeted.
        subscriptions[env] = (
            guid(raw, key) if env in {"dev", environment}
            else raw if isinstance(raw, str) and shared.GUID.fullmatch(raw) else ""
        )
        overrides[env] = text(
            env_values.get("commonResourceGroup_param", ""), "commonResourceGroup_param", empty=True
        )
    location = text(values.get("admin_location"), "admin_location")
    suffix = text(values.get("admin_locationSuffix"), "admin_locationSuffix")
    if not re.fullmatch(r"[a-z0-9]+", location) or not re.fullmatch(r"[a-z0-9]+", suffix):
        raise ValueError("Azure location and location suffix must be lowercase alphanumeric.")
    config = shared.Config(
        current_subscription=subscriptions[environment],
        current_environment=environment,
        current_project_number=number,
        location=location,
        location_suffix=suffix,
        resource_group_prefix=text(values.get("admin_aifactoryPrefixRG", ""), "admin_aifactoryPrefixRG", empty=True),
        resource_group_suffix=text(values.get("admin_aifactorySuffixRG"), "admin_aifactorySuffixRG"),
        project_prefix=text(values.get("projectPrefix", "esml-"), "projectPrefix", empty=True),
        project_suffix=text(values.get("projectSuffix", "-rg"), "projectSuffix", empty=True),
        common_name=text(values.get("vnetResourceGroupBase", "esml-common"), "vnetResourceGroupBase"),
        common_overrides=overrides,
        subscriptions=subscriptions,
        central_dns=boolean(values.get("centralDnsZoneByPolicyInHub", False), "centralDnsZoneByPolicyInHub"),
        private_dns_subscription="",
        private_dns_resource_group="",
        vnet_subscription="",
        vnet_resource_group="",
        template_file=SCRIPTS.parent / "modules" / "aifactory-dash-01.bicep",
    )
    for name in (config.current_project_resource_group, *(config.common_resource_group(e) for e in subscriptions)):
        if not shared.RG_NAME.fullmatch(name) or name.endswith("."):
            raise ValueError("Configuration resolves to an invalid resource group name.")
    return values, config, tenant


def read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ValueError("Cannot read checked-out configuration as JSON.") from None
    if not isinstance(payload, dict):
        raise ValueError("Configuration must be a JSON object.")
    return payload


def registered_ids(consumer: Path, cfg, tenant: str, values: dict,
                   factory_id: str = "", scale_set_id: str = "") -> tuple[str, str]:
    """Resolve opaque IDs from a matching registered project placement, never names."""
    path = consumer / "azurefactory" / "register.json"
    explicit = (
        text(factory_id or values.get("myProjectFactoryId", ""), "myProjectFactoryId", empty=True),
        text(scale_set_id or values.get("myProjectScaleSetId", ""), "myProjectScaleSetId", empty=True),
    )
    if not path.exists() and not path.is_symlink():
        return explicit
    document = read_json(bounded_path(consumer, "azurefactory/register.json"))
    if document.get("schema_version") != 2:
        raise ValueError("Dashboard ID discovery requires a schema_version 2 register.")
    environment = "stage" if cfg.current_environment == "test" else cfg.current_environment
    matches = []
    for factory in document.get("factories", []):
        if (str(factory.get("prefix", "")).rstrip("-") != cfg.resource_group_prefix.rstrip("-")
                or factory.get("region") != cfg.location):
            continue
        scales = {s["id"]: s for s in factory.get("scale_sets", []) if isinstance(s, dict) and "id" in s}
        for project in factory.get("projects", []):
            if str(project.get("number", "")) != cfg.current_project_number:
                continue
            for placement in project.get("placements", []):
                scale = scales.get(placement.get("scale_set_id"), {})
                if (placement.get("environment") == environment and scale.get("environment") == environment
                        and str(scale.get("tenant_id", "")).lower() == tenant.lower()
                        and str(scale.get("subscription_id", "")).lower() == cfg.current_subscription.lower()
                        and str(scale.get("suffix", "")).lstrip("-") == cfg.resource_group_suffix.lstrip("-")):
                    pair = (text(factory.get("id"), "registered factory ID"),
                            text(scale.get("id"), "registered scale set ID"))
                    if all(not requested or requested == actual for requested, actual in zip(explicit, pair)):
                        matches.append(pair)
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        raise ValueError("Register must contain exactly one matching factory/project/environment placement; explicit IDs must agree.")
    return matches[0]


def load_configuration(args):
    consumer = Path(args.consumer_root).resolve()
    repo = bounded_path(consumer, args.repo_root, directory=True)
    if repo != ROOT:
        raise ValueError("--repo-root must identify the checked-out submodule containing this runner.")
    path = bounded_path(consumer, args.variables_json)
    if path.name != "variables.json":
        raise ValueError("Use the persistent registered variables.json, not an ephemeral reviewed configuration.")
    payload = read_json(path)
    values, cfg, tenant = configuration(payload, args.environment, args.project)
    factory_id, scale_set_id = registered_ids(
        consumer, cfg, tenant, values, args.factory_id, args.scale_set_id
    )
    if args.service_connection:
        section = payload["dev" if cfg.current_environment == "dev" else "stage_prod"]
        expected = text(section.get(f"{cfg.current_environment}_service_connection"),
                        "Selected environment service connection")
        if args.service_connection != expected:
            raise ValueError("ADO service connection must match the exact environment section in variables.json.")
    return consumer, values, cfg, tenant, factory_id, scale_set_id


def runner_settings(values: dict, provider: str, selection: str) -> dict:
    allowed = {"from-config", "self-hosted", "microsoft-hosted"} if provider == "ado" else {
        "from-config", "self-hosted", "github-hosted", "self-hosted-windows", "self-hosted-linux"
    }
    if selection not in allowed:
        raise ValueError("Runner selection is not supported by this CI provider.")
    self_hosted = (boolean(values.get("useSelfHostedBuildAgent", False), "useSelfHostedBuildAgent")
                   if selection == "from-config" else selection.startswith("self-hosted"))

    def label(value, key):
        value = text(value, key)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,127}", value):
            raise ValueError(f"{key} contains unsupported pool/runner-label characters.")
        return value

    pool = label(values.get("adminVMBuildAgentPool") or "Default", "adminVMBuildAgentPool")
    os_name = {"self-hosted-windows": "Windows", "self-hosted-linux": "Linux"}.get(
        selection, values.get("selfHostedRunnerOS") or "Windows"
    )
    if not isinstance(os_name, str) or os_name.lower() not in {"windows", "linux"}:
        raise ValueError("selfHostedRunnerOS must be Windows or Linux.")
    custom = label(values.get("selfHostedRunnerLabel") or "aifactory-admin-vm", "selfHostedRunnerLabel")
    runs_on = ["self-hosted", os_name.title(), custom] if self_hosted else "ubuntu-latest"
    return {"use_self_hosted": str(self_hosted).lower(), "pool": pool,
            "runs_on": json.dumps(runs_on, separators=(",", ":"))}


def emit_ci_output(settings: dict, provider: str) -> None:
    # Only these routing values cross job boundaries; never export the JSON/config.
    if provider == "ado":
        for key in ("use_self_hosted", "pool"):
            print(f"##vso[task.setvariable variable={key};isOutput=true]{settings[key]}")
    else:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"runs_on={settings['runs_on']}\n")


def json_response(result: subprocess.CompletedProcess, purpose: str):
    if result.returncode:
        raise RuntimeError(
            f"{purpose} failed. Check the signed-in identity's resource/RG read access "
            "and the explicit subscription. No resources or roles will be created to fix access."
        )
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError(f"{purpose} returned invalid JSON.") from None


class DashboardAzure:
    """A fail-closed boundary shared by discovery, compilation and deployment."""

    def __init__(self, config, mode: str, az=None):
        self.config = config
        self.mode = mode
        self.az = az or shared.az_cli
        self.previous_inventory = {}
        self.deployment_command = None

    @property
    def dashboard_url(self):
        return f"https://management.azure.com{self.config.dashboard_id}?api-version={shared.API_VERSION}"

    def __call__(self, *args):
        args = tuple(args)
        read = args[:2] in {
            ("account", "show"), ("group", "exists"), ("group", "show"),
            ("group", "list"), ("resource", "list"), ("resource", "show"),
        }
        compile_only = args == compile_command()
        factory_read = args == factory_command(self, "get")
        factory_write = (
            args[:1] == ("rest",) and "--method" in args
            and args[args.index("--method") + 1] == "put"
            and "--url" in args and args[args.index("--url") + 1] == self.dashboard_url
            and "--headers" in args
            and any(a.startswith(("If-Match=", "If-None-Match=")) for a in args)
        )
        deployment = self.deployment_command is not None and args == self.deployment_command
        if not (read or compile_only or factory_read or (self.mode == "deploy" and (factory_write or deployment))):
            raise RuntimeError("Non-dashboard Azure command prohibited.")
        if not compile_only:
            if "--subscription" in args:
                sub = args[args.index("--subscription") + 1]
                if sub.lower() not in {s.lower() for s in self.config.subscriptions.values() if s}:
                    raise RuntimeError("Azure command subscription is outside the configured scope.")
            elif args != ("account", "show", "--output", "json", "--only-show-errors"):
                raise RuntimeError("Azure commands require an explicit configured subscription.")
        result = self.az(*args)
        if result.returncode:
            code = shared.error_code(result)
            if not code or not re.fullmatch(r"[A-Za-z0-9]+", code):
                code = "AzureCommandFailed"
            # Never replay raw CLI errors: they can include parameter/configuration values.
            return subprocess.CompletedProcess(args, result.returncode, "", json.dumps({"error": {"code": code}}))
        if factory_read:
            payload = json_response(result, "Reading factory dashboard")
            self.previous_inventory = payload.get("properties", {}).get("metadata", {}).get("aifactoryInventory", {})
        return result


def compile_command() -> tuple[str, ...]:
    return (
        "bicep", "build", "--file", str(SCRIPTS.parent / "modules" / "projectDash01.bicep"),
        "--stdout", "--only-show-errors",
    )


def factory_command(azure: DashboardAzure, method: str) -> tuple[str, ...]:
    return (
        "rest", "--subscription", azure.config.host_subscription, "--method", method,
        "--url", azure.dashboard_url, "--only-show-errors",
    )


def verify_accounts(azure: DashboardAzure, tenant: str) -> None:
    cfg = azure.config
    account = json_response(azure("account", "show", "--output", "json", "--only-show-errors"), "Reading selected account")
    if str(account.get("id", "")).lower() != cfg.current_subscription.lower() or str(account.get("tenantId", "")).lower() != tenant.lower():
        raise RuntimeError("Selected Azure account does not match variables.json tenant/subscription. Select the intended account before running.")
    for subscription in set(cfg.subscriptions.values()) - {""}:
        result = azure("account", "show", "--subscription", subscription, "--output", "json", "--only-show-errors")
        if result.returncode and subscription not in {cfg.current_subscription, cfg.host_subscription}:
            print("WARNING: A nonselected inventory subscription is unavailable; its previous tiles will be preserved.")
            continue
        account = json_response(result, "Checking configured subscription tenant")
        if str(account.get("id", "")).lower() != subscription.lower() or str(account.get("tenantId", "")).lower() != tenant.lower():
            raise RuntimeError("A configured inventory subscription belongs to a different tenant.")


def require_group(azure: DashboardAzure, subscription: str, name: str) -> None:
    result = azure("group", "show", "--subscription", subscription, "--name", name, "--output", "json", "--only-show-errors")
    if result.returncode:
        missing = shared.error_code(result) in {"ResourceGroupNotFound", "ResourceNotFound"}
        raise RuntimeError(
            f"Required existing resource group {name} "
            f"{'does not exist' if missing else 'could not be read'} in subscription {subscription}. "
            + ("Select an already deployed environment/project. " if missing else
               "Verify the configuration and the pipeline identity's existing RG read access. ")
            + "No Azure writes were attempted; dashboard-only mode never creates RGs or changes roles."
        )
    if not isinstance(json_response(result, "Reading existing resource group"), dict):
        raise RuntimeError("Resource group lookup returned an invalid response.")


def resource_id(value: object, expected_type: str, subscriptions: set[str], group: str = "") -> str:
    value = text(value, "Telemetry resource ID")
    match = RESOURCE_ID.fullmatch(value)
    if (
        not match or not shared.GUID.fullmatch(match[1])
        or match[1].lower() not in {s.lower() for s in subscriptions}
        or match[3].lower() != expected_type.lower()
        or (group and match[2].lower() != group.lower())
    ):
        raise ValueError("Telemetry resource ID is outside the selected resource type/subscription/RG scope.")
    return value


def resources(azure: DashboardAzure, group: str) -> list:
    value = json_response(azure(
        "resource", "list", "--subscription", azure.config.current_subscription,
        "--resource-group", group, "--output", "json", "--only-show-errors",
    ), f"Discovering resources in {group}")
    if not isinstance(value, list):
        raise RuntimeError("Resource discovery returned an invalid response.")
    return value


def telemetry(azure: DashboardAzure, values: dict, project_resources: list) -> tuple[str, str]:
    cfg = azure.config
    sub = cfg.current_subscription
    insight = values.get("myProjectApplicationInsightsResourceId", "")
    if not insight:
        matches = [r.get("id") for r in project_resources if str(r.get("type", "")).lower() == "microsoft.insights/components"]
        if len(matches) != 1:
            raise RuntimeError("Expected one existing project Application Insights component. Set myProjectApplicationInsightsResourceId to its exact ARM ID when ambiguous/missing.")
        insight = matches[0]
    insight = resource_id(insight, "Microsoft.Insights/components", {sub}, cfg.current_project_resource_group)
    component = json_response(azure(
        "resource", "show", "--subscription", sub, "--ids", insight,
        "--api-version", "2020-02-02", "--output", "json", "--only-show-errors",
    ), "Reading existing project Application Insights")
    workspace = values.get("myProjectLogAnalyticsResourceId", "") or component.get("properties", {}).get("WorkspaceResourceId", "")
    if not workspace:
        matches = [r.get("id") for r in resources(azure, cfg.common_resource_group(cfg.current_environment))
                   if str(r.get("type", "")).lower() == "microsoft.operationalinsights/workspaces"]
        if len(matches) != 1:
            raise RuntimeError("Cannot uniquely discover an existing Log Analytics workspace. Set myProjectLogAnalyticsResourceId to its exact ARM ID.")
        workspace = matches[0]
    workspace = resource_id(workspace, "Microsoft.OperationalInsights/workspaces", set(cfg.subscriptions.values()) - {""})
    workspace_sub = RESOURCE_ID.fullmatch(workspace)[1]
    json_response(azure(
        "resource", "show", "--subscription", workspace_sub, "--ids", workspace,
        "--api-version", "2022-10-01", "--output", "json", "--only-show-errors",
    ), "Reading the existing telemetry workspace (resource-level read access required)")
    return insight, workspace


def project_parameters(values: dict, cfg, project_resources: list, insight: str, workspace: str,
                       factory_id: str = "", scale_set_id: str = "") -> dict:
    common_suffix = text(values.get("admin_commonResourceSuffix", "-001"), "admin_commonResourceSuffix")
    suffix = text(values.get("admin_prjResourceSuffix", "-001"), "admin_prjResourceSuffix")
    if not re.fullmatch(r"-\d{3}", suffix) or not re.fullmatch(r"-\d{3}", common_suffix):
        raise ValueError("Resource suffixes must have the canonical -NNN format.")
    pattern = re.compile(
        rf"mi-prj{cfg.current_project_number}-{re.escape(cfg.location_suffix)}-"
        rf"{cfg.current_environment}-[a-z0-9]{{5}}(?P<salt>[a-z0-9]{{10}}){re.escape(suffix)}",
        re.I,
    )
    salts = {
        match["salt"] for item in project_resources
        if str(item.get("type", "")).lower() == "microsoft.managedidentity/userassignedidentities"
        and (match := pattern.fullmatch(str(item.get("name", ""))))
    }
    if len(salts) != 1:
        raise RuntimeError("Cannot uniquely recover the existing project MI naming salt. Verify project_number_000, region, environment, resource suffix and RG read access. Manual/legacy salt fallbacks are prohibited.")
    salt = salts.pop()
    params = {
        "env": cfg.current_environment,
        "projectNumber": cfg.current_project_number,
        "location": cfg.location,
        "locationSuffix": cfg.location_suffix,
        "commonRGNamePrefix": cfg.resource_group_prefix,
        "aifactorySuffixRG": cfg.resource_group_suffix,
        "commonResourceSuffix": common_suffix,
        "resourceSuffix": suffix,
        "aifactorySalt10char": salt,
        "randomValue": salt,
        "commonResourceGroupName": cfg.common_resource_group(cfg.current_environment),
        "subscriptionIdDevTestProd": cfg.current_subscription,
        "projectPrefix": cfg.project_prefix,
        "projectSuffix": cfg.project_suffix,
        "genaiSubnetId": "",
        "aksSubnetId": "",
        "acaSubnetId": "",
        "enableMyProjectDashboard": True,
        "myProjectApplicationInsightsResourceId": insight,
        "myProjectLogAnalyticsResourceId": workspace,
        "myProjectFactoryId": text(factory_id or values.get("myProjectFactoryId", ""), "myProjectFactoryId", empty=True),
        "myProjectScaleSetId": text(scale_set_id or values.get("myProjectScaleSetId", ""), "myProjectScaleSetId", empty=True),
        "myProjectTelemetryEnvironment": text(
            values.get("myProjectTelemetryEnvironment", "stage" if cfg.current_environment == "test" else cfg.current_environment),
            "myProjectTelemetryEnvironment",
        ),
        "myProjectCoverage": {},
        "tags": {},
    }
    for key in BOOL_PARAMETERS & values.keys():
        params[key] = boolean(values[key], key)
    for key in TEXT_PARAMETERS & values.keys():
        params[key] = text(values[key], key)
    if values.get("agentMonitoringWorkbookResourceId"):
        params["agentMonitoringWorkbookResourceId"] = resource_id(
            values["agentMonitoringWorkbookResourceId"], "Microsoft.Insights/workbooks",
            {cfg.current_subscription}, cfg.common_resource_group(cfg.current_environment),
        )
    for source, target in (("acr_SKU", "acrSku"), (
        "skuTierAksDev" if cfg.current_environment == "dev" else "skuTierAksStageProd", "aksSkuTier"
    )):
        if source in values:
            params[target] = text(values[source], source)
    return params


def validate_template(template: dict, parameters: dict) -> None:
    counts = {"microsoft.portal/dashboards": 0, "microsoft.insights/workbooks": 0}
    reference = re.compile(r"\[parameters\('([^']+)'\)\]")

    def resolve_binding(value, bindings):
        if not isinstance(value, str) or not value.startswith("["):
            return value
        match = reference.fullmatch(value)
        return bindings.get(match[1]) if match else None

    def visit(node, bindings):
        if not isinstance(node, dict) or any(k in node for k in ("imports", "extensions")):
            raise RuntimeError("Unsupported compiled deployment template.")
        definitions = node.get("resources", [])
        if isinstance(definitions, dict):
            definitions = list(definitions.values())
        if not isinstance(definitions, list):
            raise RuntimeError("Invalid compiled resource definitions.")
        for resource in definitions:
            if not isinstance(resource, dict) or resource.get("resources"):
                raise RuntimeError("Nested resource declarations are prohibited.")
            kind = str(resource.get("type", "")).lower()
            if resource.get("existing") is True:
                # Bicep emits the naming module's RG lookup as ARM v2 existing,
                # not a deployment/write. Accept only this exact read reference.
                if (node.get("languageVersion") == "2.0"
                        and kind == "microsoft.resources/resourcegroups"
                        and set(resource) == {"existing", "type", "apiVersion", "subscriptionId", "name"}
                        and resource["subscriptionId"] == "[parameters('subscriptionIdDevTestProd')]"
                        and resource["name"] == "[parameters('commonResourceGroupName')]"
                        and shared.GUID.fullmatch(str(parameters.get("subscriptionIdDevTestProd", "")))
                        and shared.RG_NAME.fullmatch(str(parameters.get("commonResourceGroupName", "")))
                        and bindings.get("subscriptionIdDevTestProd") == parameters["subscriptionIdDevTestProd"]
                        and bindings.get("commonResourceGroupName") == parameters["commonResourceGroupName"]):
                    continue
                raise RuntimeError("Unsupported existing resource reference in dashboard template.")
            if kind not in ALLOWED_TYPES or any(k in resource for k in ("scope", "subscriptionId", "resourceGroup")):
                raise RuntimeError("Compiled template contains a non-dashboard resource or cross-scope write.")
            if kind == "microsoft.resources/deployments":
                props = resource.get("properties", {})
                if props.get("mode", "").lower() != "incremental" or "templateLink" in props or not isinstance(props.get("template"), dict):
                    raise RuntimeError("Only embedded Incremental dashboard modules are permitted.")
                module_bindings = {
                    name: definition.get("defaultValue")
                    for name, definition in props["template"].get("parameters", {}).items()
                }
                module_bindings.update({
                    name: resolve_binding(definition.get("value"), bindings) if isinstance(definition, dict) else None
                    for name, definition in props.get("parameters", {}).items()
                })
                visit(props["template"], module_bindings)
            else:
                counts[kind] += 1

    visit(template, parameters)
    if counts != {"microsoft.portal/dashboards": 1, "microsoft.insights/workbooks": 1}:
        raise RuntimeError("Expected exactly one project dashboard and one My Project workbook.")
    declared = template.get("parameters", {})
    if set(parameters) - declared.keys():
        raise RuntimeError("Dashboard parameter allowlist and compiled template are incompatible.")
    if any(name not in parameters and "defaultValue" not in item for name, item in declared.items()):
        raise RuntimeError("A required dashboard parameter is missing.")


def reconcile(azure: DashboardAzure):
    azure.previous_inventory = {}
    inventory, tenant, etag = shared.reconcile(azure.config, azure)
    # RG list can be permission-filtered without an error. A dashboard-only
    # refresh never treats absence from that result as proof of project deletion.
    previous = shared.previous_environments(azure.previous_inventory)
    for environment in inventory["environments"]:
        by_name = {p["name"].lower(): p for p in environment["projects"]}
        for project in previous.get(environment["name"], {}).get("projects", []):
            by_name.setdefault(project["name"].lower(), project)
        if environment["name"] == azure.config.current_environment:
            cfg = azure.config
            key = cfg.current_project_resource_group.lower()
            # RG-scoped readers may not be allowed to enumerate the subscription.
            by_name[key] = shared.project_record(
                cfg, cfg.current_environment, cfg.current_subscription,
                {"name": cfg.current_project_resource_group}, by_name.get(key), azure,
            )
        for project in previous.get(environment["name"], {}).get("projects", []):
            current = by_name[project["name"].lower()]
            shortcuts = {s["id"].lower(): s for s in current.get("shortcuts", [])}
            for shortcut in project.get("shortcuts", []):
                shortcuts.setdefault(shortcut["id"].lower(), shortcut)
            current["shortcuts"] = list(shortcuts.values())
        environment["projects"] = sorted(by_name.values(), key=lambda p: p["name"].lower())
        subscription = azure.config.subscriptions.get(environment["name"])
        if subscription:
            common = environment["commonResourceGroup"]
            result = azure(
                "group", "show", "--subscription", subscription, "--name", common["name"],
                "--output", "json", "--only-show-errors",
            )
            common["deploymentStatus"] = (
                "deployed" if not result.returncode else
                "not-deployed" if shared.error_code(result) in {"ResourceGroupNotFound", "ResourceNotFound"} else
                "unverified"
            )
    return inventory, tenant, etag


def factory_resource(cfg, inventory: dict, tenant: str) -> dict:
    body = shared.dashboard_resource(cfg, inventory, tenant)
    parts = body["properties"]["lenses"][0]["parts"]
    for index, environment in enumerate(inventory["environments"]):
        if environment["commonResourceGroup"].get("deploymentStatus") != "not-deployed":
            continue
        # Retain ARM IDs and project history in inventory; replace only the two
        # broken common RG/cost tiles, not the valid project tiles below them.
        x = index * 10
        parts[:] = [part for part in parts if not (
            part["position"]["y"] == 7 and part["position"]["x"] in {x, x + 4}
        )]
        parts.append(shared.markdown_part(
            x, 7, 10, 4,
            f"## {environment['displayName']} common resources not deployed\n\n"
            "The configured common resource group does not exist. "
            "Dashboard-only refresh does not create it. Existing project history is preserved below.",
        ))
    return body


def deployment_command(cfg, template: Path, parameters: Path) -> tuple[str, ...]:
    return (
        "deployment", "group", "create",
        "--name", f"dashboard-only-prj{cfg.current_project_number}-{cfg.current_environment}",
        "--subscription", cfg.current_subscription,
        "--resource-group", cfg.current_project_resource_group,
        "--mode", "Incremental", "--template-file", str(template),
        "--parameters", f"@{parameters}", "--output", "none", "--only-show-errors",
    )


def run(args, az=None) -> dict:
    consumer, values, cfg, tenant, factory_id, scale_set_id = load_configuration(args)
    if args.ci_output:
        if args.mode != "plan":
            raise ValueError("CI routing resolution must use plan mode.")
        settings = runner_settings(values, args.ci_output, args.runner_selection)
        emit_ci_output(settings, args.ci_output)
        return settings
    azure = DashboardAzure(cfg, args.mode, az)
    verify_accounts(azure, tenant)
    for subscription, group in dict.fromkeys((
        (cfg.current_subscription, cfg.current_project_resource_group),
        (cfg.current_subscription, cfg.common_resource_group(cfg.current_environment)),
        (cfg.host_subscription, cfg.dashboard_resource_group),
    )):
        require_group(azure, subscription, group)
    discovered = resources(azure, cfg.current_project_resource_group)
    insight, workspace = telemetry(azure, values, discovered)
    parameters = project_parameters(values, cfg, discovered, insight, workspace, factory_id, scale_set_id)
    template = json_response(azure(*compile_command()), "Compiling dashboard-only Bicep (preinstall Bicep on the agent)")
    validate_template(template, parameters)
    inventory, dashboard_tenant, etag = reconcile(azure)
    if dashboard_tenant.lower() != tenant.lower():
        raise RuntimeError("Factory dashboard tenant mismatch.")
    summary = {
        "mode": args.mode,
        "environment": cfg.current_environment,
        "project": cfg.current_project_number,
        "tenantId": tenant,
        "subscription": cfg.current_subscription,
        "projectResourceGroup": cfg.current_project_resource_group,
        "factoryDashboardId": cfg.dashboard_id,
        "applicationInsightsId": insight,
        "workspaceId": workspace,
        "existingResourceGroupsVerified": True,
        "deploymentMode": "Incremental",
        "preserveExistingFactoryTiles": True,
        "azureWritesPerformed": args.mode == "deploy",
        "commonResourceGroupStatus": {
            environment["name"]: environment["commonResourceGroup"].get("deploymentStatus", "unverified")
            for environment in inventory["environments"]
        },
        "writes": ["Microsoft.Portal/dashboards (factory + project)", "Microsoft.Insights/workbooks (My Project)",
                   "Microsoft.Resources/deployments (Incremental deployment records)"],
        "coverage": "all false",
    }
    if args.mode == "plan":
        print(json.dumps(summary, indent=2))
        print("PLAN ONLY: no Azure writes. Deploy refreshes both dashboards and the workbook; no infrastructure or roles.")
        return summary
    # Artifacts live only in an invocation-owned directory inside the checkout;
    # neither configuration nor Azure CLI output is uploaded or printed.
    work = consumer / f".dashboard-only-{uuid4().hex}"
    work.mkdir()
    try:
        template_path = work / "project.json"
        parameter_path = work / "parameters.json"
        template_path.write_text(json.dumps(template), encoding="utf-8")
        parameter_path.write_text(json.dumps({
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {key: {"value": value} for key, value in parameters.items()},
        }), encoding="utf-8")
        azure.deployment_command = deployment_command(cfg, template_path, parameter_path)
        result = azure(*azure.deployment_command)
        if result.returncode:
            raise RuntimeError("Project dashboard/workbook deployment failed. No factory update attempted; review scoped deployment permissions and deployment history.")
        for attempt in range(3):
            # Refresh after the project deployment so the snapshot/ETag is current.
            inventory, dashboard_tenant, etag = reconcile(azure)
            if dashboard_tenant.lower() != tenant.lower():
                raise RuntimeError("Factory dashboard tenant mismatch.")
            body = work / "factory.json"
            body.write_text(json.dumps(factory_resource(cfg, inventory, tenant)), encoding="utf-8")
            result = azure(
                *factory_command(azure, "put"), "--headers",
                f"If-Match={etag}" if etag is not None else "If-None-Match=*",
                "Content-Type=application/json", "--body", f"@{body}",
            )
            if not result.returncode:
                break
            if shared.error_code(result) not in {"PreconditionFailed", "ConditionNotMet"} or attempt == 2:
                raise RuntimeError("Factory dashboard conditional update failed; project dashboard/workbook already refreshed. Rerun to reconcile safely.")
    finally:
        shutil.rmtree(work)
    print(json.dumps(summary, indent=2))
    print("Refreshed factory dashboard, project dashboard and My Project workbook only.")
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variables-json", default="aifactory/variables.json")
    parser.add_argument("--environment", required=True, choices=("dev", "test", "stage", "prod"))
    parser.add_argument("--project", required=True, help="Required three-digit assertion, e.g. 001; must match project_number_000.")
    parser.add_argument("--consumer-root", default=str(Path.cwd()))
    parser.add_argument("--repo-root", default="azure-enterprise-scale-ml")
    parser.add_argument("--mode", choices=("plan", "deploy"), default="plan")
    parser.add_argument("--factory-id", default="", help="Exact opaque telemetry factory ID; never inferred from RG/path.")
    parser.add_argument("--scale-set-id", default="", help="Exact opaque telemetry scale set ID; never inferred from RG/path.")
    parser.add_argument("--service-connection", default="", help="ADO connection assertion; must match the selected JSON section.")
    parser.add_argument("--ci-output", choices=("ado", "github"), help="Resolve CI runner routing offline; never authenticate or deploy.")
    parser.add_argument("--runner-selection", default="from-config")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    try:
        run(parse_args(argv))
        return 0
    except (ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
