"""Turn discovered Azure resources into a health model plan and Bicep parameters.

Pure functions only: no Azure calls. ``azure.py`` performs discovery and
deployment; this module classifies, renders entities/relationships from the
signal catalog, applies validated overrides and reports coverage drift against
the AI Factory ``enable*`` flags.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import catalog as cat
from .naming import FactoryScope

AUTH_SETTING = "systemassigned"
MANAGED_BY = "aifactory-healthmodel"
MODEL_SCOPES = ("project", "common")
NESTED_MODEL = re.compile(r"hm-[a-z0-9-]*prj\d{3}-[a-z0-9-]+")
WORKSPACE_ID = re.compile(r"/subscriptions/[0-9a-f-]{36}/resourceGroups/([\w().-]{1,90})/providers/"
                          r"Microsoft\.OperationalInsights/workspaces/[\w-]{4,63}", re.I)
BICEP_OPTIONS = frozenset({
    "healthObjective", "alertPolicy", "actionGroupIds", "createActionGroup", "actionGroupEmails",
    "actionGroupShortName", "assignReaderRoles", "tags",
})
LAYER_SPACING, RESOURCE_OFFSET, ROW_HEIGHT = 360, 90, 140


@dataclass(frozen=True)
class DiscoveredResource:
    id: str
    name: str
    type: str
    kind: str
    resource_group: str
    location: str = ""
    hns: bool | None = None
    tags: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def subscription_id(self) -> str:
        parts = self.id.split("/")
        return parts[2].lower() if len(parts) > 2 else ""

    @property
    def short_name(self) -> str:
        return self.name.split("/")[-1]


@dataclass
class PlannedEntity:
    name: str
    role: str
    layer: str
    display_name: str
    properties: dict
    profile: str | None = None
    resource_id: str | None = None
    scope: str | None = None

    def as_parameter(self) -> dict:
        return {"name": self.name, "role": self.role, "properties": self.properties}


@dataclass
class Plan:
    model_name: str
    model_scope: str
    scope: FactoryScope
    root_display_name: str
    entities: list[PlannedEntity]
    relationships: list[dict]
    reader_resource_groups: list[str]
    coverage: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unmodelled: list[DiscoveredResource] = field(default_factory=list)
    not_monitorable: list[DiscoveredResource] = field(default_factory=list)

    def entity(self, name: str) -> PlannedEntity:
        for item in self.entities:
            if item.name == name:
                return item
        raise KeyError(name)

    def summary(self) -> dict:
        resources = [e for e in self.entities if e.role == "resource"]
        return {
            "model": self.model_name,
            "modelScope": self.model_scope,
            "subscription": self.scope.subscription_id,
            "resourceGroup": self.home_resource_group,
            "entities": len(self.entities),
            "resources": len(resources),
            "layers": dict(Counter(e.layer for e in resources)),
            "profiles": dict(sorted(Counter(e.profile for e in resources).items())),
            "signals": sum(len(group.get("signals", [])) for e in resources
                           for group in e.properties["signalGroups"].values()),
            "relationships": len(self.relationships),
            "readerResourceGroups": self.reader_resource_groups,
            "unmodelled": sorted({r.type for r in self.unmodelled}),
            "notMonitorable": dict(sorted(Counter(r.type for r in self.not_monitorable).items())),
            "coverage": self.coverage,
            "warnings": self.warnings,
        }

    @property
    def home_resource_group(self) -> str:
        return self.scope.project_resource_group if self.model_scope == "project" else self.scope.common_resource_group


def parse_resources(rows: list[dict]) -> list[DiscoveredResource]:
    resources = []
    for row in rows or []:
        hns = row.get("hns")
        resources.append(DiscoveredResource(
            id=str(row["id"]), name=str(row["name"]), type=str(row["type"]).lower(),
            kind=str(row.get("kind") or ""), resource_group=str(row.get("resourceGroup") or ""),
            location=str(row.get("location") or ""), hns=None if hns is None else bool(hns),
            tags=dict(row.get("tags") or {}),
        ))
    return resources


def _sanitize(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower())
    return re.sub(r"-{2,}", "-", value).strip("-")


def entity_name(profile_key: str, resource: DiscoveredResource) -> str:
    base = _sanitize(resource.name.replace("/", "-"))[:50].strip("-") or "resource"
    digest = hashlib.sha1(resource.id.lower().encode("utf-8")).hexdigest()[:6]
    return f"{profile_key}-{base}-{digest}"


def _validate_overrides(catalog: dict, overrides: dict) -> dict:
    overrides = copy.deepcopy(overrides or {})
    unknown = set(overrides) - {"signals", "profiles"}
    if unknown:
        raise ValueError(f"Unknown override sections: {sorted(unknown)}")
    profiles = {p["key"]: p for p in catalog["profiles"]}
    for key, change in (overrides.get("profiles") or {}).items():
        if key not in profiles:
            raise ValueError(f"Override references unknown profile {key!r}.")
        bad = set(change) - {"enabled", "impact", "resourceHealth"}
        if bad:
            raise ValueError(f"Unsupported profile override fields for {key}: {sorted(bad)}")
        if "impact" in change and change["impact"] not in cat.IMPACTS:
            raise ValueError(f"Impact for {key} must be one of {sorted(cat.IMPACTS)}.")
        if "resourceHealth" in change and change["resourceHealth"] not in {"Enabled", "Disabled"}:
            raise ValueError(f"resourceHealth for {key} must be Enabled or Disabled.")
    for key, change in (overrides.get("signals") or {}).items():
        profile_key, _, signal_name = key.partition("/")
        profile = profiles.get(profile_key)
        if not profile or signal_name not in {s["name"] for s in profile["signals"]}:
            raise ValueError(f"Override references unknown signal {key!r}.")
        bad = set(change) - {"enabled", "degradedThreshold", "unhealthyThreshold", "timeGrain", "refreshInterval"}
        if bad:
            raise ValueError(f"Unsupported signal override fields for {key}: {sorted(bad)}")
        if change.get("enabled") is False and any(
                signal_name in g["members"] for g in profile.get("signalAggregationGroups", [])):
            raise ValueError(f"{key} belongs to an aggregation group; disable the whole profile instead.")
        if "refreshInterval" in change and change["refreshInterval"] not in cat.REFRESH_INTERVALS:
            raise ValueError(f"refreshInterval for {key} is not supported.")
    return overrides


def _apply_signal_override(signal: dict, change: dict, key: str) -> dict:
    signal = copy.deepcopy(signal)
    rules = signal["evaluationRules"]
    if "unhealthyThreshold" in change:
        rules["unhealthyRule"]["threshold"] = change["unhealthyThreshold"]
    if "degradedThreshold" in change:
        if change["degradedThreshold"] is None:
            rules.pop("degradedRule", None)
        else:
            rules.setdefault("degradedRule", {"operator": rules["unhealthyRule"]["operator"]})
            rules["degradedRule"]["threshold"] = change["degradedThreshold"]
    for field_name in ("timeGrain", "refreshInterval"):
        if field_name in change:
            signal[field_name] = change[field_name]
    unhealthy, degraded = rules["unhealthyRule"], rules.get("degradedRule")
    for rule in filter(None, (unhealthy, degraded)):
        if not isinstance(rule.get("threshold"), int) or isinstance(rule.get("threshold"), bool):
            raise ValueError(f"Thresholds for {key} must be integers.")
    if degraded:
        operator = unhealthy["operator"]
        if (operator.startswith("Greater") and degraded["threshold"] > unhealthy["threshold"]) or (
                operator.startswith("Less") and degraded["threshold"] < unhealthy["threshold"]):
            raise ValueError(f"Degraded threshold for {key} must be reached before the unhealthy threshold.")
    return signal


def _resolve_profile(catalog: dict, profile: dict, overrides: dict) -> dict | None:
    change = (overrides.get("profiles") or {}).get(profile["key"], {})
    if change.get("enabled") is False:
        return None
    resolved = copy.deepcopy(profile)
    for field_name in ("impact", "resourceHealth"):
        if field_name in change:
            resolved[field_name] = change[field_name]
    signals = []
    for signal in resolved["signals"]:
        key = f"{profile['key']}/{signal['name']}"
        signal_change = (overrides.get("signals") or {}).get(key)
        if signal_change is None:
            signals.append(signal)
        elif signal_change.get("enabled", True):
            signals.append(_apply_signal_override(signal, signal_change, key))
    resolved["signals"] = signals
    return resolved


def nested_model_pattern(scope: FactoryScope) -> re.Pattern:
    """Names of project models that belong to the same factory scale set and environment."""
    sample = scope.model_name("project")
    token = f"prj{scope.project_number}"
    if token not in sample:
        return NESTED_MODEL
    return re.compile(re.escape(sample).replace(re.escape(token), r"prj\d{3}"))


def _select(catalog: dict, scope: FactoryScope, resources: list[DiscoveredResource], model_scope: str,
            model_name: str):
    """Return (monitored [(resource, profile_key, layer, origin)], unmodelled, not_monitorable)."""
    project_rg, common_rg = scope.project_resource_group.lower(), scope.common_resource_group.lower()
    shared_profiles = set(catalog["projectSharedProfiles"])
    not_monitorable_types = set(catalog.get("notMonitorable", {}))
    nested_pattern = nested_model_pattern(scope)
    monitored, unmodelled, not_monitorable = [], [], []
    for resource in resources:
        if resource.subscription_id != scope.subscription_id.lower():
            continue
        group = resource.resource_group.lower()
        profile = cat.classify(catalog, resource.type, resource.kind, resource.hns)
        if resource.type == "microsoft.sql/servers/databases" and resource.short_name.lower() == "master":
            continue
        if profile and profile.get("nestedModel"):
            if (model_scope == "common" and nested_pattern.fullmatch(resource.name.lower())
                    and resource.name.lower() != model_name):
                monitored.append((resource, profile["key"], profile["layer"], "project"))
            continue
        if model_scope == "project":
            if group == project_rg:
                origin = "project"
            elif group == common_rg and profile and profile["key"] in shared_profiles:
                monitored.append((resource, profile["key"], "shared", "common"))
                continue
            else:
                continue
        else:
            if group != common_rg:
                continue
            origin = "common"
        if profile is None:
            if resource.type in not_monitorable_types:
                not_monitorable.append(resource)
            elif not cat.is_excluded(catalog, resource.type):
                unmodelled.append(resource)
            continue
        monitored.append((resource, profile["key"], profile["layer"], origin))
    return monitored, unmodelled, not_monitorable


def _resource_properties(profile: dict, resource: DiscoveredResource, layer: str, origin: str,
                         position: dict, workspace: str | None = None) -> dict:
    nested = bool(profile.get("nestedModel"))
    group = {
        "authenticationSetting": AUTH_SETTING,
        "azureResourceId": resource.id,
        "azureResourceKind": resource.type if nested else resource.kind,
        "resourceHealth": {"enabled": profile["resourceHealth"]},
        "signals": copy.deepcopy(profile["signals"]),
    }
    properties = {
        "displayName": f"{profile['displayName']}: {resource.short_name}"[:260],
        "impact": profile["impact"],
        "icon": {"iconName": "Resource"},
        "canvasPosition": position,
        "tags": {"managedBy": MANAGED_BY, "role": "resource", "profile": profile["key"], "layer": layer,
                 "aifactoryScope": origin},
        "signalGroups": {"azureResource": group},
    }
    if workspace and profile.get("logAnalyticsSignals"):
        signals = copy.deepcopy(profile["logAnalyticsSignals"])
        for signal in signals:
            # Resource IDs contain no quotes; scope every query to this one resource.
            signal["queryText"] = signal["queryText"].replace("__RESOURCE_ID__", resource.id.lower())
        properties["signalGroups"]["azureLogAnalytics"] = {
            "authenticationSetting": AUTH_SETTING, "logAnalyticsWorkspaceResourceId": workspace, "signals": signals}
    if profile.get("signalAggregationGroups"):
        properties["signalAggregationGroups"] = copy.deepcopy(profile["signalAggregationGroups"])
    return properties


def _has_signal_source(profile: dict, workspace: str | None) -> bool:
    return bool(profile["signals"] or profile["resourceHealth"] == "Enabled" or profile.get("nestedModel")
                or (workspace and profile.get("logAnalyticsSignals")))


def _coverage(catalog: dict, scope: FactoryScope, monitored, model_scope: str) -> tuple[list[dict], list[str]]:
    if not scope.flags:
        return [], []
    common_flags = set(catalog["commonResourceFlags"])
    home = "project" if model_scope == "project" else "common"
    counts = Counter(profile for _, profile, _, origin in monitored if origin == home)
    by_flag = defaultdict(list)
    for profile in catalog["profiles"]:
        for flag in profile["enableFlags"]:
            by_flag[flag].append(profile["key"])
    rows, warnings = [], []
    for flag in sorted(by_flag):
        if flag not in scope.flags or (flag in common_flags) != (model_scope == "common"):
            continue
        enabled, found = scope.flags[flag], sum(counts[p] for p in by_flag[flag])
        status = ("monitored" if enabled and found else "missing" if enabled
                  else "present-but-disabled" if found else "disabled")
        rows.append({"flag": flag, "enabled": enabled, "profiles": by_flag[flag], "resources": found,
                     "status": status})
        if status == "missing":
            warnings.append(f"{flag} is true but no {'/'.join(by_flag[flag])} resource was found; "
                            "the deployment may be incomplete or the resource was removed.")
    return rows, warnings


def build_plan(catalog: dict, scope: FactoryScope, resources: list[DiscoveredResource], *,
               model_scope: str = "project", overrides: dict | None = None,
               model_name: str | None = None, log_analytics_workspace_id: str | None = None) -> Plan:
    if model_scope not in MODEL_SCOPES:
        raise ValueError("model_scope must be 'project' or 'common'.")
    workspace = log_analytics_workspace_id or None
    if workspace and not WORKSPACE_ID.fullmatch(workspace):
        raise ValueError("log_analytics_workspace_id must be a Log Analytics workspace resource ID.")
    overrides = _validate_overrides(catalog, overrides or {})
    model_name = model_name or scope.model_name(model_scope)
    if not cat.MODEL_NAME_PATTERN.fullmatch(model_name):
        raise ValueError(f"Invalid health model name {model_name!r}.")
    resolved = {p["key"]: _resolve_profile(catalog, p, overrides) for p in catalog["profiles"]}
    discovered, unmodelled, not_monitorable = _select(catalog, scope, resources, model_scope, model_name)
    discovered = [m for m in discovered if resolved[m[1]] is not None]
    monitored = [m for m in discovered if _has_signal_source(resolved[m[1]], workspace)]
    hints = []
    for resource, profile_key, _, _ in discovered:
        if not _has_signal_source(resolved[profile_key], workspace):
            not_monitorable.append(resource)
            hint = resolved[profile_key].get("noSourceHint") or f"{profile_key} has no signal source."
            if hint not in hints:
                hints.append(hint)
    monitored.sort(key=lambda m: ([l["key"] for l in catalog["layers"]].index(m[2]), m[1], m[0].id.lower()))

    layer_order = [l["key"] for l in catalog["layers"] if any(m[2] == l["key"] for m in monitored)]
    layer_x = {key: int((i - (len(layer_order) - 1) / 2) * LAYER_SPACING) for i, key in enumerate(layer_order)}
    entities, relationships = [], []
    for key in layer_order:
        definition = cat.layer(catalog, key)
        entities.append(PlannedEntity(
            name=f"layer-{key}", role="layer", layer=key, display_name=definition["displayName"],
            properties={
                "displayName": definition["displayName"],
                "impact": definition["impact"],
                "icon": {"iconName": "SystemComponent"},
                "canvasPosition": {"x": layer_x[key], "y": 220},
                "tags": {"managedBy": MANAGED_BY, "role": "layer", "layer": key},
                "signalGroups": {"dependencies": {"aggregationType": "WorstOf", "ignoreUnknown": True}},
            },
        ))
        relationships.append(_relationship(model_name, f"layer-{key}"))

    per_layer = Counter()
    for resource, profile_key, layer_key, origin in monitored:
        index = per_layer[layer_key]
        per_layer[layer_key] += 1
        count = sum(1 for m in monitored if m[2] == layer_key)
        offset = 0 if count == 1 else (RESOURCE_OFFSET if index % 2 else -RESOURCE_OFFSET)
        position = {"x": layer_x[layer_key] + offset, "y": 440 + (index // 2 if count > 1 else index) * ROW_HEIGHT}
        profile = resolved[profile_key]
        name = entity_name(profile_key, resource)
        properties = _resource_properties(profile, resource, layer_key, origin, position, workspace)
        entities.append(PlannedEntity(
            name=name, role="resource", layer=layer_key, display_name=properties["displayName"],
            properties=properties, profile=profile_key, resource_id=resource.id, scope=origin,
        ))
        relationships.append(_relationship(f"layer-{layer_key}", name))

    coverage, warnings = _coverage(catalog, scope, discovered, model_scope)
    warnings.extend(hints)
    if not monitored:
        warnings.append("No modelled resources were found; only the root entity will be created.")
    groups = [scope.project_resource_group if model_scope == "project" else scope.common_resource_group]
    for resource, _, _, _ in monitored:
        if resource.resource_group not in groups:
            groups.append(resource.resource_group)
    if workspace and any("azureLogAnalytics" in e.properties["signalGroups"] for e in entities if e.role == "resource"):
        workspace_group = WORKSPACE_ID.fullmatch(workspace).group(1)
        if workspace_group.lower() not in {g.lower() for g in groups}:
            groups.append(workspace_group)
    root = (f"AI Factory project {scope.project_number} ({scope.environment})" if model_scope == "project"
            else f"AI Factory common services ({scope.environment})")
    return Plan(model_name=model_name, model_scope=model_scope, scope=scope, root_display_name=root,
                entities=entities, relationships=relationships, reader_resource_groups=groups,
                coverage=coverage, warnings=warnings, unmodelled=unmodelled, not_monitorable=not_monitorable)


def _relationship(parent: str, child: str) -> dict:
    return {"name": f"{parent}-to-{child}", "parentEntityName": parent, "childEntityName": child}


def bicep_parameters(plan: Plan, *, location: str, options: dict | None = None) -> dict:
    """ARM deployment parameters for ``bicep/main.bicep``."""
    options = dict(options or {})
    unknown = set(options) - BICEP_OPTIONS
    if unknown:
        raise ValueError(f"Unsupported Bicep option(s): {sorted(unknown)}")
    values = {
        "healthModelName": plan.model_name,
        "location": location,
        "modelScope": plan.model_scope,
        "rootDisplayName": plan.root_display_name,
        "readerResourceGroups": plan.reader_resource_groups,
        "entities": [e.as_parameter() for e in plan.entities],
        "relationships": plan.relationships,
        **options,
    }
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {key: {"value": value} for key, value in values.items()},
    }
