import json
import subprocess

from src.operations import AzureInventoryProvider, LocalFactoryDiscovery, OperationsService, OperationsStore


SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"


def test_environment_group_references_preserve_exact_ids_subscriptions_and_tenants():
    group = "mrvel-1-project017-sdc-dev-007"
    rg_id = f"/subscriptions/{SUB}/resourceGroups/{group}"
    discovered = {"project_numbers": ["017"], "subscriptions": {"dev": SUB},
                  "subscription_tenants": {SUB: TENANT}}
    result = LocalFactoryDiscovery().annotate_with_inventory(discovered, [
        {"id": rg_id, "name": group, "location": "swedencentral", "subscriptionId": SUB}
    ], [])
    environments = result["projects"][0]["environments"]
    assert environments[0]["resource_group_refs"] == [
        {"name": group, "id": rg_id, "subscription_id": SUB, "tenant_id": TENANT}
    ]
    assert environments[0]["status"] == "active"
    assert environments[1]["resource_group_refs"] == []
    assert environments[1]["status"] == "not_deployed"


def test_common_group_reference_keeps_azure_id_and_tenant_for_scale_set_link():
    name = "mrvel-1-esml-common-sdc-dev-007"
    resource_id = f"/subscriptions/{SUB}/resourceGroups/{name}"
    result = LocalFactoryDiscovery().annotate_with_inventory(
        {"project_numbers": [], "subscriptions": {"dev": SUB}, "subscription_tenants": {SUB: TENANT}},
        [{"id": resource_id, "name": name, "location": "swedencentral", "subscriptionId": SUB}], [],
    )
    group = result["common_resource_groups"][0]
    assert group["id"] == resource_id
    assert group["subscriptionId"] == group["subscription_id"] == SUB
    assert group["tenant_id"] == TENANT


def test_inventory_completeness_does_not_confuse_telemetry_errors_with_missing_resources(tmp_path):
    store = OperationsStore(tmp_path / "operations.db")
    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs:
        subprocess.CompletedProcess(argv, 0, json.dumps([]), ""))
    provider._collect_telemetry = lambda resources: ({}, ["Telemetry query unavailable"])
    result = provider.get_inventory(str(tmp_path), [SUB], force_refresh=True)
    assert result["inventory_complete"] is True
    assert OperationsService._resource_summary([], [], result)["is_complete"] is True
    assert "Telemetry query unavailable" in result["warning"]
    cached = provider.get_inventory(str(tmp_path), [SUB])
    assert cached["inventory_complete"] is True


def test_partial_inventory_never_proves_project_not_deployed(tmp_path):
    def runner(argv, **kwargs):
        if argv[1] == "group":
            return subprocess.CompletedProcess(argv, 1, "", "AuthorizationFailed")
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    provider = AzureInventoryProvider(OperationsStore(tmp_path / "ops.db"), runner=runner)
    result = provider.get_inventory(str(tmp_path), [SUB], force_refresh=True)
    assert result["inventory_complete"] is False
    assert OperationsService._resource_summary([], [], result)["is_complete"] is False
    assert OperationsService._resource_summary([], [], {"source": "cached"})["is_complete"] is False
