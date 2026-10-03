"""Resolve AI Factory scope (tenant, subscription, resource groups) and health model names.

Resource group naming mirrors ``deploy-aifactory-dashboard.Config`` in the
accelerator; ``tests/test_naming.py`` guards that parity.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import MODEL_NAME_PATTERN

GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
PROJECT_NUMBER = re.compile(r"\d{3}")
RG_NAME = re.compile(r"[\w().-]{1,90}")
LOCATION = re.compile(r"[a-z0-9]+")
MODEL_NAME_MAX = 44

# Regions where Microsoft.CloudHealth/healthmodels can be created (provider
# metadata, 2026-10-03). The live provider list is preferred when readable.
SUPPORTED_REGIONS = frozenset({
    "australiaeast", "canadacentral", "centralus", "eastasia", "germanywestcentral", "italynorth",
    "japanwest", "northeurope", "southeastasia", "swedencentral", "switzerlandnorth", "uksouth",
    "westeurope", "westus3",
})
# Only same-geography fallbacks are automatic; anything else needs an explicit choice.
REGION_FALLBACK = {
    "eastus": "centralus", "eastus2": "centralus", "southcentralus": "centralus",
    "northcentralus": "centralus", "westcentralus": "westus3", "westus": "westus3", "westus2": "westus3",
    "canadaeast": "canadacentral",
    "denmarkeast": "swedencentral", "swedensouth": "swedencentral", "norwayeast": "swedencentral",
    "norwaywest": "swedencentral", "finlandcentral": "swedencentral",
    "francecentral": "westeurope", "francesouth": "westeurope", "belgiumcentral": "westeurope",
    "spaincentral": "westeurope", "polandcentral": "germanywestcentral",
    "germanynorth": "germanywestcentral", "austriaeast": "germanywestcentral",
    "ukwest": "uksouth", "switzerlandwest": "switzerlandnorth", "japaneast": "japanwest",
    "australiasoutheast": "australiaeast", "australiacentral": "australiaeast",
    "australiacentral2": "australiaeast",
}
ENVIRONMENTS = {"dev": "dev", "test": "test", "stage": "test", "prod": "prod"}
SUBSCRIPTION_KEYS = {"dev": "dev_sub_id", "test": "test_sub_id", "prod": "prod_sub_id"}


@dataclass(frozen=True)
class FactoryScope:
    tenant_id: str
    subscription_id: str
    environment: str
    project_number: str
    location: str
    location_suffix: str
    project_resource_group: str
    common_resource_group: str
    resource_group_prefix: str = ""
    resource_group_suffix: str = ""
    flags: dict = field(default_factory=dict)

    def model_name(self, scope: str) -> str:
        """Deterministic, valid health model name for the project or common model."""
        if scope == "project":
            token = f"prj{self.project_number}"
        elif scope == "common":
            token = "cmn"
        else:
            raise ValueError("Model scope must be 'project' or 'common'.")
        head = _sanitize(f"hm-{self.resource_group_prefix}")
        tail = _sanitize(f"{token}-{self.location_suffix}-{self.environment}{self.resource_group_suffix}")[:30].strip("-")
        name = f"{head}-{tail}" if head else tail
        if len(name) > MODEL_NAME_MAX:
            digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
            head = head[: MODEL_NAME_MAX - len(tail) - len(digest) - 2].rstrip("-")
            name = f"{head}-{digest}-{tail}"
        if not MODEL_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"Cannot derive a valid health model name from the configuration: {name!r}")
        return name

    @property
    def resource_groups(self) -> tuple[str, str]:
        return self.project_resource_group, self.common_resource_group


def _sanitize(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower())
    return re.sub(r"-{2,}", "-", value).strip("-")


def _text(values: dict, key: str, *, required: bool = True, default: str = "") -> str:
    value = values.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string.")
    if required and not value:
        raise ValueError(f"{key} is required in the selected configuration.")
    if len(value) > 2048 or any(ord(c) < 32 for c in value) or "$(" in value:
        raise ValueError(f"{key} contains unresolved variables or control characters.")
    return value


def _guid(value: object, key: str) -> str:
    if not isinstance(value, str) or not GUID.fullmatch(value):
        raise ValueError(f"{key} must be an Azure GUID (placeholders such as <todo> are not accepted).")
    return value.lower()


def _flags(values: dict) -> dict[str, bool]:
    flags = {}
    for key, value in values.items():
        if not (key.startswith("enable") or key.startswith("ENABLE_")):
            continue
        if isinstance(value, bool):
            flags[key] = value
        elif isinstance(value, str) and value.lower() in {"true", "false"}:
            flags[key] = value.lower() == "true"
    return flags


def read_variables(path: str | Path) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ValueError("Cannot read the AI Factory configuration as JSON.") from None
    if not isinstance(document, dict) or not isinstance(document.get("dev"), dict):
        raise ValueError("variables.json must be an object with a dev section.")
    return document


def from_variables(payload: dict, environment: str, project: str) -> FactoryScope:
    """Resolve scope from a persistent AI Factory variables.json (dev + stage_prod overlay)."""
    if environment not in ENVIRONMENTS:
        raise ValueError("Select an environment: dev, stage (test) or prod.")
    env = ENVIRONMENTS[environment]
    if not isinstance(payload, dict) or not isinstance(payload.get("dev"), dict):
        raise ValueError("variables.json must contain a dev section.")
    stage = payload.get("stage_prod") or {}
    if not isinstance(stage, dict):
        raise ValueError("stage_prod must be an object.")
    section = payload["dev"] if env == "dev" else stage
    values = {**payload["dev"], **(stage if env != "dev" else {})}
    number = str(values.get("project_number_000", "")).zfill(3) if values.get("project_number_000") else ""
    if not PROJECT_NUMBER.fullmatch(number) or number == "000":
        raise ValueError("project_number_000 must be a three-digit project number.")
    if not PROJECT_NUMBER.fullmatch(project or "") or project != number:
        raise ValueError("The --project assertion must equal project_number_000 in the selected configuration.")
    tenant = _guid(section.get("tenantId", values.get("tenantId")), "tenantId")
    subscription = _guid(section.get(SUBSCRIPTION_KEYS[env]), SUBSCRIPTION_KEYS[env])
    location = _text(values, "admin_location")
    suffix = _text(values, "admin_locationSuffix")
    if not LOCATION.fullmatch(location) or not LOCATION.fullmatch(suffix):
        raise ValueError("admin_location and admin_locationSuffix must be lowercase alphanumeric.")
    prefix = _text(values, "admin_aifactoryPrefixRG", required=False)
    rg_suffix = _text(values, "admin_aifactorySuffixRG")
    project_prefix = _text(values, "projectPrefix", required=False, default="esml-")
    project_suffix = _text(values, "projectSuffix", required=False, default="-rg")
    common_base = _text(values, "vnetResourceGroupBase", required=False, default="esml-common") or "esml-common"
    override = _text(values, "commonResourceGroup_param", required=False).strip()
    common = (override.replace("<env>", env).replace("<network_env>", env) if override
              else f"{prefix}{common_base}-{suffix}-{env}{rg_suffix}")
    project_rg = f"{prefix}{project_prefix}project{number}-{suffix}-{env}{rg_suffix}{project_suffix}"
    for name in (project_rg, common):
        if not RG_NAME.fullmatch(name) or name.endswith("."):
            raise ValueError(f"Configuration resolves to an invalid resource group name: {name!r}")
    return FactoryScope(
        tenant_id=tenant, subscription_id=subscription, environment=env, project_number=number,
        location=location, location_suffix=suffix, project_resource_group=project_rg,
        common_resource_group=common, resource_group_prefix=prefix, resource_group_suffix=rg_suffix,
        flags=_flags(values),
    )


def explicit(*, tenant_id: str, subscription_id: str, environment: str, project_number: str, location: str,
             location_suffix: str, project_resource_group: str, common_resource_group: str = "",
             resource_group_prefix: str = "", resource_group_suffix: str = "") -> FactoryScope:
    """Scope from explicit values, for factories without a checked-out variables.json."""
    if environment not in ENVIRONMENTS:
        raise ValueError("Select an environment: dev, stage (test) or prod.")
    if not PROJECT_NUMBER.fullmatch(project_number or ""):
        raise ValueError("The project number must have three digits.")
    for name in filter(None, (project_resource_group, common_resource_group)):
        if not RG_NAME.fullmatch(name) or name.endswith("."):
            raise ValueError(f"Invalid resource group name: {name!r}")
    if not LOCATION.fullmatch(location or "") or not LOCATION.fullmatch(location_suffix or ""):
        raise ValueError("Location and location suffix must be lowercase alphanumeric.")
    return FactoryScope(
        tenant_id=_guid(tenant_id, "tenant"), subscription_id=_guid(subscription_id, "subscription"),
        environment=ENVIRONMENTS[environment], project_number=project_number, location=location,
        location_suffix=location_suffix, project_resource_group=project_resource_group,
        common_resource_group=common_resource_group, resource_group_prefix=resource_group_prefix,
        resource_group_suffix=resource_group_suffix, flags={},
    )


def health_model_location(location: str, override: str | None = None,
                          supported: set[str] | frozenset[str] | None = None) -> tuple[str, str]:
    """Choose a region that supports health models; returns (region, reason)."""
    regions = {r.lower().replace(" ", "") for r in (supported or SUPPORTED_REGIONS)}
    if override:
        choice = override.lower().replace(" ", "")
        if choice not in regions:
            raise ValueError(f"Health models are not supported in {choice}. Supported: {', '.join(sorted(regions))}.")
        return choice, "explicit"
    location = (location or "").lower().replace(" ", "")
    if location in regions:
        return location, "supported"
    fallback = REGION_FALLBACK.get(location)
    if fallback and fallback in regions:
        return fallback, f"{location} has no health model support; same-geography fallback to {fallback}"
    raise ValueError(
        f"Health models are not available in {location} and no same-geography fallback is defined. "
        "Pass --health-model-location with one of: " + ", ".join(sorted(regions))
    )
