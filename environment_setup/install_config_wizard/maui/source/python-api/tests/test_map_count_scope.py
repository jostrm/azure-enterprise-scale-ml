from src.operations import OperationsService


def test_saved_marker_outside_refreshed_factory_is_not_a_verified_zero():
    local = {"active_regions": ["swedencentral", "eastus2"], "monitoring_regions": ["eastus2"]}
    result = OperationsService._regions(local, [], [], [], {
        "source": "cached", "inventory_complete": True, "collected_at": "2026-09-08T20:34:31Z",
    })
    regions = {region["name"]: region for region in result}
    assert regions["swedencentral"]["factory_count"] == 1
    assert regions["swedencentral"]["count_status"] == "out_of_scope"
    assert "not confirmed zero" in regions["swedencentral"]["count_details"]
    assert regions["eastus2"]["count_status"] == "complete"
    assert regions["eastus2"]["resource_count"] == 0


def test_observed_counts_and_all_project_regions_are_retained():
    local = {"active_regions": ["swedencentral"], "monitoring_regions": ["swedencentral", "westeurope"]}
    resources = [{"location": "swedencentral"}] * 4 + [{"location": "global"}]
    projects = [{"project_number": "017", "environments": [
        {"region": "swedencentral", "regions": ["swedencentral", "westeurope"]},
        {"region": "swedencentral"},
    ]}]
    result = OperationsService._regions(local, [], resources, projects, {
        "source": "azure", "inventory_complete": True,
    })
    regions = {region["name"]: region for region in result}
    assert regions["swedencentral"]["resource_count"] == 4
    assert regions["swedencentral"]["project_count"] == regions["westeurope"]["project_count"] == 1
    assert regions["swedencentral"]["count_status"] == "complete"
    assert regions["global"]["resource_count"] == 1


def test_partial_and_unavailable_inventory_does_not_claim_zero():
    local = {"active_regions": ["swedencentral"], "monitoring_regions": ["swedencentral"]}
    for source, expected in (("azure", "partial"), ("unavailable", "not_collected")):
        region = next(region for region in OperationsService._regions(local, [], [], [], {
            "source": source, "inventory_complete": False,
        }) if region["name"] == "swedencentral")
        assert region["count_status"] == expected
