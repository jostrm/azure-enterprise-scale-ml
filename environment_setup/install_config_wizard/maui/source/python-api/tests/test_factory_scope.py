import json
import subprocess

from src.factory_scope import current_factory_scope
from src.operations import AzureInventoryProvider, LocalFactoryDiscovery, OperationsStore
from src import azure_auth


SUB = "612e830e-b795-424e-ba5d-cd0a5dadecf4"
TENANT = "11111111-1111-4111-8111-111111111111"
FOREIGN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"


def make_factory(root):
    (root / "variables.json").write_text(json.dumps({
        "dev": {"dev_sub_id": SUB, "tenantId": TENANT, "admin_location": "swedencentral"},
        "stage_prod": {},
    }), encoding="utf-8")
    for path in ("config-wizard/scalesets/scaleset_old.json", "config-wizard/project-017/project_state.json"):
        snapshot = root / path
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps({
            "project_number_000": "017", "tenantId": OTHER_TENANT,
            "dev_sub_id": FOREIGN, "test_sub_id": FOREIGN, "prod_sub_id": FOREIGN,
        }), encoding="utf-8")


def test_map_and_auth_use_identical_current_scope_excluding_saved_history(tmp_path):
    make_factory(tmp_path)
    scope = current_factory_scope(tmp_path)
    discovery = LocalFactoryDiscovery().discover(str(tmp_path))
    auth = azure_auth._context(str(tmp_path))
    assert scope["subscription_ids"] == discovery["subscription_ids"] == [SUB]
    assert set(discovery["subscriptions"].values()) == {SUB}
    assert auth.subscription_ids == (SUB,)
    assert auth.tenant_ids == (TENANT,)
    assert "017" in discovery["project_numbers"]  # history remains available, but not authorization scope


def test_absent_current_scope_never_borrows_subscriptions_from_project_files(tmp_path):
    make_factory(tmp_path)
    (tmp_path / "variables.json").unlink()
    assert current_factory_scope(tmp_path)["subscription_ids"] == []
    assert LocalFactoryDiscovery().discover(str(tmp_path))["subscription_ids"] == []


def test_refresh_never_reuses_broader_snapshot_and_only_calls_current_subscription(tmp_path):
    make_factory(tmp_path)
    store = OperationsStore(tmp_path / "operations.db")
    store.save_snapshot(str(tmp_path), "azure", {
        "subscriptions": [SUB, FOREIGN], "warning": f"Old error for {FOREIGN}",
        "resources": [], "resource_groups": [],
    })
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["account", "show"]:
            value = TENANT
        else:
            value = []
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")

    local = LocalFactoryDiscovery().discover(str(tmp_path))
    provider = AzureInventoryProvider(store, runner=runner)
    result = provider.get_inventory(str(tmp_path), local["subscription_ids"], False, local)
    assert result["source"] == "azure"
    assert result["subscriptions"] == [SUB]
    assert FOREIGN not in json.dumps(result)
    assert all(argv[argv.index("--subscription") + 1] == SUB for argv in calls)
    count = len(calls)
    assert provider.get_inventory(str(tmp_path), [SUB], False, local)["source"] == "cached"
    assert len(calls) == count


def test_wrong_tenant_is_detected_before_resource_queries(tmp_path):
    make_factory(tmp_path)
    store = OperationsStore(tmp_path / "operations.db")
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[1:3] == ["account", "show"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(OTHER_TENANT), "")

    local = LocalFactoryDiscovery().discover(str(tmp_path))
    result = AzureInventoryProvider(store, runner=runner).get_inventory(
        str(tmp_path), local["subscription_ids"], True, local
    )
    assert result["source"] == "unavailable"
    assert "does not match" in result["warning"]
    assert len(calls) == 1


def test_failed_refresh_does_not_fall_back_to_an_unrelated_scope(tmp_path):
    make_factory(tmp_path)
    store = OperationsStore(tmp_path / "operations.db")
    store.save_snapshot(str(tmp_path), "azure", {
        "subscriptions": [FOREIGN], "resources": [{"id": "foreign-resource"}],
        "resource_groups": [], "warning": "old wrong-tenant warning",
    })
    local = LocalFactoryDiscovery().discover(str(tmp_path))
    result = AzureInventoryProvider(store, runner=lambda argv, **kwargs:
        subprocess.CompletedProcess(argv, 1, "", "Please run az login")
    ).get_inventory(str(tmp_path), [SUB], True, local)
    assert result["source"] == "unavailable"
    assert result["resources"] == []
    assert "old wrong-tenant" not in result["warning"]
