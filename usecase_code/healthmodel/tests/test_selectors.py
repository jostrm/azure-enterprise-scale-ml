"""Interpreter/Specification: the JSON selector language used by model definitions."""
from __future__ import annotations

import pytest

from aifactory_healthmodel.domain.classification import Candidate
from aifactory_healthmodel.domain.resources import DiscoveredResource
from aifactory_healthmodel.domain.selectors import SelectorError, SelectorParser
from aifactory_healthmodel.domain.signals import SignalCatalog

SUB = "00000000-0000-0000-0000-0000000000aa"


@pytest.fixture(scope="module")
def catalog():
    return SignalCatalog.from_file()


@pytest.fixture(scope="module")
def parse(catalog):
    return SelectorParser(catalog, definition_keys={"project", "common"}).parse


def candidate(catalog, profile_key, origin="project", name="res1", tags=None, nested=None):
    profile = catalog.profile(profile_key)
    resource = DiscoveredResource(
        id=f"/subscriptions/{SUB}/resourceGroups/rg/providers/{profile.resource_type}/{name}",
        name=name, type=profile.resource_type, kind="", resource_group="rg", tags=tags or {})
    return Candidate(resource, profile, origin, nested_definition=nested)


def test_profile_origin_type_and_layer_terms(catalog, parse):
    vault = candidate(catalog, "keyvault", origin="common")
    assert parse({"profile": "keyvault"}).matches(vault)
    assert parse({"profile": ["vm", "keyvault"]}).matches(vault)
    assert not parse({"profile": "vm"}).matches(vault)
    assert parse({"origin": "common"}).matches(vault) and not parse({"origin": "project"}).matches(vault)
    assert parse({"type": "Microsoft.KeyVault/Vaults"}).matches(vault)
    assert parse({"layer": "security"}).matches(vault) and not parse({"layer": "genai"}).matches(vault)


def test_several_keys_in_one_object_mean_all_of(catalog, parse):
    selector = parse({"origin": "common", "profile": ["loganalytics", "adls-gen2"]})
    assert selector.matches(candidate(catalog, "loganalytics", origin="common"))
    assert not selector.matches(candidate(catalog, "loganalytics", origin="project"))
    assert not selector.matches(candidate(catalog, "keyvault", origin="common"))
    assert selector.describe() == "origin = common and profile in (loganalytics, adls-gen2)"


def test_boolean_composition(catalog, parse):
    selector = parse({"anyOf": [{"profile": "search"}, {"allOf": [{"layer": "genai"}, {"not": {"profile": "bot"}}]}]})
    assert selector.matches(candidate(catalog, "search"))
    assert selector.matches(candidate(catalog, "foundry"))
    assert not selector.matches(candidate(catalog, "bot"))
    assert not selector.matches(candidate(catalog, "vm"))
    assert selector.describe() == "profile = search or (layer = genai and not (profile = bot))"


def test_specifications_compose_with_operators(catalog, parse):
    genai, common = parse({"layer": "genai"}), parse({"origin": "common"})
    assert (genai & ~common).matches(candidate(catalog, "foundry"))
    assert not (genai & ~common).matches(candidate(catalog, "foundry", origin="common"))
    assert (genai | common).matches(candidate(catalog, "vm", origin="common"))


def test_tag_and_name_terms(catalog, parse):
    tagged = candidate(catalog, "storage", name="stagentfiles001", tags={"workload": "Agents", "tier": "1"})
    assert parse({"tag": {"workload": "agents"}}).matches(tagged), "tag values compare case-insensitively"
    assert parse({"tag": {"tier": ["1", "2"]}}).matches(tagged)
    assert parse({"tag": {"workload": True}}).matches(tagged)
    assert not parse({"tag": {"owner": True}}).matches(tagged)
    assert parse({"name": "st(agent|chat).*"}).matches(tagged)
    assert not parse({"name": "agent"}).matches(tagged), "names must match completely"


def test_nested_model_and_everything_terms(catalog, parse):
    nested = candidate(catalog, "health-model", origin="model", nested="project")
    assert parse({"nestedModel": "project"}).matches(nested)
    assert not parse({"nestedModel": "common"}).matches(nested)
    assert not parse({"origin": "project"}).matches(nested), "nested models are only selected explicitly"
    assert parse({"all": True}).matches(nested)


@pytest.mark.parametrize("expression,message", [
    ({"profiles": "vm"}, "Unknown selector term"),
    ({"profile": "nope"}, "Unknown profile"),
    ({"origin": "elsewhere"}, "origin"),
    ({"layer": "nope"}, "Unknown layer"),
    ({"anyOf": []}, "at least one"),
    ({"name": "("}, "regular expression"),
    ({"nestedModel": "agents"}, "Unknown model definition"),
    ({"all": False}, "all"),
    ({}, "empty"),
    ("profile", "object"),
    ({"tag": {}}, "tag"),
])
def test_invalid_selectors_are_rejected_with_a_clear_message(parse, expression, message):
    with pytest.raises(SelectorError, match=message):
        parse(expression)
