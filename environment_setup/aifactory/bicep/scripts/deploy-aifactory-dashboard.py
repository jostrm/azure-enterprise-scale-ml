#!/usr/bin/env python3
"""Reconcile and deploy the shared AI Factory Azure Portal dashboard."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
PROJECT_NUMBER = re.compile(r"\d{3}")
RG_NAME = re.compile(r"[\w().-]{1,90}")
UNEXPANDED = re.compile(r"^\$\([A-Za-z_][\w.-]*\)$")
Az = Callable[..., subprocess.CompletedProcess[str]]
ENVIRONMENTS = (
    ("dev", "DEV", "DASHBOARD_DEV_SUBSCRIPTION_ID"),
    ("test", "STAGE", "DASHBOARD_STAGE_SUBSCRIPTION_ID"),
    ("prod", "PROD", "DASHBOARD_PROD_SUBSCRIPTION_ID"),
)
API_VERSION = "2020-09-01-preview"


class ConcurrentUpdate(RuntimeError):
    """The dashboard changed after it was read."""


def env_value(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if UNEXPANDED.fullmatch(value) or value.lower() == "unset":
        return default
    return value or default


def az_cli(*args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required for dashboard reconciliation; 'az' was not found on PATH.")
    command = [executable]
    if sys.platform == "win32" and Path(executable).suffix.lower() in (".cmd", ".bat"):
        # Use the CLI's own runtime, as in cleanup-project-orphan-roles.py, not cmd.exe:
        # dashboard URLs, ETags, and JSON-file arguments must stay literal.
        cli_python = Path(executable).parent.parent / "python.exe"
        if not cli_python.is_file():
            raise RuntimeError(f"Cannot locate the Windows Azure CLI Python runtime: {cli_python}")
        command = [str(cli_python), "-X", "utf8", "-IBm", "azure.cli"]
    try:
        return subprocess.run(
            [*command, *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        raise RuntimeError(f"Unable to launch Azure CLI for dashboard reconciliation: {error}") from error


def error_code(result: subprocess.CompletedProcess[str]) -> str | None:
    text = f"{result.stderr}\n{result.stdout}"
    for offset, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = json.JSONDecoder().raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str):
            return code
    return None


def json_result(result: subprocess.CompletedProcess[str], purpose: str) -> object | None:
    if result.returncode:
        print(f"WARNING: {purpose} failed: {result.stderr.strip() or result.stdout.strip()}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"WARNING: {purpose} returned invalid JSON.")
        return None


def arm_id(subscription: str, resource_group: str) -> str:
    return f"/subscriptions/{subscription}/resourceGroups/{resource_group}"


def configuration_payload() -> dict:
    path_value = env_value("DASHBOARD_CONFIG_FILE")
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"WARNING: Unable to read dashboard subscription fallbacks from {path}: {error}")
        return {}
    return payload if isinstance(payload, dict) else {}


@dataclass(frozen=True)
class Config:
    current_subscription: str
    current_environment: str
    current_project_number: str
    location: str
    location_suffix: str
    resource_group_prefix: str
    resource_group_suffix: str
    project_prefix: str
    project_suffix: str
    common_name: str
    common_overrides: dict[str, str]
    subscriptions: dict[str, str]
    central_dns: bool
    private_dns_subscription: str
    private_dns_resource_group: str
    vnet_subscription: str
    vnet_resource_group: str
    template_file: Path

    @classmethod
    def from_env(cls) -> Config:
        current_subscription = env_value("DASHBOARD_CURRENT_SUBSCRIPTION_ID")
        current_environment = env_value("DASHBOARD_CURRENT_ENV").lower()
        current_project_number = env_value("DASHBOARD_PROJECT_NUMBER")
        location = env_value("DASHBOARD_LOCATION")
        location_suffix = env_value("DASHBOARD_LOCATION_SUFFIX")
        if not GUID.fullmatch(current_subscription):
            raise ValueError("DASHBOARD_CURRENT_SUBSCRIPTION_ID must be an Azure subscription GUID.")
        if current_environment not in {"dev", "test", "prod"}:
            raise ValueError("DASHBOARD_CURRENT_ENV must be dev, test, or prod.")
        if not PROJECT_NUMBER.fullmatch(current_project_number):
            raise ValueError("DASHBOARD_PROJECT_NUMBER must contain exactly three digits.")
        if not location or not location_suffix:
            raise ValueError("Dashboard location and location suffix are required.")

        configuration = configuration_payload()
        dev_configuration = configuration.get("dev")
        stage_configuration = configuration.get("stage_prod")
        dev_configuration = dev_configuration if isinstance(dev_configuration, dict) else {}
        stage_configuration = (
            stage_configuration if isinstance(stage_configuration, dict) else {}
        )
        subscription_keys = {
            "dev": "dev_sub_id",
            "test": "test_sub_id",
            "prod": "prod_sub_id",
        }
        subscriptions = {
            environment: env_value(
                variable, str(dev_configuration.get(subscription_keys[environment], ""))
            )
            for environment, _, variable in ENVIRONMENTS
        }
        subscriptions[current_environment] = (
            subscriptions[current_environment] or current_subscription
        )
        subscriptions = {
            environment: value if GUID.fullmatch(value) else ""
            for environment, value in subscriptions.items()
        }

        template_default = (
            Path(__file__).resolve().parents[1] / "modules" / "aifactory-dash-01.bicep"
        )
        template_file = Path(env_value("DASHBOARD_TEMPLATE_FILE", str(template_default)))
        if not template_file.is_file():
            raise ValueError(f"Dashboard Bicep template does not exist: {template_file}")

        current_common_override = env_value("DASHBOARD_COMMON_RG")
        if configuration:
            common_overrides = {
                "dev": str(dev_configuration.get("commonResourceGroup_param", "")).strip(),
                "test": str(stage_configuration.get("commonResourceGroup_param", "")).strip(),
                "prod": str(stage_configuration.get("commonResourceGroup_param", "")).strip(),
            }
            common_overrides[current_environment] = (
                current_common_override or common_overrides[current_environment]
            )
        else:
            common_overrides = {environment: "" for environment, _, _ in ENVIRONMENTS}
            common_overrides[current_environment] = current_common_override

        config = cls(
            current_subscription=current_subscription,
            current_environment=current_environment,
            current_project_number=current_project_number,
            location=location,
            location_suffix=location_suffix,
            resource_group_prefix=env_value("DASHBOARD_RG_PREFIX"),
            resource_group_suffix=env_value("DASHBOARD_RG_SUFFIX"),
            project_prefix=env_value("DASHBOARD_PROJECT_PREFIX", "esml-"),
            project_suffix=env_value("DASHBOARD_PROJECT_SUFFIX", "-rg"),
            common_name=env_value("DASHBOARD_COMMON_NAME", "esml-common"),
            common_overrides=common_overrides,
            subscriptions=subscriptions,
            central_dns=env_value("DASHBOARD_CENTRAL_DNS", "false").lower() == "true",
            private_dns_subscription=env_value("DASHBOARD_PRIVATE_DNS_SUBSCRIPTION_ID"),
            private_dns_resource_group=env_value("DASHBOARD_PRIVATE_DNS_RESOURCE_GROUP"),
            vnet_subscription=env_value(
                "DASHBOARD_VNET_SUBSCRIPTION_ID", current_subscription
            ),
            vnet_resource_group=env_value("DASHBOARD_VNET_RESOURCE_GROUP"),
            template_file=template_file,
        )
        for name in (
            config.dashboard_resource_group,
            config.current_project_resource_group,
            *(config.common_resource_group(environment) for environment, _, _ in ENVIRONMENTS),
        ):
            if not RG_NAME.fullmatch(name) or name.endswith("."):
                raise ValueError(f"Invalid dashboard resource-group name: {name!r}")
        return config

    def common_resource_group(self, environment: str) -> str:
        common_override = self.common_overrides.get(environment, "")
        if common_override:
            return (
                common_override.replace("<env>", environment)
                .replace("<network_env>", environment)
            )
        return (
            f"{self.resource_group_prefix}{self.common_name}-"
            f"{self.location_suffix}-{environment}{self.resource_group_suffix}"
        )

    @property
    def host_subscription(self) -> str:
        return self.subscriptions["dev"] or self.current_subscription

    @property
    def dashboard_resource_group(self) -> str:
        return self.common_resource_group("dev")

    @property
    def dashboard_name(self) -> str:
        prefix = re.sub(r"[^a-zA-Z0-9-]", "-", self.resource_group_prefix).strip("-")
        region = re.sub(r"[^a-zA-Z0-9-]", "-", self.location_suffix).strip("-")
        suffix = re.sub(r"[^a-zA-Z0-9-]", "-", self.resource_group_suffix).strip("-")
        components = [component for component in (prefix, region, suffix) if component]
        return f"AIFactory-{'-'.join(components)}-dash-01"

    @property
    def dashboard_id(self) -> str:
        return (
            f"{arm_id(self.host_subscription, self.dashboard_resource_group)}"
            f"/providers/Microsoft.Portal/dashboards/{self.dashboard_name}"
        )

    @property
    def current_project_resource_group(self) -> str:
        return (
            f"{self.resource_group_prefix}{self.project_prefix}"
            f"project{self.current_project_number}-{self.location_suffix}-"
            f"{self.current_environment}{self.resource_group_suffix}{self.project_suffix}"
        )

    def project_pattern(self, environment: str) -> re.Pattern[str]:
        prefix = (
            f"{self.resource_group_prefix}{self.project_prefix}project"
        )
        suffix = (
            f"-{self.location_suffix}-{environment}"
            f"{self.resource_group_suffix}{self.project_suffix}"
        )
        return re.compile(
            rf"^{re.escape(prefix)}(?P<number>\d{{3}}){re.escape(suffix)}$",
            re.I,
        )


def ensure_dashboard_resource_group(config: Config, az: Az) -> None:
    result = az(
        "group",
        "exists",
        "--subscription",
        config.host_subscription,
        "--name",
        config.dashboard_resource_group,
        "--output",
        "json",
        "--only-show-errors",
    )
    exists = json_result(result, "Checking the dashboard resource group")
    if exists is True:
        return
    if exists is False:
        raise RuntimeError(
            "The DEV common resource group that hosts the shared dashboard does not "
            f"exist: {config.dashboard_resource_group} ({config.host_subscription})."
        )
    raise RuntimeError(
        "Unable to determine whether the DEV common dashboard resource group exists."
    )


def existing_inventory(config: Config, az: Az) -> tuple[dict, str | None]:
    result = az(
        "rest",
        "--subscription",
        config.host_subscription,
        "--method",
        "get",
        "--url",
        f"https://management.azure.com{config.dashboard_id}?api-version={API_VERSION}",
        "--only-show-errors",
    )
    if result.returncode:
        if error_code(result) in {"ResourceNotFound", "ResourceGroupNotFound"}:
            return {}, None
        raise RuntimeError(
            "Unable to read the existing AI Factory dashboard: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    payload = json_result(result, "Reading the existing AI Factory dashboard")
    if not isinstance(payload, dict):
        raise RuntimeError("The existing AI Factory dashboard response is invalid.")
    properties = payload.get("properties")
    metadata = properties.get("metadata") if isinstance(properties, dict) else None
    inventory = metadata.get("aifactoryInventory") if isinstance(metadata, dict) else None
    tags = payload.get("tags")
    owned = (
        isinstance(tags, dict)
        and str(tags.get("AI-Factory-Dashboard", "")).lower() == "true"
    )
    if inventory is None:
        if not owned:
            raise RuntimeError(
                f"Dashboard {config.dashboard_id} already exists but is not managed by AI Factory. "
                "Refusing to overwrite it."
            )
        print(
            "WARNING: The managed dashboard has no persisted inventory; "
            "rebuilding it from Azure discovery."
        )
        inventory = {}
    if not isinstance(inventory, dict) or inventory.get("schemaVersion") != 1:
        if inventory:
            raise RuntimeError("The existing AI Factory dashboard inventory is invalid.")
    etag = payload.get("etag")
    if not isinstance(etag, str) or not etag:
        raise RuntimeError("The existing AI Factory dashboard did not return an ETag.")
    return inventory, etag


def resource_shortcuts(
    subscription: str,
    resource_group: str,
    previous: list[dict],
    az: Az,
) -> list[dict]:
    result = az(
        "resource",
        "list",
        "--subscription",
        subscription,
        "--resource-group",
        resource_group,
        "--query",
        "[].{id:id,name:name,type:type,kind:kind}",
        "--output",
        "json",
        "--only-show-errors",
    )
    resources = json_result(result, f"Discovering shortcuts in {resource_group}")
    if not isinstance(resources, list):
        return previous

    wanted = (
        ("AI Foundry", "microsoft.cognitiveservices/accounts"),
        ("Storage", "microsoft.storage/storageaccounts"),
        ("Key Vault", "microsoft.keyvault/vaults"),
        ("AI Search", "microsoft.search/searchservices"),
    )
    shortcuts: list[dict] = []
    for label, resource_type in wanted:
        matches = sorted(
            (
                resource
                for resource in resources
                if isinstance(resource, dict)
                and str(resource.get("type", "")).lower() == resource_type
                and isinstance(resource.get("id"), str)
            ),
            key=lambda item: (
                0
                if (
                    label == "AI Foundry"
                    and (
                        str(item.get("name", "")).lower().startswith("aif2")
                        or "foundry" in str(item.get("name", "")).lower()
                    )
                )
                or (
                    label == "Storage"
                    and "2001" in str(item.get("name", "")).lower()
                )
                else 1,
                str(item.get("name", "")).lower(),
            ),
        )
        if matches:
            shortcuts.append(
                {
                    "label": label,
                    "id": matches[0]["id"],
                    "type": matches[0]["type"],
                }
            )
    return shortcuts


def project_record(
    config: Config,
    environment: str,
    subscription: str,
    group: dict,
    previous: dict | None,
    az: Az,
) -> dict:
    name = str(group["name"])
    project_number = config.project_pattern(environment).fullmatch(name).group("number")
    project_id = str(group.get("id") or arm_id(subscription, name))
    dashboard_id = (
        f"{project_id}/providers/Microsoft.Portal/dashboards/"
        f"dash-prj{project_number}-{environment}-{config.location_suffix}"
    )
    tenant_result = az(
        "account",
        "show",
        "--subscription",
        subscription,
        "--query",
        "tenantId",
        "--output",
        "tsv",
        "--only-show-errors",
    )
    tenant_id = tenant_result.stdout.strip() if tenant_result.returncode == 0 else ""
    dashboard_url = (
        f"https://portal.azure.com/#@{tenant_id}/dashboard/arm{dashboard_id}"
        if tenant_id
        else f"https://portal.azure.com/#dashboard/arm{dashboard_id}"
    )
    previous_shortcuts = (
        previous.get("shortcuts", [])
        if isinstance(previous, dict) and isinstance(previous.get("shortcuts"), list)
        else []
    )
    return {
        "projectNumber": project_number,
        "name": name,
        "id": project_id,
        "dashboardUrl": dashboard_url,
        "shortcuts": resource_shortcuts(
            subscription, name, previous_shortcuts, az
        ),
    }


def previous_environments(inventory: dict) -> dict[str, dict]:
    environments = inventory.get("environments", [])
    if not isinstance(environments, list):
        return {}
    return {
        item["name"]: item
        for item in environments
        if isinstance(item, dict) and item.get("name") in {"dev", "test", "prod"}
    }


def discover_environment(
    config: Config,
    environment: str,
    display_name: str,
    subscription: str,
    previous: dict | None,
    az: Az,
) -> dict:
    common_name = config.common_resource_group(environment)
    base = {
        "name": environment,
        "displayName": display_name,
        "subscriptionId": subscription,
        "commonResourceGroup": {
            "name": common_name,
            "id": arm_id(subscription, common_name) if subscription else "",
        },
        "projects": [],
    }
    if not subscription:
        print(f"WARNING: No {display_name} subscription is configured; preserving its dashboard inventory.")
        return previous or base

    result = az(
        "group",
        "list",
        "--subscription",
        subscription,
        "--query",
        "[].{name:name,id:id}",
        "--output",
        "json",
        "--only-show-errors",
    )
    groups = json_result(result, f"Discovering {display_name} resource groups")
    if not isinstance(groups, list):
        return previous or base

    pattern = config.project_pattern(environment)
    previous_projects = {
        project.get("name"): project
        for project in (previous or {}).get("projects", [])
        if isinstance(project, dict) and isinstance(project.get("name"), str)
    }
    matched = sorted(
        (
            group
            for group in groups
            if isinstance(group, dict)
            and isinstance(group.get("name"), str)
            and pattern.fullmatch(group["name"])
        ),
        key=lambda group: pattern.fullmatch(group["name"]).group("number"),
    )
    projects = [
        project_record(
            config,
            environment,
            subscription,
            group,
            previous_projects.get(group["name"]),
            az,
        )
        for group in matched
    ]
    base["projects"] = projects
    print(f"{display_name}: discovered {len(projects)} AI Factory project resource group(s).")
    return base


def merge_hub_resource_groups(config: Config, inventory: dict) -> list[dict]:
    previous = inventory.get("hubResourceGroups", [])
    merged = {
        str(item.get("id", "")).lower(): item
        for item in previous
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("name"), str)
    } if isinstance(previous, list) else {}

    candidates: list[tuple[str, str]] = []
    if (
        config.central_dns
        and GUID.fullmatch(config.private_dns_subscription)
        and RG_NAME.fullmatch(config.private_dns_resource_group)
    ):
        candidates.append(
            (config.private_dns_subscription, config.private_dns_resource_group)
        )
    if GUID.fullmatch(config.vnet_subscription) and RG_NAME.fullmatch(
        config.vnet_resource_group
    ):
        candidates.append((config.vnet_subscription, config.vnet_resource_group))

    common_ids = {
        arm_id(subscription, config.common_resource_group(environment)).lower()
        for environment, subscription in config.subscriptions.items()
        if subscription
    }
    for subscription, resource_group in candidates:
        resource_id = arm_id(subscription, resource_group)
        if resource_id.lower() not in common_ids:
            merged[resource_id.lower()] = {
                "name": resource_group,
                "id": resource_id,
            }
    return sorted(merged.values(), key=lambda item: item["name"].lower())[:3]


def markdown_part(x: int, y: int, width: int, height: int, content: str) -> dict:
    return {
        "position": {"x": x, "y": y, "colSpan": width, "rowSpan": height},
        "metadata": {
            "inputs": [],
            "type": "Extension/HubsExtension/PartType/MarkdownPart",
            "settings": {
                "content": {
                    "settings": {
                        "content": content,
                        "title": "",
                        "subtitle": "",
                        "markdownSource": 1,
                        "markdownUri": None,
                    }
                }
            },
        },
    }


def resource_part(x: int, y: int, width: int, height: int, resource: dict) -> dict:
    return {
        "position": {"x": x, "y": y, "colSpan": width, "rowSpan": height},
        "metadata": {
            "inputs": [{"name": "id", "isOptional": False, "value": resource["id"]}],
            "type": "Extension/HubsExtension/PartType/ResourcePart",
            "asset": {
                "idInputName": "id",
                "type": resource.get("type", "ResourceGroup"),
            },
        },
    }


def cost_part(x: int, y: int, resource: dict, tenant_id: str) -> dict:
    resource_id = resource["id"]
    return {
        "position": {"x": x, "y": y, "colSpan": 6, "rowSpan": 4},
        "metadata": {
            "deepLink": f"#@{tenant_id}/resource{resource_id}/costanalysis",
            "inputs": [
                {"name": "scope", "value": resource_id},
                {"name": "scopeName", "value": resource["name"]},
                {
                    "name": "view",
                    "isOptional": True,
                    "value": {
                        "accumulated": "true",
                        "chart": "Area",
                        "currency": None,
                        "dateRange": "ThisMonth",
                        "displayName": "AccumulatedCosts",
                        "kpis": [
                            {
                                "enabled": True,
                                "extendedProperties": {
                                    "name": "COST_NAVIGATOR.BUDGET_OPTIONS.NONE"
                                },
                                "id": "COST_NAVIGATOR.BUDGET_OPTIONS.NONE",
                                "type": "Budget",
                            },
                            {"enabled": True, "type": "Forecast"},
                        ],
                        "pivots": [
                            {"name": "ServiceName", "type": "Dimension"},
                            {"name": "ResourceLocation", "type": "Dimension"},
                            {"name": "ResourceId", "type": "Dimension"},
                        ],
                        "query": {
                            "dataSet": {
                                "aggregation": {
                                    "totalCost": {
                                        "function": "Sum",
                                        "name": "Cost",
                                    },
                                    "totalCostUSD": {
                                        "function": "Sum",
                                        "name": "CostUSD",
                                    },
                                },
                                "granularity": "Daily",
                                "sorting": [
                                    {
                                        "direction": "ascending",
                                        "name": "UsageDate",
                                    }
                                ],
                            },
                            "timeframe": "None",
                            "type": "ActualCost",
                        },
                        "scope": resource_id.removeprefix("/"),
                    },
                },
                {"name": "externalState", "isOptional": True},
            ],
            "type": "Extension/Microsoft_Azure_CostManagement/PartType/CostAnalysisPinPart",
        },
    }


def dashboard_parts(inventory: dict, tenant_id: str) -> list[dict]:
    parts = [
        markdown_part(
            0,
            0,
            30,
            2,
            "# AI Factory\n\nCross-environment landing zone inventory. "
            "Hub and shared services are shown first, followed by DEV, STAGE, and PROD. "
            "Project pipelines reconcile this dashboard after every deployment.",
        )
    ]
    hubs = inventory["hubResourceGroups"]
    if hubs:
        for index, hub in enumerate(hubs[:3]):
            x = index * 10
            parts.extend((resource_part(x, 2, 4, 4, hub), cost_part(x + 4, 2, hub, tenant_id)))
    else:
        parts.append(
            markdown_part(
                0,
                2,
                30,
                4,
                "## Hub / Shared Services\n\nNo separate hub resource group is configured. "
                "Environment common resource groups are shown below.",
            )
        )

    for environment_index, environment in enumerate(inventory["environments"]):
        x = environment_index * 10
        parts.append(
            markdown_part(x, 6, 10, 1, f"# {environment['displayName']}")
        )
        common = environment["commonResourceGroup"]
        if not common.get("id"):
            parts.append(
                markdown_part(
                    x,
                    7,
                    10,
                    4,
                    f"## {environment['displayName']} is not configured\n\n"
                    "Set the environment subscription ID and rerun a project pipeline.",
                )
            )
            continue
        parts.extend(
            (
                resource_part(x, 7, 4, 4, common),
                cost_part(x + 4, 7, common, tenant_id),
            )
        )
        for project_index, project in enumerate(environment["projects"]):
            y = 11 + project_index * 7
            parts.append(
                markdown_part(
                    x,
                    y,
                    10,
                    1,
                    f"## Project {project['projectNumber']}\n\n"
                    f"[Open project dashboard]({project['dashboardUrl']})",
                )
            )
            parts.extend(
                (
                    resource_part(x, y + 1, 4, 4, project),
                    cost_part(x + 4, y + 1, project, tenant_id),
                )
            )
            for shortcut_index, shortcut in enumerate(project["shortcuts"][:4]):
                parts.append(
                    resource_part(x + shortcut_index, y + 5, 1, 1, shortcut)
                )
    return parts


def reconcile(config: Config, az: Az = az_cli) -> tuple[dict, str, str | None]:
    ensure_dashboard_resource_group(config, az)
    inventory, etag = existing_inventory(config, az)
    previous = previous_environments(inventory)
    environments = [
        discover_environment(
            config,
            environment,
            display_name,
            config.subscriptions[environment],
            previous.get(environment),
            az,
        )
        for environment, display_name, _ in ENVIRONMENTS
    ]
    reconciled = {
        "schemaVersion": 1,
        "hubResourceGroups": merge_hub_resource_groups(config, inventory),
        "environments": environments,
    }

    tenant_result = az(
        "account",
        "show",
        "--subscription",
        config.host_subscription,
        "--query",
        "tenantId",
        "--output",
        "tsv",
        "--only-show-errors",
    )
    if tenant_result.returncode or not GUID.fullmatch(tenant_result.stdout.strip()):
        raise RuntimeError("Unable to resolve the dashboard host tenant.")
    return reconciled, tenant_result.stdout.strip(), etag


def dashboard_resource(config: Config, inventory: dict, tenant_id: str) -> dict:
    return {
        "location": config.location,
        "tags": {
            "hidden-title": config.dashboard_name,
            "AI-Factory-Dashboard": "true",
            "AI-Factory": "true",
            "AI-Factory-Location": config.location_suffix,
        },
        "properties": {
            "lenses": [
                {
                    "order": 0,
                    "parts": dashboard_parts(inventory, tenant_id),
                }
            ],
            "metadata": {
                "aifactoryInventory": inventory,
                "model": {
                    "timeRange": {
                        "value": {
                            "relative": {
                                "duration": 30,
                                "timeUnit": 2,
                            }
                        },
                        "type": (
                            "MsPortalFx.Composition.Configuration.ValueTypes.TimeRange"
                        ),
                    },
                    "filterLocale": {"value": "en-us"},
                    "filters": {
                        "value": {
                            "MsPortalFx_TimeRange": {
                                "model": {
                                    "format": "utc",
                                    "granularity": "auto",
                                    "relative": "30d",
                                },
                                "displayCache": {
                                    "name": "UTC Time",
                                    "value": "Past 30 days",
                                },
                                "filteredPartIds": [],
                            }
                        }
                    },
                },
            },
        },
    }


def deploy(
    config: Config,
    inventory: dict,
    tenant_id: str,
    etag: str | None,
    az: Az = az_cli,
) -> str:
    portal_url = (
        f"https://portal.azure.com/#@{tenant_id}/dashboard/arm{config.dashboard_id}"
    )
    if etag is not None:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as handle:
            json.dump(dashboard_resource(config, inventory, tenant_id), handle, indent=2)
            body_file = Path(handle.name)
        try:
            result = az(
                "rest",
                "--subscription",
                config.host_subscription,
                "--method",
                "put",
                "--url",
                f"https://management.azure.com{config.dashboard_id}?api-version={API_VERSION}",
                "--headers",
                f"If-Match={etag}",
                "Content-Type=application/json",
                "--body",
                f"@{body_file}",
                "--only-show-errors",
            )
        finally:
            body_file.unlink(missing_ok=True)
        if result.returncode:
            if error_code(result) in {"PreconditionFailed", "ConditionNotMet"}:
                raise ConcurrentUpdate("The AI Factory dashboard changed concurrently.")
            raise RuntimeError(
                "AI Factory dashboard update failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return portal_url

    parameters = {
        "$schema": (
            "https://schema.management.azure.com/schemas/2019-04-01/"
            "deploymentParameters.json#"
        ),
        "contentVersion": "1.0.0.0",
        "parameters": {
            "location": {"value": config.location},
            "dashboardName": {"value": config.dashboard_name},
            "dashboardTitle": {"value": config.dashboard_name},
            "dashboardParts": {"value": dashboard_parts(inventory, tenant_id)},
            "aifactoryInventory": {"value": inventory},
            "tags": {
                "value": {
                    "AI-Factory": "true",
                    "AI-Factory-Location": config.location_suffix,
                }
            },
        },
    }
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(parameters, handle, indent=2)
        parameter_file = Path(handle.name)
    try:
        result = az(
            "deployment",
            "group",
            "create",
            "--name",
            f"aifactory-dashboard-{config.location_suffix}",
            "--subscription",
            config.host_subscription,
            "--resource-group",
            config.dashboard_resource_group,
            "--template-file",
            str(config.template_file),
            "--parameters",
            f"@{parameter_file}",
            "--query",
            "properties.outputs.dashboardUrl.value",
            "--output",
            "tsv",
            "--only-show-errors",
        )
    finally:
        parameter_file.unlink(missing_ok=True)
    if result.returncode:
        raise RuntimeError(
            f"AI Factory dashboard deployment failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout.strip() or portal_url


def main() -> int:
    try:
        config = Config.from_env()
        for attempt in range(1, 4):
            inventory, tenant_id, etag = reconcile(config)
            try:
                dashboard_url = deploy(config, inventory, tenant_id, etag)
                break
            except ConcurrentUpdate:
                if attempt == 3:
                    raise RuntimeError(
                        "The dashboard changed concurrently during all three update attempts."
                    )
                print(
                    f"WARNING: Dashboard changed concurrently; retrying "
                    f"reconciliation ({attempt}/3)."
                )
    except (ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    project_count = sum(
        len(environment["projects"]) for environment in inventory["environments"]
    )
    print(f"AI Factory dashboard reconciled with {project_count} project(s).")
    print(f"Dashboard: {dashboard_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
