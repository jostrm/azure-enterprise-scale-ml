"""Model definitions: Template Method planning, Factory Method kinds, registry and golden parity."""
from __future__ import annotations

import json
from collections import Counter

import pytest

from aifactory_healthmodel import naming
from aifactory_healthmodel.application.parameters import BicepParameterRenderer
from aifactory_healthmodel.domain.definitions import (DefinitionError, DefinitionRegistry, LayeredModelDefinition,
                                                      ModelDefinitionFactory)
from aifactory_healthmodel.domain.resources import parse_resources
from aifactory_healthmodel.domain.signals import SignalCatalog
from conftest import FIXTURES

SUB = "00000000-0000-0000-0000-0000000000aa"
PRJ, CMN = "spider-esml-project001-sdc-dev-001-rg", "spider-esml-common-sdc-dev-001"
CATALOG = SignalCatalog.from_file()


def factory_scope(flags=None):
    scope = naming.explicit(
        tenant_id="11111111-1111-1111-1111-111111111111", subscription_id=SUB, environment="dev",
        project_number="001", location="swedencentral", location_suffix="sdc", project_resource_group=PRJ,
        common_resource_group=CMN, resource_group_prefix="spider-", resource_group_suffix="-001")
    return naming.FactoryScope(**{**scope.__dict__, "flags": flags or {}})


@pytest.fixture(scope="module")
def registry():
    return DefinitionRegistry.builtin(CATALOG)


@pytest.fixture(scope="module")
def rows():
    return json.loads((FIXTURES / "test-env-resources.json").read_text(encoding="utf-8"))


def health_model_row(name, group):
    return {"id": f"/subscriptions/{SUB}/resourceGroups/{group}/providers/Microsoft.CloudHealth/healthmodels/{name}",
            "name": name, "type": "microsoft.cloudhealth/healthmodels", "resourceGroup": group, "kind": "", "tags": {}}


NESTED = [health_model_row("hm-spider-prj001-sdc-dev-001", PRJ), health_model_row("hm-spider-prj002-sdc-dev-001", PRJ),
          health_model_row("hm-other-prj001-sdc-dev-001", "other-rg")]
OVERRIDES = {"signals": {"foundry/throttled-calls": {"degradedThreshold": 50, "unhealthyThreshold": 500},
                         "storage/e2e-latency": {"enabled": False},
                         "cosmos/server-side-latency": {"degradedThreshold": None}},
             "profiles": {"vm": {"impact": "Suppressed"}, "databricks": {"enabled": False},
                          "appinsights": {"resourceHealth": "Enabled"}}}
FLAGS = {"enableAISearch": True, "enableDatabricks": False, "enablePostgreSQL": True, "enableAdminVM": True,
         "enableCosmosDB": True, "enableContainerApps": True, "enableDatafactoryCommon": False}
OPTIONS = {"healthObjective": 98, "alertPolicy": {"rootDegradedSeverity": ""}, "createActionGroup": True,
           "actionGroupEmails": ["ops@contoso.com"], "actionGroupIds": []}
# The same inputs that produced tests/fixtures/golden with the original procedural planner.
SCENARIOS = {
    "project-default": dict(definition="project"),
    "project-log-signals": dict(definition="project", workspace=True),
    "project-overrides": dict(definition="project", overrides=OVERRIDES),
    "project-flags": dict(definition="project", flags=FLAGS, overrides={"profiles": {"search": {"enabled": False}}}),
    "project-options": dict(definition="project", options=OPTIONS),
    "common-nested": dict(definition="common", nested=True),
    "common-flags": dict(definition="common", nested=True, flags=FLAGS, overrides=OVERRIDES),
}


def roundtrip(document):
    return json.loads(json.dumps(document))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_declarative_definitions_reproduce_the_golden_masters(registry, rows, name):
    scenario = SCENARIOS[name]
    resources = parse_resources(rows + (NESTED if scenario.get("nested") else []))
    workspace = next(r["id"] for r in rows if r["type"] == "microsoft.operationalinsights/workspaces")
    plan = registry.plan(scenario["definition"], factory_scope(scenario.get("flags")), resources,
                         overrides=scenario.get("overrides"), workspace=workspace if scenario.get("workspace") else None)
    document = BicepParameterRenderer().render(plan, location="swedencentral", options=scenario.get("options"))
    golden = json.loads((FIXTURES / "golden" / f"{name}.json").read_text(encoding="utf-8"))
    assert roundtrip(document) == golden["parameters"]
    assert roundtrip(plan.summary()) == golden["summary"]


def test_builtin_definitions(registry):
    assert registry.keys() == ("agents", "common", "project")
    assert registry.get("common").nests == frozenset({"project"})
    assert registry.get("project").home == "project" and registry.get("common").home == "common"
    assert registry.deployment_order(["common", "agents", "project"]) == ["agents", "project", "common"]


def test_agents_definition_models_the_agent_user_flow(registry, rows):
    plan = registry.plan("agents", factory_scope(FLAGS), parse_resources(rows))
    assert plan.model_name == "hm-spider-agt001-sdc-dev-001"
    assert plan.root_display_name == "AI Factory agents, project 001 (dev)"
    assert [e.name for e in plan.entities if e.role == "layer"] == [
        "layer-models", "layer-agent-runtime", "layer-knowledge", "layer-state", "layer-channels", "layer-telemetry"]
    assert Counter(e.profile for e in plan.entities if e.role == "resource") == Counter({
        "foundry": 1, "foundry-project": 1, "search": 1, "cosmos": 1, "storage": 2, "bot": 1, "appinsights": 1})
    assert {e.properties["impact"] for e in plan.entities if e.name in ("layer-channels", "layer-telemetry")} == {"Limited"}
    assert plan.coverage == [] and plan.unmodelled == [], "the agents model does not report factory coverage"
    assert plan.defaults["alertPolicy"]["layerUnhealthySeverity"] == "Sev2"


def test_definitions_are_prototypes(registry, rows):
    project = registry.get("project")
    quiet = project.clone(overrides={"profiles": {"aks": {"impact": "Suppressed"}}})
    plan = quiet.plan_for(factory_scope(), parse_resources(rows), siblings=registry.sibling_patterns(factory_scope()))
    assert next(e for e in plan.entities if e.profile == "aks").properties["impact"] == "Suppressed"
    assert registry.get("project").spec.overrides == {}, "the registered definition is unchanged"


def test_custom_definitions_load_from_a_directory(tmp_path, rows):
    (tmp_path / "data.json").write_text(json.dumps({
        "key": "data", "description": "Data platform", "nameToken": "dat{project}", "home": "project",
        "rootDisplayName": "Data platform {project} ({env})",
        "layers": [{"key": "lake", "displayName": "Lake", "impact": "Standard",
                    "select": {"profile": ["storage", "adls-gen2"]}},
                   {"fromCatalog": True, "select": {"origin": "project", "layer": "analytics"}}],
        "healthObjective": 95,
    }), encoding="utf-8")
    registry = DefinitionRegistry.builtin(CATALOG).load_directory(tmp_path)
    plan = registry.plan("data", factory_scope(), parse_resources(rows))
    assert plan.model_name == "hm-spider-dat001-sdc-dev-001"
    layers = [e.name for e in plan.entities if e.role == "layer"]
    assert layers == ["layer-analytics", "layer-lake"], "catalog layers keep catalog order; custom layers follow"
    assert {e.profile for e in plan.entities if e.role == "resource" and e.layer == "lake"} == {"storage", "adls-gen2"}
    assert plan.defaults == {"healthObjective": 95}


@pytest.mark.parametrize("change,message", [
    ({"surprise": 1}, "Unknown definition field"),
    ({"key": "Bad Key"}, "key"),
    ({"nameToken": "prj{project}"}, "token"),
    ({"nameToken": "x"}, "token"),
    ({"home": "hub"}, "home"),
    ({"layers": []}, "layers"),
    ({"layers": [{"key": "custom", "select": {"all": True}}]}, "displayName"),
    ({"layers": [{"fromCatalog": True, "key": "x", "select": {"all": True}}]}, "fromCatalog"),
    ({"layers": [{"key": "lake", "displayName": "L", "impact": "Loud", "select": {"all": True}}]}, "impact"),
    ({"layers": [{"key": "lake", "displayName": "L", "impact": "Standard", "select": {"profile": "nope"}}]}, "profile"),
    ({"layers": [{"key": "nested", "displayName": "Nested", "impact": "Standard", "select": {"nestedModel": "nope"}}]}, "nope"),
    ({"layers": [{"key": "nested", "displayName": "Nested", "impact": "Standard", "select": {"nestedModel": "data"}}]}, "itself"),
    ({"alertPolicy": {"rootUnhealthySeverity": "Sev9"}}, "severity"),
    ({"healthObjective": 101}, "healthObjective"),
    ({"overrides": {"profiles": {"vm": {"impact": "Loud"}}}}, "Impact"),
    ({"overrides": {"signals": {"foundry/throttled-calls": {"degradedThreshold": 900}}}}, "before the unhealthy"),
    ({"overrides": {"signals": {"foundry/throttled-calls": {"unhealthyThreshold": "high"}}}}, "integers"),
    ({"layers": [{"key": "nested", "displayName": "Nested", "impact": "Standard", "select": {"origin": "model"}}]},
     "nestedModel"),
    ({"layers": [{"fromCatalog": True, "select": {"anyOf": [{"layer": "data"}, {"profile": "health-model"}]}}]},
     "nestedModel"),
    ({"rootDisplayName": "Data {project:03d}"}, "format"),
    ({"rootDisplayName": "Data {project!r}"}, "format"),
    ({"rootDisplayName": "Data {project:{env}}"}, "format"),
    ({"rootDisplayName": "Data {project"}, "rootDisplayName"),
    ({"layers": [{"key": "lake-", "displayName": "Lake", "impact": "Standard", "select": {"profile": "storage"}}]},
     "Layer key"),
    ({"rootDisplayName": "Model {tenant}"}, "placeholder"),
    ({"kind": "graph"}, "kind"),
])
def test_invalid_definitions_fail_fast(change, message):
    document = {"key": "data", "nameToken": "dat{project}", "home": "project", "rootDisplayName": "Data {project}",
                "layers": [{"fromCatalog": True, "select": {"all": True}}], **change}
    with pytest.raises(DefinitionError, match=message):
        DefinitionRegistry.builtin(CATALOG).add_document(document, source="test")


def test_nesting_cycles_are_rejected():
    registry = DefinitionRegistry(CATALOG)
    for key, other in (("one", "two"), ("two", "one")):
        registry.add_document({"key": key, "nameToken": key[:3], "home": "project", "rootDisplayName": key,
                               "layers": [{"key": "nested", "displayName": "Nested", "impact": "Standard",
                                           "select": {"nestedModel": other}}]}, source="test", validate=False)
    with pytest.raises(DefinitionError, match="cycle"):
        registry.validate()


def test_factory_method_supports_new_definition_kinds(rows):
    class FoundryOnly(LayeredModelDefinition):
        """A coded definition: same template, different layer assignment."""

        def assign(self, candidate):
            return self.catalog.layer("genai") if candidate.profile.key == "foundry" else None

    factory = ModelDefinitionFactory()
    factory.register("foundry-only", FoundryOnly)
    registry = DefinitionRegistry(CATALOG, factory=factory)
    registry.add_document({"key": "fo", "kind": "foundry-only", "nameToken": "fdy{project}", "home": "project",
                           "rootDisplayName": "Foundry {project}", "layers": [{"fromCatalog": True, "select": {"all": True}}]},
                          source="test")
    plan = registry.plan("fo", factory_scope(), parse_resources(rows))
    assert isinstance(registry.get("fo"), FoundryOnly)
    assert [e.profile for e in plan.entities if e.role == "resource"] == ["foundry"]


def test_json_schema_matches_the_parser_and_accepts_the_builtin_definitions():
    from aifactory_healthmodel.domain.definitions import DEFINITION_FIELDS, DEFINITIONS_DIR
    from aifactory_healthmodel.domain.selectors import SelectorParser

    schema = json.loads((DEFINITIONS_DIR / "model-definition.schema.json").read_text(encoding="utf-8"))
    assert set(schema["properties"]) == set(DEFINITION_FIELDS)
    terms = {name[len("_term_"):] for name in dir(SelectorParser) if name.startswith("_term_")}
    assert set(schema["$defs"]["selector"]["properties"]) == terms
    jsonschema = pytest.importorskip("jsonschema")
    for path in sorted(DEFINITIONS_DIR.glob("*.json")):
        if not path.name.endswith(".schema.json"):
            jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), schema)


def test_only_definitions_named_by_nested_model_are_nested(rows):
    registry = DefinitionRegistry.builtin(CATALOG)
    registry.add_document({"key": "overview", "nameToken": "ovw", "home": "common", "rootDisplayName": "Overview",
                           "layers": [{"key": "projects", "select": {"nestedModel": "project"}},
                                      {"fromCatalog": True, "select": {"all": True}}]}, source="test")
    models = [health_model_row(name, PRJ) for name in ("hm-spider-prj001-sdc-dev-001", "hm-spider-agt001-sdc-dev-001")]
    plan = registry.plan("overview", factory_scope(), parse_resources(rows + models))
    nested = [e.resource_id.rsplit("/", 1)[-1] for e in plan.entities if e.profile == "health-model"]
    assert nested == ["hm-spider-prj001-sdc-dev-001"], "the agents model is not nested: overview does not name it"


def test_a_negated_model_selector_does_not_require_nesting():
    registry = DefinitionRegistry.builtin(CATALOG)
    registry.add_document({"key": "nomodels", "nameToken": "nom", "home": "project", "rootDisplayName": "No models",
                           "layers": [{"fromCatalog": True, "select": {"not": {"origin": "model"}}}]}, source="test")
    assert registry.get("nomodels").nests == frozenset()


@pytest.mark.parametrize("changes,message", [
    ({"health_objective": 150}, "healthObjective"),
    ({"alert_policy": {"rootUnhealthySeverity": "Sev9"}}, "severity"),
    ({"root_display_name": "Agents {project:x}"}, "format"),
    ({"home": "hub"}, "home"),
    ({"key": "Agents"}, "key"),
    ({"name_token": "agents-{project}"}, "token"),
])
def test_clones_are_validated_like_files(registry, changes, message):
    with pytest.raises(DefinitionError, match=message):
        registry.get("agents").clone(**{"key": "agents2", "name_token": "agx{project}", **changes})


def test_schema_patterns_match_the_parser():
    from aifactory_healthmodel.domain.definitions import DEFINITIONS_DIR, KEY_PATTERN, LAYER_KEY_PATTERN

    schema = json.loads((DEFINITIONS_DIR / "model-definition.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["key"]["pattern"] == f"^{KEY_PATTERN.pattern}$"
    assert schema["$defs"]["layer"]["properties"]["key"]["pattern"] == f"^{LAYER_KEY_PATTERN.pattern}$"
