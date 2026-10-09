"""Planning behaviour of the built-in project and common definitions on the anonymized test factory."""
from __future__ import annotations

from collections import Counter

import pytest

from aifactory_healthmodel import catalog as cat
from aifactory_healthmodel import naming
from aifactory_healthmodel.application.parameters import BicepParameterRenderer
from aifactory_healthmodel.domain.definitions import DefinitionRegistry
from aifactory_healthmodel.domain.resources import parse_resources
from aifactory_healthmodel.domain.visitors import AUTH_SETTING, MANAGED_BY

SUB = "00000000-0000-0000-0000-0000000000aa"
TENANT = "11111111-1111-1111-1111-111111111111"
PROJECT_RG = "spider-esml-project001-sdc-dev-001-rg"
COMMON_RG = "spider-esml-common-sdc-dev-001"
CATALOG = cat.load_catalog()
REGISTRY = DefinitionRegistry.builtin()


@pytest.fixture()
def scope():
    return naming.explicit(
        tenant_id=TENANT, subscription_id=SUB, environment="dev", project_number="001",
        location="swedencentral", location_suffix="sdc", project_resource_group=PROJECT_RG,
        common_resource_group=COMMON_RG, resource_group_prefix="spider-", resource_group_suffix="-001",
    )


@pytest.fixture()
def resources(test_env_resources):
    return parse_resources(test_env_resources)


def profiles_of(plan):
    return Counter(e.profile for e in plan.entities if e.role == "resource")


def test_project_model_monitors_every_project_workload_and_shared_dependencies(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    assert profiles_of(plan) == Counter({
        "foundry": 1, "foundry-project": 1, "search": 1, "cosmos": 1, "bot": 1,
        "storage": 2, "keyvault": 1, "appinsights": 1, "aml": 1, "aks": 1,
        "datafactory": 1, "containerapps-env": 1, "containerapp": 2,
        "loganalytics": 1, "adls-gen2": 2,
    })
    assert plan.unmodelled == []
    assert sorted(r.type for r in plan.not_monitorable) == ["microsoft.app/jobs", "microsoft.databricks/workspaces"]
    assert plan.model_name == "hm-spider-prj001-sdc-dev-001"


def test_databricks_is_modelled_with_log_analytics_signals_when_a_workspace_is_given(scope, resources):
    workspace = next(r.id for r in resources if r.type == "microsoft.operationalinsights/workspaces")
    plan = REGISTRY.plan("project", scope, resources, workspace=workspace)
    databricks = next(e for e in plan.entities if e.profile == "databricks")
    group = databricks.properties["signalGroups"]["azureLogAnalytics"]
    assert group["logAnalyticsWorkspaceResourceId"] == workspace
    assert group["authenticationSetting"] == AUTH_SETTING
    query = group["signals"][0]["queryText"]
    assert databricks.resource_id.lower() in query.lower() and "__RESOURCE_ID__" not in query
    assert databricks.properties["signalGroups"]["azureResource"]["resourceHealth"] == {"enabled": "Disabled"}
    assert COMMON_RG in plan.reader_resource_groups
    assert "microsoft.databricks/workspaces" not in {r.type for r in plan.not_monitorable}


def test_missing_log_analytics_workspace_is_explained(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    assert any("Databricks" in w and "--log-signals" in w for w in plan.warnings)


def test_log_analytics_workspace_must_be_a_workspace_id(scope, resources):
    with pytest.raises(ValueError):
        REGISTRY.plan("project", scope, resources,
                           workspace="/subscriptions/x/resourceGroups/y/providers/Microsoft.Storage/storageAccounts/z")


def test_shared_common_dependencies_use_the_limited_shared_layer(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    shared = [e for e in plan.entities if e.role == "resource" and e.scope == "common"]
    assert {e.profile for e in shared} == {"loganalytics", "adls-gen2"}
    assert {e.layer for e in shared} == {"shared"}
    layer = plan.entity("layer-shared")
    assert layer.properties["impact"] == "Limited"
    # Admin VMs and common Key Vaults belong to the factory (common) model only.
    assert not any(e.profile == "vm" for e in plan.entities)


def test_common_model_covers_vms_lake_vaults_and_nested_projects(scope, resources):
    project_model_id = (f"/subscriptions/{SUB}/resourceGroups/{PROJECT_RG}/providers/"
                        "Microsoft.CloudHealth/healthmodels/hm-spider-prj001-sdc-dev-001")
    nested = parse_resources([{
        "id": project_model_id, "name": "hm-spider-prj001-sdc-dev-001",
        "type": "microsoft.cloudhealth/healthmodels", "resourceGroup": PROJECT_RG, "kind": "", "tags": {},
    }, {
        "id": project_model_id.replace("spider", "other"), "name": "hm-other-prj001-sdc-dev-001",
        "type": "microsoft.cloudhealth/healthmodels", "resourceGroup": "other-esml-project001-sdc-dev-001-rg",
        "kind": "", "tags": {},
    }, {
        "id": project_model_id.replace("prj001-sdc-dev", "prj001-sdc-prod"), "name": "hm-spider-prj001-sdc-prod-001",
        "type": "microsoft.cloudhealth/healthmodels", "resourceGroup": PROJECT_RG, "kind": "", "tags": {},
    }])
    plan = REGISTRY.plan("common", scope, resources + nested)
    assert profiles_of(plan) == Counter({
        "vm": 2, "adls-gen2": 2, "keyvault": 2, "loganalytics": 1, "health-model": 1,
    })
    assert plan.unmodelled == []
    assert [r.type for r in plan.not_monitorable] == ["microsoft.containerregistry/registries"]
    assert plan.summary()["notMonitorable"] == {"microsoft.containerregistry/registries": 1}
    nested_entity = next(e for e in plan.entities if e.profile == "health-model")
    assert nested_entity.layer == "projects"
    group = nested_entity.properties["signalGroups"]["azureResource"]
    assert group["azureResourceId"] == project_model_id and group["signals"] == []
    assert group["azureResourceKind"] == "microsoft.cloudhealth/healthmodels"
    assert plan.model_name == "hm-spider-cmn-sdc-dev-001"
    assert set(plan.reader_resource_groups) == {COMMON_RG, PROJECT_RG}


def test_common_model_nests_all_projects_when_model_names_are_hashed(scope):
    long_scope = naming.FactoryScope(**{**scope.__dict__, "resource_group_prefix": "contoso-enterprise-aifact-"})
    rows = []
    for number in ("001", "002", "003"):
        project_scope = naming.FactoryScope(**{**long_scope.__dict__, "project_number": number})
        name = project_scope.model_name("project")
        rows.append({"id": f"/subscriptions/{SUB}/resourceGroups/rg-{number}/providers/Microsoft.CloudHealth/healthmodels/{name}",
                     "name": name, "type": "microsoft.cloudhealth/healthmodels", "resourceGroup": f"rg-{number}",
                     "kind": "", "tags": {}})
    common = naming.FactoryScope(**{**long_scope.__dict__, "common_resource_group": COMMON_RG})
    plan = REGISTRY.plan("common", common, parse_resources(rows))
    assert profiles_of(plan) == Counter({"health-model": 3})


def test_coverage_marks_profiles_disabled_by_overrides_instead_of_missing(scope, resources):
    scope = naming.FactoryScope(**{**scope.__dict__, "flags": {"enableAISearch": True}})
    plan = REGISTRY.plan("project", scope, resources,
                              overrides={"profiles": {"search": {"enabled": False}}})
    row = next(r for r in plan.coverage if r["flag"] == "enableAISearch")
    assert row["status"] == "excluded-by-override" and row["resources"] == 1
    assert not any("enableAISearch" in w for w in plan.warnings)


def test_entity_names_are_valid_unique_and_stable(scope, resources):
    first = REGISTRY.plan("project", scope, resources)
    second = REGISTRY.plan("project", scope, list(reversed(resources)))
    names = [e.name for e in first.entities]
    assert len(names) == len(set(names))
    assert all(cat.NAME_PATTERN.fullmatch(n) and len(n) <= 80 for n in names)
    assert sorted(names) == sorted(e.name for e in second.entities)


def test_relationships_form_a_tree_rooted_at_the_model(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    names = {e.name for e in plan.entities} | {plan.model_name}
    parents = Counter()
    for rel in plan.relationships:
        assert rel["parentEntityName"] in names and rel["childEntityName"] in names
        assert cat.NAME_PATTERN.fullmatch(rel["name"])
        parents[rel["childEntityName"]] += 1
    assert all(parents[e.name] == 1 for e in plan.entities)
    root_children = {r["childEntityName"] for r in plan.relationships if r["parentEntityName"] == plan.model_name}
    assert root_children == {e.name for e in plan.entities if e.role == "layer"}
    # Only layers that contain resources are created.
    used = {e.layer for e in plan.entities if e.role == "resource"}
    assert {e.name for e in plan.entities if e.role == "layer"} == {f"layer-{k}" for k in used}


def test_resource_entity_is_api_shaped_with_catalog_signals(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    foundry = next(e for e in plan.entities if e.profile == "foundry")
    props = foundry.properties
    assert set(props) == {"displayName", "impact", "icon", "canvasPosition", "tags", "signalGroups",
                          "signalAggregationGroups"}
    group = props["signalGroups"]["azureResource"]
    assert group["authenticationSetting"] == AUTH_SETTING
    assert group["azureResourceId"].endswith("/accounts/aif2bltscaae001dev")
    assert group["resourceHealth"] == {"enabled": "Enabled"}
    assert group["signals"] == cat.profile(CATALOG, "foundry")["signals"]
    assert props["signalAggregationGroups"] == cat.profile(CATALOG, "foundry")["signalAggregationGroups"]
    assert props["tags"]["managedBy"] == MANAGED_BY
    vault = next(e for e in plan.entities if e.profile == "keyvault")
    assert "signalAggregationGroups" not in vault.properties
    assert "azureLogAnalytics" not in vault.properties["signalGroups"]


def test_layer_entities_aggregate_children_worst_of(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    for entity in (e for e in plan.entities if e.role == "layer"):
        deps = entity.properties["signalGroups"]["dependencies"]
        assert deps == {"aggregationType": "WorstOf", "ignoreUnknown": True}
        assert entity.properties["tags"]["role"] == "layer"


def test_canvas_positions_are_integer_and_distinct(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    positions = [(e.properties["canvasPosition"]["x"], e.properties["canvasPosition"]["y"]) for e in plan.entities]
    assert all(isinstance(x, int) and isinstance(y, int) for x, y in positions)
    assert len(positions) == len(set(positions))


def test_signal_overrides_change_thresholds_and_disable_signals(scope, resources):
    overrides = {
        "signals": {
            "foundry/throttled-calls": {"degradedThreshold": 50, "unhealthyThreshold": 500},
            "storage/e2e-latency": {"enabled": False},
        },
        "profiles": {"vm": {"impact": "Suppressed"}, "databricks": {"enabled": False}},
    }
    plan = REGISTRY.plan("project", scope, resources, overrides=overrides)
    foundry = next(e for e in plan.entities if e.profile == "foundry")
    throttled = next(s for s in foundry.properties["signalGroups"]["azureResource"]["signals"]
                     if s["name"] == "throttled-calls")
    assert throttled["evaluationRules"]["degradedRule"]["threshold"] == 50
    assert throttled["evaluationRules"]["unhealthyRule"]["threshold"] == 500
    storage = next(e for e in plan.entities if e.profile == "storage")
    assert "e2e-latency" not in {s["name"] for s in storage.properties["signalGroups"]["azureResource"]["signals"]}
    assert not any(e.profile == "databricks" for e in plan.entities)
    assert CATALOG == cat.load_catalog(), "overrides must not mutate the catalog document"
    shared = REGISTRY.catalog.profile("foundry").signal("throttled-calls").to_api()
    assert shared["evaluationRules"]["unhealthyRule"]["threshold"] != 500, "nor the shared signal flyweights"


@pytest.mark.parametrize("bad", [
    {"signals": {"foundry/does-not-exist": {"enabled": False}}},
    {"signals": {"foundry/throttled-calls": {"degradedThreshold": 900, "unhealthyThreshold": 500}}},
    {"signals": {"foundry/throttled-calls": {"threshold": 1}}},
    {"profiles": {"nope": {"enabled": False}}},
    {"profiles": {"vm": {"impact": "Loud"}}},
    {"unknown": {}},
])
def test_invalid_overrides_fail_before_any_azure_call(scope, resources, bad):
    with pytest.raises(ValueError):
        REGISTRY.plan("project", scope, resources, overrides=bad)


def test_overrides_cannot_disable_the_availability_gate_partially(scope, resources):
    bad = {"signals": {"foundry/model-traffic-gate": {"enabled": False}}}
    with pytest.raises(ValueError, match="aggregation group"):
        REGISTRY.plan("project", scope, resources, overrides=bad)


def test_coverage_compares_enable_flags_with_discovered_resources(scope, resources):
    flags = {"enableAISearch": True, "enableDatabricks": False, "enablePostgreSQL": True,
             "enableAdminVM": True, "enableCosmosDB": True}
    scope = naming.FactoryScope(**{**scope.__dict__, "flags": flags})
    plan = REGISTRY.plan("project", scope, resources)
    rows = {row["flag"]: row for row in plan.coverage}
    assert rows["enableAISearch"]["status"] == "monitored"
    assert rows["enablePostgreSQL"]["status"] == "missing"
    assert rows["enableDatabricks"]["status"] == "present-but-disabled"
    assert "enableAdminVM" not in rows, "common-RG flags are reported by the common model"
    assert any("enablePostgreSQL" in w for w in plan.warnings)


def test_unknown_types_are_reported_not_silently_dropped(scope, resources):
    extra = parse_resources([{
        "id": f"/subscriptions/{SUB}/resourceGroups/{PROJECT_RG}/providers/Microsoft.Foo/bars/b1",
        "name": "b1", "type": "microsoft.foo/bars", "resourceGroup": PROJECT_RG, "kind": "", "tags": {},
    }])
    plan = REGISTRY.plan("project", scope, resources + extra)
    assert [r.type for r in plan.unmodelled] == ["microsoft.foo/bars"]


def test_sql_master_database_is_not_modelled(scope):
    rows = [{
        "id": f"/subscriptions/{SUB}/resourceGroups/{PROJECT_RG}/providers/Microsoft.Sql/servers/s1/databases/{name}",
        "name": f"s1/{name}", "type": "microsoft.sql/servers/databases", "resourceGroup": PROJECT_RG,
        "kind": "v12.0,user", "tags": {},
    } for name in ("master", "appdb")]
    plan = REGISTRY.plan("project", scope, parse_resources(rows))
    assert [e.display_name for e in plan.entities if e.role == "resource"] == ["Azure SQL Database: appdb"]


def test_resources_outside_the_scoped_groups_are_ignored(scope, resources):
    foreign = parse_resources([{
        "id": f"/subscriptions/{SUB}/resourceGroups/other-rg/providers/Microsoft.KeyVault/vaults/kv1",
        "name": "kv1", "type": "microsoft.keyvault/vaults", "resourceGroup": "other-rg", "kind": "", "tags": {},
    }])
    plan = REGISTRY.plan("project", scope, resources + foreign)
    assert not any(e.resource_id and "/other-rg/" in e.resource_id for e in plan.entities)


def test_bicep_parameters_document(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    document = BicepParameterRenderer().render(plan, location="swedencentral", options={"healthObjective": 99})
    params = document["parameters"]
    assert document["contentVersion"] == "1.0.0.0"
    assert params["healthModelName"]["value"] == plan.model_name
    assert params["location"]["value"] == "swedencentral"
    assert params["rootDisplayName"]["value"] == "AI Factory project 001 (dev)"
    assert params["healthObjective"]["value"] == 99
    assert params["readerResourceGroups"]["value"] == [PROJECT_RG, COMMON_RG]
    entities = params["entities"]["value"]
    assert {e["role"] for e in entities} == {"layer", "resource"}
    assert all(set(e) == {"name", "role", "properties"} for e in entities)
    assert params["relationships"]["value"] == plan.relationships


def test_unknown_bicep_option_is_rejected(scope, resources):
    plan = REGISTRY.plan("project", scope, resources)
    with pytest.raises(ValueError, match="option"):
        BicepParameterRenderer().render(plan, location="swedencentral", options={"notAParameter": 1})


def test_empty_project_produces_root_only_plan_with_warning(scope):
    plan = REGISTRY.plan("project", scope, [])
    assert plan.entities == [] and plan.relationships == []
    assert any("No modelled resources" in w for w in plan.warnings)


def test_summary_is_human_readable(scope, resources):
    workspace = next(r.id for r in resources if r.type == "microsoft.operationalinsights/workspaces")
    plan = REGISTRY.plan("project", scope, resources, workspace=workspace)
    summary = plan.summary()
    assert summary["entities"] == len(plan.entities)
    assert summary["signals"] == sum(
        len(group.get("signals", [])) for e in plan.entities if e.role == "resource"
        for group in e.properties["signalGroups"].values())
    assert summary["signals"] == 53
    assert summary["layers"]["genai"] >= 5
