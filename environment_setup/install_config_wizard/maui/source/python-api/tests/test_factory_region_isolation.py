import json
import subprocess

import pytest

from src.factory_scope import current_factory_scope
from src.operations import AzureInventoryProvider, LocalFactoryDiscovery, OperationsService, OperationsStore


SUB = "612e830e-b795-424e-ba5d-cd0a5dadecf4"
TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_SUB = "22222222-2222-4222-8222-222222222222"
SDC_GROUP = "mrvel-1-esml-common-sdc-dev-007"
EUS_GROUP = "mrvel-1-esml-common-eus2-dev-007"


def write_factory(root, stage_region=None):
    dev = {
        "dev_sub_id": SUB, "tenantId": TENANT,
        "admin_location": "swedencentral", "admin_locationSuffix": "sdc",
        "admin_aifactoryPrefixRG": "mrvel-1-", "admin_aifactorySuffixRG": "-007",
    }
    stage = dict(dev)
    if stage_region:
        stage.update(admin_location="eastus2", admin_locationSuffix="eus2", test_sub_id=OTHER_SUB, prod_sub_id=OTHER_SUB)
    (root / "variables.json").write_text(json.dumps({"dev": dev, "stage_prod": stage}), encoding="utf-8")
    old = root / "config-wizard" / "scalesets" / "scaleset_old.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({**dev, "admin_location": "eastus2", "admin_locationSuffix": "eus2"}), encoding="utf-8")
    return LocalFactoryDiscovery().discover(str(root))


@pytest.mark.parametrize("name,expected", [
    (SDC_GROUP, True),
    ("mrvel-1-project017-sdc-dev-007", True),
    ("mrvel-1-esml-project017-sdc-test-007-rg", True),
    ("mrvel-1-esml-common-sdc-prod-007", True),
    (EUS_GROUP, False),
    ("mrvel-1-project017-eus2-dev-007", False),
    ("gh-esml-common-sdc-dev-007", False),
    ("other-mrvel-1-esml-common-sdc-dev-007", False),
    ("mrvel-11-esml-common-sdc-dev-007", False),
    ("mrvel-1-esml-common-sdc-dev-0070", False),
    ("mrvel-1-esml-common-sdc-dev-008", False),
])
def test_group_scope_distinguishes_region_prefix_and_scale_set(tmp_path, name, expected):
    local = write_factory(tmp_path)
    assert AzureInventoryProvider._is_relevant_group(name, local, SUB) is expected
    assert local["monitoring_regions"] == ["swedencentral"]


def test_stage_prod_region_and_subscription_must_match_the_same_target(tmp_path):
    local = write_factory(tmp_path, stage_region=True)
    assert AzureInventoryProvider._is_relevant_group(SDC_GROUP, local, SUB)
    assert AzureInventoryProvider._is_relevant_group("mrvel-1-esml-common-eus2-test-007", local, OTHER_SUB)
    assert not AzureInventoryProvider._is_relevant_group("mrvel-1-esml-common-eus2-test-007", local, SUB)
    assert not AzureInventoryProvider._is_relevant_group(EUS_GROUP, local, OTHER_SUB)


def test_resource_ids_are_kept_verbatim_and_other_region_never_reaches_telemetry(tmp_path):
    local = write_factory(tmp_path)
    store = OperationsStore(tmp_path / "operations.db")
    resources = [
        {
            "name": name, "resourceGroup": group, "type": "Microsoft.OperationalInsights/workspaces",
            "id": f"/subscriptions/{SUB}/resourceGroups/{group}/providers/Microsoft.OperationalInsights/workspaces/{name}",
        }
        for group, name in ((SDC_GROUP, "la-cmn-sdc-dev-x46jf-001"), (EUS_GROUP, "la-cmn-eus2-dev-s2d7r-001"))
    ]
    captured = []

    def runner(argv, **kwargs):
        command = argv[1:3]
        if command == ["account", "show"]:
            value = TENANT
        elif command == ["group", "list"]:
            value = [{"name": SDC_GROUP}, {"name": EUS_GROUP}]
        elif command == ["resource", "list"]:
            value = resources
        else:
            pytest.fail(f"Unexpected Azure query {command}")
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")

    provider = AzureInventoryProvider(store, runner=runner)
    provider._collect_telemetry = lambda items: (captured.extend(items) or {}, [])
    result = provider.get_inventory(str(tmp_path), [SUB], True, local)
    assert [item["id"] for item in captured] == [resources[0]["id"]]
    assert [item["name"] for item in result["resource_groups"]] == [SDC_GROUP]
    assert "eus2" not in json.dumps(result["resources"])
    assert result["configuration_scope"]["monitoring_regions"] == ["swedencentral"]


def test_region_change_rejects_previous_regions_cache_and_warning(tmp_path):
    local = write_factory(tmp_path)
    store = OperationsStore(tmp_path / "operations.db")
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(TENANT if argv[1] == "account" else []), "")

    provider = AzureInventoryProvider(store, runner=runner)
    provider.get_inventory(str(tmp_path), [SUB], True, local)
    initial_calls = len(calls)
    assert provider.get_inventory(str(tmp_path), [SUB], False, local)["source"] == "cached"
    assert len(calls) == initial_calls
    document = json.loads((tmp_path / "variables.json").read_text())
    for section in document.values():
        section.update(admin_location="eastus2", admin_locationSuffix="eus2")
    (tmp_path / "variables.json").write_text(json.dumps(document), encoding="utf-8")
    changed = LocalFactoryDiscovery().discover(str(tmp_path))
    result = provider.get_inventory(str(tmp_path), [SUB], False, changed)
    assert result["source"] == "azure"
    assert len(calls) > initial_calls
    assert result["configuration_scope"]["monitoring_regions"] == ["eastus2"]


def test_workspace_success_without_genai_records_shows_only_labeled_mock_usage(tmp_path):
    write_factory(tmp_path)
    store = OperationsStore(tmp_path / "operations.db")

    class Inventory:
        def get_inventory(self, *args):
            return {
                "source": "azure", "warning": None, "resources": [], "resource_groups": [],
                "telemetry": {"prompt_records": [], "successful_prompt_queries": 1},
            }

    result = OperationsService(store, inventory=Inventory()).overview(str(tmp_path))
    assert result["prompt_summary"]["record_count"] == 30
    assert result["prompt_summary"]["source"] == "mock"
    assert "Source: Mock" in result["warning"]
    assert store.query_prompt_records(str(tmp_path))["total"] == 0
    assert "permission denied" not in result["warning"].lower()


def test_snapshot_history_excludes_earlier_combined_region_counts(tmp_path):
    store = OperationsStore(tmp_path / "operations.db")
    current = {"monitoring_regions": ["swedencentral"]}
    old = {"monitoring_regions": ["eastus2", "swedencentral"]}
    for scope, count, day in ((old, 999, "01"), (current, 2, "02"), (current, 3, "03")):
        store.save_snapshot(str(tmp_path), "azure", {
            "resources": [{}] * count, "configuration_scope": scope,
        }, f"2026-09-{day}T10:00:00Z")
    charts = OperationsService(store)._charts(
        str(tmp_path), [{}] * 3, "cached", [], [], configuration_scope=current
    )
    assert charts["snapshot_history"]["values"] == [2, 3]
