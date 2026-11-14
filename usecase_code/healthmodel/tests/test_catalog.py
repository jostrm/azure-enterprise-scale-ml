"""Invariants for catalog/signal-catalog.json, the single source of truth for signals.

The metric fixture was captured from live metric definitions in the AI Factory
test environment (and the Microsoft Learn reference for absent types), so these
tests prove that every signal names a real metric, aggregation and time grain.
"""
from __future__ import annotations

import re

import pytest

from aifactory_healthmodel import catalog as cat

from conftest import VARIABLES_YAML

CATALOG = cat.load_catalog()
PROFILES = CATALOG["profiles"]
LAYERS = {layer["key"]: layer for layer in CATALOG["layers"]}

# Services the AI Factory enables by default (variables.yaml "true") plus the
# services explicitly requested for the first release of the health model.
DEFAULT_TRUE_RESOURCE_FLAGS = {
    "enableAIFoundry", "enableAFoundryCaphost", "enableAIFactoryCreatedDefaultProjectForAIFv2",
    "enableAISearch", "enableCosmosDB", "enableApplicationInsights", "enableBotService",
}
REQUESTED_SERVICES = {
    "storage": ("microsoft.storage/storageaccounts", False),
    "adls-gen2": ("microsoft.storage/storageaccounts", True),
    "vm": ("microsoft.compute/virtualmachines", None),
    "aks": ("microsoft.containerservice/managedclusters", None),
    "aml": ("microsoft.machinelearningservices/workspaces", None),
    "databricks": ("microsoft.databricks/workspaces", None),
    "containerapp": ("microsoft.app/containerapps", None),
    "containerapps-env": ("microsoft.app/managedenvironments", None),
    "postgres-flexible": ("microsoft.dbforpostgresql/flexibleservers", None),
    "keyvault": ("microsoft.keyvault/vaults", None),
}


def enable_flags_from_variables_yaml() -> dict[str, str]:
    flags = {}
    for line in VARIABLES_YAML.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^\s+((?:enable|ENABLE_)\w+):\s*"?(true|false)"?', line)
        if match:
            flags[match[1]] = match[2]
    return flags


def all_signals():
    for profile in PROFILES:
        for signal in profile["signals"]:
            yield profile, signal


def signal_ids():
    return [f"{p['key']}/{s['name']}" for p, s in all_signals()]


def test_catalog_declares_schema_and_api_version():
    assert CATALOG["schemaVersion"] == 1
    assert CATALOG["apiVersion"] in cat.SUPPORTED_API_VERSIONS


def test_layers_are_unique_and_use_valid_impact():
    keys = [layer["key"] for layer in CATALOG["layers"]]
    assert len(keys) == len(set(keys))
    for layer in CATALOG["layers"]:
        assert cat.NAME_PATTERN.fullmatch(f"layer-{layer['key']}")
        assert layer["impact"] in cat.IMPACTS
        assert 1 <= len(layer["displayName"]) <= 260


def test_profiles_are_unique_and_reference_known_layers(metric_definitions):
    keys = [profile["key"] for profile in PROFILES]
    assert len(keys) == len(set(keys))
    for profile in PROFILES:
        assert re.fullmatch(r"[a-z][a-z0-9-]{1,30}", profile["key"]), profile["key"]
        assert profile["layer"] in LAYERS, profile["key"]
        assert profile["impact"] in cat.IMPACTS
        assert profile["resourceHealth"] in {"Enabled", "Disabled"}
        assert profile["match"]["type"] == profile["match"]["type"].lower()
        if not profile.get("nestedModel"):
            assert profile["match"]["type"] in metric_definitions, profile["match"]["type"]


def test_every_profile_can_evaluate_health():
    for profile in PROFILES:
        # A nested health model contributes the state of its own root entity.
        evaluates = (profile["signals"] or profile["resourceHealth"] == "Enabled" or profile.get("nestedModel")
                     or profile.get("logAnalyticsSignals"))
        assert evaluates, profile["key"]


# Verified on the test factory: Azure Resource Health answered HTTP 422 (not supported).
RESOURCE_HEALTH_UNSUPPORTED = {
    "microsoft.app/managedenvironments", "microsoft.app/containerapps", "microsoft.app/jobs",
    "microsoft.databricks/workspaces", "microsoft.containerregistry/registries",
    "microsoft.machinelearningservices/workspaces",
}


def test_resource_health_is_disabled_where_azure_does_not_support_it():
    for profile in PROFILES:
        if profile["match"]["type"] in RESOURCE_HEALTH_UNSUPPORTED:
            assert profile["resourceHealth"] == "Disabled", profile["key"]


def test_log_analytics_signals_are_api_shaped():
    keys = {"name", "displayName", "signalKind", "queryText", "valueColumnName", "dataUnit", "timeGrain",
            "refreshInterval", "evaluationRules"}
    found = [(p, s) for p in PROFILES for s in p.get("logAnalyticsSignals", [])]
    assert {p["key"] for p, _ in found} == {"databricks"}
    for profile, signal in found:
        assert set(signal) == keys
        assert signal["signalKind"] == "LogAnalyticsQuery"
        assert 1 <= len(signal["queryText"]) <= 5000 and "isfuzzy" not in signal["queryText"]
        # Verified live: DatabricksJobs exists in the workspace schema even without diagnostic settings,
        # so the query must return no row (Unknown) unless logs actually flowed, never a green zero.
        assert "toscalar(" in signal["queryText"] and "| where flowing" in signal["queryText"]
        assert signal["valueColumnName"] in signal["queryText"]
        assert signal["refreshInterval"] in cat.REFRESH_INTERVALS
        assert profile.get("logAnalyticsTables")


def test_only_nested_model_profile_has_no_signal_source():
    nested = [p for p in PROFILES if p.get("nestedModel")]
    assert [p["match"]["type"] for p in nested] == ["microsoft.cloudhealth/healthmodels"]
    assert nested[0]["signals"] == [] and nested[0]["resourceHealth"] == "Disabled"


def test_classification_rules_do_not_overlap():
    seen = {}
    for profile in PROFILES:
        match = profile["match"]
        kinds = tuple(sorted(k.lower() for k in match.get("kinds") or ["*"]))
        for kind in kinds:
            key = (match["type"], kind, match.get("hns"))
            assert key not in seen, f"{profile['key']} overlaps {seen.get(key)}"
            seen[key] = profile["key"]


@pytest.mark.parametrize("signal_id", signal_ids())
def test_signal_shape_is_api_compatible(signal_id):
    profile_key, name = signal_id.split("/")
    signal = next(s for s in cat.profile(CATALOG, profile_key)["signals"] if s["name"] == name)
    assert set(signal) <= cat.SIGNAL_KEYS, set(signal) - cat.SIGNAL_KEYS
    assert cat.REQUIRED_SIGNAL_KEYS <= set(signal)
    assert cat.NAME_PATTERN.fullmatch(signal["name"])
    assert 1 <= len(signal["displayName"]) <= 260
    assert signal["signalKind"] == "AzureResourceMetric"
    assert signal["aggregationType"] in cat.AGGREGATIONS
    assert signal["refreshInterval"] in cat.REFRESH_INTERVALS
    assert re.fullmatch(r"PT\d+[MH]", signal["timeGrain"])


def test_signal_names_are_unique_per_profile():
    for profile in PROFILES:
        names = [s["name"] for s in profile["signals"]]
        assert len(names) == len(set(names)), profile["key"]
        assert len(names) <= 12, f"{profile['key']} has too many signals for a readable entity"


@pytest.mark.parametrize("signal_id", signal_ids())
def test_signal_metric_exists_with_supported_aggregation_and_grain(signal_id, metric_definitions):
    profile_key, name = signal_id.split("/")
    profile = cat.profile(CATALOG, profile_key)
    signal = next(s for s in profile["signals"] if s["name"] == name)
    assert signal["metricNamespace"] == profile["match"]["type"]
    metrics = metric_definitions[profile["match"]["type"]]["metrics"]
    assert signal["metricName"] in metrics, f"{signal['metricName']} is not a metric of {profile['match']['type']}"
    definition = metrics[signal["metricName"]]
    assert signal["aggregationType"] in definition["aggregations"], definition["aggregations"]
    assert signal["timeGrain"] in definition["timeGrains"], definition["timeGrains"]
    for dimension in re.findall(r"(\w+)\s+(?:eq|ne)\s+'", signal.get("dimensionFilter", "")):
        assert dimension in definition["dimensions"], f"unknown dimension {dimension}"


@pytest.mark.parametrize("signal_id", signal_ids())
def test_evaluation_rules_are_valid_and_ordered(signal_id):
    profile_key, name = signal_id.split("/")
    signal = next(s for s in cat.profile(CATALOG, profile_key)["signals"] if s["name"] == name)
    rules = signal["evaluationRules"]
    assert set(rules) <= {"degradedRule", "unhealthyRule"}
    unhealthy = rules["unhealthyRule"]
    assert unhealthy["operator"] in cat.OPERATORS - {"Dynamic"}
    # Bicep types thresholds as int; ints also avoid float drift in what-if.
    assert isinstance(unhealthy["threshold"], int) and not isinstance(unhealthy["threshold"], bool)
    degraded = rules.get("degradedRule")
    if degraded:
        assert degraded["operator"] == unhealthy["operator"]
        assert isinstance(degraded["threshold"], int)
        if unhealthy["operator"].startswith("Greater"):
            assert degraded["threshold"] <= unhealthy["threshold"]
        elif unhealthy["operator"].startswith("Less"):
            assert degraded["threshold"] >= unhealthy["threshold"]


def test_aggregation_groups_reference_existing_signals():
    for profile in PROFILES:
        names = {s["name"] for s in profile["signals"]}
        for group in profile.get("signalAggregationGroups", []):
            assert cat.NAME_PATTERN.fullmatch(group["name"])
            assert group["aggregationType"] in cat.GROUP_AGGREGATIONS
            assert set(group["members"]) <= names, profile["key"]
            assert len(group["members"]) == len(set(group["members"])) >= 2
            if group["aggregationType"] in {"BestOf", "WorstOf"}:
                assert not {"degradedThreshold", "unhealthyThreshold", "unit"} & set(group)


def test_availability_gate_pattern_for_foundry_models():
    foundry = cat.profile(CATALOG, "foundry")
    group = next(g for g in foundry["signalAggregationGroups"] if g["aggregationType"] == "BestOf")
    signals = {s["name"]: s for s in foundry["signals"]}
    metrics = {signals[m]["metricName"] for m in group["members"]}
    assert metrics == {"ModelAvailabilityRate", "ModelRequests"}
    gate = next(signals[m] for m in group["members"] if signals[m]["metricName"] == "ModelRequests")
    assert gate["evaluationRules"]["unhealthyRule"]["operator"] == "GreaterThanOrEqual"


def test_every_default_true_resource_flag_is_modelled():
    flags = enable_flags_from_variables_yaml()
    defaults_true = {flag for flag, value in flags.items() if value == "true"}
    non_resource = set(CATALOG["nonResourceFlags"])
    assert DEFAULT_TRUE_RESOURCE_FLAGS <= defaults_true
    assert defaults_true - non_resource == DEFAULT_TRUE_RESOURCE_FLAGS
    mapped = {flag for profile in PROFILES for flag in profile["enableFlags"]}
    assert DEFAULT_TRUE_RESOURCE_FLAGS <= mapped


def test_every_enable_flag_is_mapped_or_explained():
    flags = set(enable_flags_from_variables_yaml())
    mapped = {flag for profile in PROFILES for flag in profile["enableFlags"]}
    explained = CATALOG["nonResourceFlags"]
    assert all(reason.strip() for reason in explained.values())
    assert not (mapped & set(explained)), "a flag cannot be both modelled and explained away"
    assert flags - mapped - set(explained) == set()
    assert set(explained) <= flags, "stale explanation for a flag that no longer exists"


def test_requested_services_have_profiles():
    for key, (resource_type, hns) in REQUESTED_SERVICES.items():
        profile = cat.profile(CATALOG, key)
        assert profile["match"]["type"] == resource_type
        if hns is not None:
            assert profile["match"].get("hns") is hns


def test_databricks_relies_on_opt_in_log_analytics_without_platform_metrics(metric_definitions):
    assert metric_definitions["microsoft.databricks/workspaces"]["metrics"] == {}
    databricks = cat.profile(CATALOG, "databricks")
    assert databricks["signals"] == [] and databricks["resourceHealth"] == "Disabled"
    assert databricks["logAnalyticsSignals"]


def test_not_monitorable_types_are_explained_and_disjoint():
    not_monitorable = CATALOG["notMonitorable"]
    assert {"microsoft.containerregistry/registries", "microsoft.app/jobs"} <= set(not_monitorable)
    assert all(len(reason) > 40 for reason in not_monitorable.values())
    assert not set(not_monitorable) & set(CATALOG["excludedTypes"])
    assert not set(not_monitorable) & {p["match"]["type"] for p in PROFILES}


def test_excluded_types_are_plumbing_not_workloads():
    excluded = set(CATALOG["excludedTypes"])
    assert "microsoft.network/privateendpoints" in excluded
    assert "microsoft.network/networkinterfaces" in excluded
    assert not excluded & {p["match"]["type"] for p in PROFILES}


def test_profile_lookup_rejects_unknown_key():
    with pytest.raises(KeyError):
        cat.profile(CATALOG, "does-not-exist")


def test_common_flags_map_to_catalog_profiles():
    mapped = {flag for profile in PROFILES for flag in profile["enableFlags"]}
    assert set(CATALOG["commonResourceFlags"]) <= mapped
    assert "projectSharedProfiles" not in CATALOG, "model contents belong to definitions/*.json"


def test_classify_uses_kind_and_hierarchical_namespace():
    assert cat.classify(CATALOG, "Microsoft.CognitiveServices/accounts", "AIServices")["key"] == "foundry"
    assert cat.classify(CATALOG, "microsoft.cognitiveservices/accounts", "OpenAI")["key"] == "openai"
    assert cat.classify(CATALOG, "microsoft.cognitiveservices/accounts", "SpeechServices")["key"] == "ai-service"
    assert cat.classify(CATALOG, "microsoft.cognitiveservices/accounts", "Unknown") is None
    assert cat.classify(CATALOG, "microsoft.storage/storageaccounts", "StorageV2", True)["key"] == "adls-gen2"
    assert cat.classify(CATALOG, "microsoft.storage/storageaccounts", "StorageV2", False)["key"] == "storage"
    assert cat.classify(CATALOG, "microsoft.storage/storageaccounts", "StorageV2", None)["key"] == "storage"
    assert cat.classify(CATALOG, "microsoft.foo/bars") is None
    assert cat.is_excluded(CATALOG, "Microsoft.Network/privateEndpoints")
