import pytest

from aif_lifecycle.domain.errors import InvalidId
from aif_lifecycle.domain.ids import FactoryId, ProjectId, ScalesetId, catalog_environment, parse_any, physical_environment


@pytest.mark.parametrize("text, prefix, code, env", [
    ("aif-121-sdc-dev", "aif-121", "sdc", "dev"),
    ("spider-sdc-dev", "spider", "sdc", "dev"),
    ("acme-ai-eus2-test", "acme-ai", "eus2", "test"),
    ("mrvel-1-gwc-prod", "mrvel-1", "gwc", "prod"),
])
def test_factory_id_parses_from_the_right_and_round_trips(text, prefix, code, env):
    factory = FactoryId.parse(text)
    assert (factory.prefix, factory.region_code, factory.env) == (prefix, code, env)
    assert str(factory) == text


def test_factory_id_maps_region_code_and_catalog_environment():
    factory = FactoryId.parse("spider-sdc-test")
    assert factory.region == "swedencentral"
    assert factory.catalog_env == "stage"


@pytest.mark.parametrize("text", [
    "", "sdc-dev", "aif-121-sdc", "AIF-121-sdc-dev", "aif-121-xyz-dev", "aif-121-sdc-stage",
    "aif-121-sdc-qa", "aif--121-sdc-dev", "-aif-sdc-dev", "aif_121-sdc-dev", "aif-121-sdc-dev ",
])
def test_factory_id_rejects_malformed_text(text):
    with pytest.raises(InvalidId):
        FactoryId.parse(text)


def test_scaleset_id_adds_the_resource_group_suffix_and_names_the_common_group():
    scaleset = ScalesetId.parse("aif-121-sdc-dev-001")
    assert scaleset.factory == FactoryId("aif-121", "sdc", "dev")
    assert scaleset.suffix == "001"
    assert str(scaleset) == "aif-121-sdc-dev-001"
    assert scaleset.common_resource_group == "aif-121-esml-common-sdc-dev-001"


@pytest.mark.parametrize("text", ["aif-121-sdc-dev-1", "aif-121-sdc-dev-0001", "aif-121-sdc-dev", "aif-121-sdc-dev-abc"])
def test_scaleset_id_requires_a_three_digit_suffix(text):
    with pytest.raises(InvalidId):
        ScalesetId.parse(text)


@pytest.mark.parametrize("text, prefix, number, code, env, suffix", [
    ("aif-121-esml-project001-sdc-dev-001-rg", "aif-121", "001", "sdc", "dev", "001"),
    ("spider-esml-project001-sdc-dev-001-rg", "spider", "001", "sdc", "dev", "001"),
    ("aif-113-esml-project002-sdc-dev-002-rg", "aif-113", "002", "sdc", "dev", "002"),
])
def test_project_id_is_the_project_resource_group_name(text, prefix, number, code, env, suffix):
    project = ProjectId.parse(text)
    assert project.scaleset == ScalesetId(FactoryId(prefix, code, env), suffix)
    assert project.number == number
    assert project.resource_group == text
    assert str(project) == text


def test_project_id_honors_custom_project_prefix_and_suffix():
    project = ProjectId.parse("acme-project003-weu-prod-001-prod", project_prefix="", project_suffix="-prod")
    assert project.number == "003"
    assert project.scaleset == ScalesetId.parse("acme-weu-prod-001")
    assert str(project) == "acme-project003-weu-prod-001-prod"


@pytest.mark.parametrize("text", [
    "aif-121-esml-project01-sdc-dev-001-rg", "aif-121-esml-project001-sdc-dev-001", "aif-121-project001-sdc-dev-001-rg",
    "aif-121-esml-common-sdc-dev-001", "esml-project001-sdc-dev-001-rg",
])
def test_project_id_rejects_other_resource_group_names(text):
    with pytest.raises(InvalidId):
        ProjectId.parse(text)


def test_containment_follows_factory_scaleset_project_scope():
    factory = FactoryId.parse("spider-sdc-dev")
    scaleset = ScalesetId.parse("spider-sdc-dev-001")
    project = ProjectId.parse("spider-esml-project001-sdc-dev-001-rg")
    sibling = ProjectId.parse("spider-esml-project002-sdc-dev-001-rg")
    assert factory.contains(scaleset) and factory.contains(project) and factory.contains(factory)
    assert scaleset.contains(project) and scaleset.contains(sibling)
    assert not scaleset.contains(factory)
    assert project.contains(project) and not project.contains(sibling)
    assert not FactoryId.parse("spider-sdc-test").contains(project)


@pytest.mark.parametrize("text, kind", [
    ("spider-sdc-dev", FactoryId),
    ("spider-sdc-dev-001", ScalesetId),
    ("spider-esml-project001-sdc-dev-001-rg", ProjectId),
])
def test_parse_any_recognizes_each_kind(text, kind):
    assert isinstance(parse_any(text), kind)


def test_environment_tokens_map_stage_to_test():
    assert physical_environment("stage") == "test"
    assert physical_environment("dev") == "dev"
    assert catalog_environment("test") == "stage"
    assert catalog_environment("prod") == "prod"
    with pytest.raises(InvalidId):
        physical_environment("qa")
