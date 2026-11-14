"""Chain of Responsibility: how discovered resources become model candidates."""
from __future__ import annotations

import pytest

from aifactory_healthmodel import naming
from aifactory_healthmodel.domain.classification import (Candidate, ClassificationContext, Dropped,
                                                         Unclassified, default_chain)
from aifactory_healthmodel.domain.resources import parse_resources
from aifactory_healthmodel.domain.signals import SignalCatalog

SUB = "00000000-0000-0000-0000-0000000000aa"
PROJECT_RG, COMMON_RG = "spider-esml-project001-sdc-dev-001-rg", "spider-esml-common-sdc-dev-001"


@pytest.fixture(scope="module")
def context():
    scope = naming.explicit(
        tenant_id="11111111-1111-1111-1111-111111111111", subscription_id=SUB, environment="dev",
        project_number="001", location="swedencentral", location_suffix="sdc", project_resource_group=PROJECT_RG,
        common_resource_group=COMMON_RG, resource_group_prefix="spider-", resource_group_suffix="-001")
    return ClassificationContext(
        scope=scope, catalog=SignalCatalog.from_file(), model_name="hm-spider-cmn-sdc-dev-001",
        siblings={"project": (scope.sibling_model_pattern("prj{project}"), "project")})


def row(name, rtype, group, sub=SUB, kind="", provider=None):
    provider = provider or rtype
    return {"id": f"/subscriptions/{sub}/resourceGroups/{group}/providers/{provider}/{name}", "name": name,
            "type": rtype, "resourceGroup": group, "kind": kind, "tags": {}}


def classify(context, *rows):
    chain = default_chain()
    return [chain.handle(resource, context) for resource in parse_resources(list(rows))]


def test_catalog_resources_get_their_origin_from_the_resource_group(context):
    project, common = classify(context, row("kv1", "microsoft.keyvault/vaults", PROJECT_RG),
                               row("kv2", "microsoft.keyvault/vaults", COMMON_RG))
    assert isinstance(project, Candidate) and project.origin == "project" and project.profile.key == "keyvault"
    assert isinstance(common, Candidate) and common.origin == "common" and common.aifactory_scope == "common"


def test_guards_drop_foreign_subscriptions_master_databases_and_other_groups(context):
    results = classify(
        context,
        row("kv1", "microsoft.keyvault/vaults", PROJECT_RG, sub="00000000-0000-0000-0000-0000000000bb"),
        row("s1/master", "microsoft.sql/servers/databases", PROJECT_RG, kind="v12.0,system"),
        row("kv3", "microsoft.keyvault/vaults", "other-rg"),
    )
    assert [type(r) for r in results] == [Dropped, Dropped, Dropped]
    assert [r.reason for r in results] == ["other-subscription", "system-database", "outside-factory"]


def test_nested_models_resolve_to_their_definition(context):
    sibling, foreign, own = classify(
        context,
        row("hm-spider-prj002-sdc-dev-001", "microsoft.cloudhealth/healthmodels", "rg-2"),
        row("hm-spider-prj002-sdc-prod-001", "microsoft.cloudhealth/healthmodels", "rg-2"),
        row("hm-spider-cmn-sdc-dev-001", "microsoft.cloudhealth/healthmodels", COMMON_RG),
    )
    assert isinstance(sibling, Candidate) and sibling.origin == "model"
    assert sibling.nested_definition == "project" and sibling.aifactory_scope == "project"
    assert isinstance(foreign, Dropped) and isinstance(own, Dropped)


def test_unmodelled_not_monitorable_and_excluded_types(context):
    unknown, registry, endpoint = classify(
        context,
        row("b1", "microsoft.foo/bars", PROJECT_RG),
        row("acr1", "microsoft.containerregistry/registries", COMMON_RG),
        row("pe1", "microsoft.network/privateendpoints", PROJECT_RG),
    )
    assert isinstance(unknown, Unclassified) and unknown.reason == "unmodelled" and unknown.origin == "project"
    assert isinstance(registry, Unclassified) and registry.reason == "not-monitorable"
    assert isinstance(endpoint, Dropped) and endpoint.reason == "excluded-type"


def test_the_chain_is_extensible(context):
    from aifactory_healthmodel.domain.classification import ClassificationHandler

    class DropByTag(ClassificationHandler):
        def handle(self, resource, ctx):
            if resource.tags.get("healthmodel") == "ignore":
                return Dropped(resource, "opted-out")
            return super().handle(resource, ctx)

    chain = DropByTag(default_chain())
    tagged = parse_resources([{**row("kv1", "microsoft.keyvault/vaults", PROJECT_RG), "tags": {"healthmodel": "ignore"}}])
    assert chain.handle(tagged[0], context) == Dropped(tagged[0], "opted-out")
