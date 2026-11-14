from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aifactory_healthmodel import naming
from conftest import REPO

TENANT = "11111111-1111-1111-1111-111111111111"
DEV_SUB = "22222222-2222-2222-2222-222222222222"
TEST_SUB = "33333333-3333-3333-3333-333333333333"


def payload(**dev_overrides) -> dict:
    dev = {
        "tenantId": TENANT, "dev_sub_id": DEV_SUB, "test_sub_id": "", "prod_sub_id": "",
        "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "admin_aifactoryPrefixRG": "spider-", "admin_aifactorySuffixRG": "-001",
        "projectPrefix": "esml-", "projectSuffix": "-rg", "vnetResourceGroupBase": "esml-common",
        "commonResourceGroup_param": "", "project_number_000": "001",
        "enableAISearch": "true", "enableDatabricks": "false",
    }
    dev.update(dev_overrides)
    return {"dev": dev, "stage_prod": {"tenantId": TENANT, "test_sub_id": TEST_SUB, "prod_sub_id": TEST_SUB}}


def test_resolves_ai_factory_resource_group_names_from_variables_json():
    scope = naming.from_variables(payload(), "dev", "001")
    assert scope.project_resource_group == "spider-esml-project001-sdc-dev-001-rg"
    assert scope.common_resource_group == "spider-esml-common-sdc-dev-001"
    assert scope.subscription_id == DEV_SUB and scope.tenant_id == TENANT
    assert scope.flags["enableAISearch"] is True and scope.flags["enableDatabricks"] is False


def test_stage_maps_to_test_environment_and_stage_prod_section():
    scope = naming.from_variables(payload(), "stage", "001")
    assert scope.environment == "test"
    assert scope.subscription_id == TEST_SUB
    assert scope.project_resource_group == "spider-esml-project001-sdc-test-001-rg"


def test_common_resource_group_override_supports_environment_token():
    scope = naming.from_variables(payload(commonResourceGroup_param="byo-common-<env>-rg"), "dev", "001")
    assert scope.common_resource_group == "byo-common-dev-rg"


@pytest.mark.parametrize("project", ["002", "1", ""])
def test_project_assertion_must_match_configuration(project):
    with pytest.raises(ValueError, match="project"):
        naming.from_variables(payload(), "dev", project)


@pytest.mark.parametrize("field", ["tenantId", "dev_sub_id"])
def test_placeholder_identifiers_fail_closed(field):
    with pytest.raises(ValueError, match="GUID"):
        naming.from_variables(payload(**{field: "<todo>_SubID"}), "dev", "001")


def test_unknown_environment_is_rejected():
    with pytest.raises(ValueError, match="environment"):
        naming.from_variables(payload(), "qa", "001")


def test_model_names_are_valid_unique_and_deterministic():
    scope = naming.from_variables(payload(), "dev", "001")
    project, common = scope.model_name("project"), scope.model_name("common")
    assert project == "hm-spider-prj001-sdc-dev-001"
    assert common == "hm-spider-cmn-sdc-dev-001"
    for name in (project, common):
        assert naming.MODEL_NAME_PATTERN.fullmatch(name)
    assert naming.from_variables(payload(), "dev", "001").model_name("project") == project


def test_long_prefixes_are_truncated_with_stable_hash():
    scope = naming.from_variables(payload(admin_aifactoryPrefixRG="contoso-enterprise-ai-platform-very-long-"), "dev", "001")
    name = scope.model_name("project")
    assert len(name) <= 44 and naming.MODEL_NAME_PATTERN.fullmatch(name)
    assert name == scope.model_name("project")
    other = naming.from_variables(payload(admin_aifactoryPrefixRG="contoso-enterprise-ai-platform-very-long-"), "dev", "001")
    assert other.model_name("common") != name


def test_hashed_project_model_names_differ_only_in_the_project_token():
    """The common model finds sibling project models by swapping prjNNN, so the digest must not depend on it."""
    prefix = "contoso-enterprise-aifact-"
    first = naming.from_variables(payload(admin_aifactoryPrefixRG=prefix, project_number_000="001"), "dev", "001")
    second = naming.from_variables(payload(admin_aifactoryPrefixRG=prefix, project_number_000="002"), "dev", "002")
    name1, name2 = first.model_name("project"), second.model_name("project")
    assert len(name1) <= 44 and name1 != name2
    assert name1.replace("prj001", "prj002") == name2
    other_factory = naming.from_variables(payload(admin_aifactoryPrefixRG="contoso-enterprise-aifact-x-"), "dev", "001")
    assert other_factory.model_name("project") != name1


def test_unknown_model_scope_is_rejected():
    scope = naming.from_variables(payload(), "dev", "001")
    with pytest.raises(ValueError):
        scope.model_name("factory")


def test_definitions_name_models_with_their_own_token():
    scope = naming.from_variables(payload(), "dev", "001")
    assert scope.render_token("agt{project}") == "agt001"
    assert scope.model_name_for("agt001") == "hm-spider-agt001-sdc-dev-001"
    assert scope.model_name_for(scope.render_token("prj{project}")) == scope.model_name("project")
    for bad in ("Agents", "a", "agt-{project}", "{project}", "agentsruntime{project}"):
        with pytest.raises(ValueError, match="token"):
            scope.render_token(bad)


@pytest.mark.parametrize("prefix", ["spider-", "contoso-enterprise-aifact-"])
def test_sibling_patterns_find_every_project_model_of_the_same_factory(prefix):
    scopes = [naming.from_variables(payload(admin_aifactoryPrefixRG=prefix, project_number_000=n), "dev", n)
              for n in ("001", "002")]
    pattern = scopes[0].sibling_model_pattern("prj{project}")
    assert all(pattern.fullmatch(s.model_name("project")) for s in scopes)
    assert not pattern.fullmatch(scopes[0].model_name_for("agt001"))
    assert not pattern.fullmatch(scopes[0].model_name("common"))
    assert scopes[0].sibling_model_pattern("cmn").fullmatch(scopes[1].model_name("common"))
    prod = naming.from_variables(payload(admin_aifactoryPrefixRG=prefix), "prod", "001")
    assert not pattern.fullmatch(prod.model_name("project"))


@pytest.mark.parametrize("location,expected", [
    ("swedencentral", "swedencentral"),
    ("eastus2", "centralus"),
    ("denmarkeast", "swedencentral"),
    ("westus2", "westus3"),
    ("francecentral", "westeurope"),
    ("japaneast", "japanwest"),
])
def test_health_model_region_falls_back_to_nearest_supported(location, expected):
    region, reason = naming.health_model_location(location)
    assert region == expected
    assert region in naming.SUPPORTED_REGIONS
    assert (reason == "supported") == (location == expected)
    if location != expected:
        assert "same-geography fallback" in reason


def test_unmapped_region_requires_explicit_choice():
    with pytest.raises(ValueError, match="--health-model-location"):
        naming.health_model_location("uaenorth")
    assert naming.health_model_location("uaenorth", override="westeurope")[0] == "westeurope"
    with pytest.raises(ValueError, match="not supported"):
        naming.health_model_location("uaenorth", override="uaenorth")


def test_supported_regions_can_come_from_the_live_provider():
    region, _ = naming.health_model_location("eastus2", supported={"eastus2", "centralus"})
    assert region == "eastus2"


def test_explicit_scope_without_variables_json():
    scope = naming.explicit(
        tenant_id=TENANT, subscription_id=DEV_SUB, environment="dev", project_number="001",
        location="swedencentral", location_suffix="sdc",
        project_resource_group="spider-esml-project001-sdc-dev-001-rg",
        common_resource_group="spider-esml-common-sdc-dev-001",
        resource_group_prefix="spider-", resource_group_suffix="-001",
    )
    assert scope.model_name("project") == "hm-spider-prj001-sdc-dev-001"
    assert scope.flags == {}


def _dashboard_config_class():
    import sys
    path = REPO / "environment_setup/aifactory/bicep/scripts/deploy-aifactory-dashboard.py"
    spec = importlib.util.spec_from_file_location("hm_dashboard_parity", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.Config


@pytest.mark.parametrize("environment,override", [("dev", ""), ("test", ""), ("prod", "byo-<env>-common")])
def test_resource_group_naming_matches_the_dashboard_reconciler(environment, override):
    """Guards against drift from the accelerator's existing naming implementation."""
    Config = _dashboard_config_class()
    config = Config(
        current_subscription=DEV_SUB, current_environment=environment, current_project_number="007",
        location="swedencentral", location_suffix="sdc", resource_group_prefix="acme-",
        resource_group_suffix="-002", project_prefix="esml-", project_suffix="-rg",
        common_name="esml-common", common_overrides={environment: override},
        subscriptions={"dev": DEV_SUB, "test": DEV_SUB, "prod": DEV_SUB}, central_dns=False,
        private_dns_subscription="", private_dns_resource_group="", vnet_subscription="",
        vnet_resource_group="", template_file=Path("unused.bicep"),
    )
    data = payload(admin_aifactoryPrefixRG="acme-", admin_aifactorySuffixRG="-002", project_number_000="007",
                   commonResourceGroup_param=override)
    data["stage_prod"].update({"commonResourceGroup_param": override})
    scope = naming.from_variables(data, environment, "007")
    assert scope.project_resource_group == config.current_project_resource_group
    assert scope.common_resource_group == config.common_resource_group(environment)


def test_configuration_file_reader_rejects_non_objects(tmp_path):
    path = tmp_path / "variables.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(ValueError):
        naming.read_variables(path)
