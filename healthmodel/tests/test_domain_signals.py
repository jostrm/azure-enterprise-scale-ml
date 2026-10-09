"""Catalog domain objects: Flyweight signals, Prototype profiles, immutable catalog."""
from __future__ import annotations

import pytest

from aifactory_healthmodel import catalog as raw
from aifactory_healthmodel.domain.signals import SignalCatalog, SignalFactory


@pytest.fixture(scope="module")
def catalog():
    return SignalCatalog.from_document(raw.load_catalog())


def test_catalog_exposes_profiles_layers_and_rules(catalog):
    document = raw.load_catalog()
    assert [p.key for p in catalog.profiles] == [p["key"] for p in document["profiles"]]
    assert catalog.layer_order == tuple(layer["key"] for layer in document["layers"])
    assert catalog.api_version == document["apiVersion"]
    assert catalog.is_excluded("Microsoft.Network/privateEndpoints")
    assert "microsoft.app/jobs" in catalog.not_monitorable


@pytest.mark.parametrize("resource_type,kind,hns,expected", [
    ("Microsoft.CognitiveServices/accounts", "AIServices", None, "foundry"),
    ("microsoft.cognitiveservices/accounts", "OpenAI", None, "openai"),
    ("microsoft.storage/storageaccounts", "StorageV2", True, "adls-gen2"),
    ("microsoft.storage/storageaccounts", "StorageV2", None, "storage"),
    ("microsoft.foo/bars", "", None, None),
])
def test_classification_matches_the_raw_catalog(catalog, resource_type, kind, hns, expected):
    profile = catalog.classify(resource_type, kind, hns)
    assert (profile.key if profile else None) == expected
    reference = raw.classify(raw.load_catalog(), resource_type, kind, hns)
    assert (reference["key"] if reference else None) == expected


def test_signals_are_shared_flyweights_with_fresh_api_payloads(catalog):
    storage, lake = catalog.profile("storage"), catalog.profile("adls-gen2")
    assert all(a is b for a, b in zip(storage.signals, lake.signals)), "inherited signals share one instance"
    payload = storage.signals[0].to_api()
    payload["metricName"] = "changed"
    assert storage.signals[0].to_api()["metricName"] == "Availability"
    assert storage.signals[0].to_api() == raw.profile(raw.load_catalog(), "storage")["signals"][0]


def test_signal_factory_interns_identical_definitions():
    factory = SignalFactory()
    payload = {"name": "a-b", "evaluationRules": {"unhealthyRule": {"operator": "GreaterThan", "threshold": 1}}}
    assert factory.get(payload) is factory.get(dict(reversed(list(payload.items()))))
    assert len(factory) == 1


def test_profiles_are_prototypes(catalog):
    original = catalog.profile("vm")
    clone = original.clone(impact="Suppressed")
    assert clone.impact == "Suppressed" and original.impact == "Limited"
    assert clone.signals is original.signals and clone.key == original.key


def test_signal_evolve_validates_threshold_changes(catalog):
    signal = next(s for s in catalog.profile("foundry").signals if s.name == "throttled-calls")
    changed = signal.evolve({"degradedThreshold": 50, "unhealthyThreshold": 500}, "foundry/throttled-calls")
    rules = changed.to_api()["evaluationRules"]
    assert (rules["degradedRule"]["threshold"], rules["unhealthyRule"]["threshold"]) == (50, 500)
    assert signal.to_api()["evaluationRules"]["degradedRule"]["threshold"] == 10
    without = signal.evolve({"degradedThreshold": None}, "foundry/throttled-calls")
    assert "degradedRule" not in without.to_api()["evaluationRules"]
    with pytest.raises(ValueError, match="before the unhealthy"):
        signal.evolve({"degradedThreshold": 900, "unhealthyThreshold": 500}, "foundry/throttled-calls")
    with pytest.raises(ValueError, match="integers"):
        signal.evolve({"unhealthyThreshold": 1.5}, "foundry/throttled-calls")


def test_signal_source_rules(catalog):
    workspace = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.OperationalInsights/workspaces/la"
    assert catalog.profile("foundry").has_signal_source(None)
    assert not catalog.profile("databricks").has_signal_source(None)
    assert catalog.profile("databricks").has_signal_source(workspace)
    assert catalog.profile("health-model").has_signal_source(None)


def test_catalog_is_immutable(catalog):
    with pytest.raises(AttributeError):
        catalog.profile("vm").impact = "Standard"
    with pytest.raises(TypeError):
        catalog.not_monitorable["x"] = "y"
