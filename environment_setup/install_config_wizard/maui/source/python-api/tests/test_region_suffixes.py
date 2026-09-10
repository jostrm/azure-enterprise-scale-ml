import pytest

from src import api, factory_configuration, wizard


def test_schema_exposes_tkinter_suffixes_without_a_second_mapping():
    options = api.schema()["options"]
    expected = {region: suffix for _, region, suffix in wizard.PageScaleSet.REGIONS}
    assert options["azure_region_suffixes"] == expected
    assert options["azure_region_suffixes"]["swedencentral"] == "sdc"
    assert options["azure_region_suffixes"]["westeurope"] == "weu"
    assert options["azure_region_suffixes"]["eastus2"] == "eus2"
    assert options["azure_regions"] == sorted(set(options["azure_regions"]))


@pytest.mark.parametrize("region,suffix", [("swedencentral", "sdc"), ("westeurope", "weu"), ("eastus2", "eus2")])
def test_new_factory_region_prepopulates_same_default_suffix(region, suffix):
    state, *_ = factory_configuration._prepare_state("factory", region)
    assert state["admin_location"] == region
    assert state["admin_locationSuffix"] == suffix


def test_catalog_region_without_tkinter_abbreviation_requires_manual_suffix():
    state, *_ = factory_configuration._prepare_state("factory", "austriaeast")
    assert state["admin_locationSuffix"] == ""
