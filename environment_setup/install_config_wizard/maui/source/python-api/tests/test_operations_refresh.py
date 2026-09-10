import json
import subprocess

import pytest

from src.operations import AzureCollectionError, AzureInventoryProvider, OperationsService, OperationsStore
from telemetry_helpers import TelemetryResponse, tables, token_result


@pytest.fixture
def store(tmp_path):
    return OperationsStore(tmp_path / "operations.db")


def component(name, **properties):
    return {
        "id": f"/subscriptions/sub/resourceGroups/demo-project001-dev/providers/Microsoft.Insights/components/{name}",
        "name": name, "resourceGroup": "demo-project001-dev",
        "type": "Microsoft.Insights/components", "location": "eastus2",
        "properties": properties,
    }


def result(argv, payload=None, error=None):
    return subprocess.CompletedProcess(
        argv, 1 if error else 0,
        stdout=json.dumps(payload), stderr=error or "",
    )


def test_expired_login_is_distinct_from_missing_reader_permission(store, tmp_path):
    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: result(
        argv, error="AADSTS70043: The refresh token has expired. Interactive authentication is needed."
    ))
    inventory = provider.get_inventory(str(tmp_path), ["expired-sub"], force_refresh=True)
    assert inventory["source"] == "unavailable"
    assert "sign-in has expired" in inventory["warning"]
    assert "expired-sub" in inventory["warning"]
    assert "Reader" not in inventory["warning"]


def test_component_permission_failure_retains_inventory_other_telemetry_and_cached_warning(store, tmp_path):
    denied = component("denied")
    readable = component("readable", AppId="readable-app")
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["group", "list"]:
            return result(argv, [{"name": denied["resourceGroup"]}])
        if argv[1:3] == ["resource", "list"]:
            return result(argv, [denied, readable])
        if argv[1:3] == ["resource", "show"]:
            return result(argv, error=(
                "AuthorizationFailed: client does not have authorization to perform action "
                f"'Microsoft.Insights/components/read' over scope '{denied['id']}'"
            ))
        assert argv[1:3] == ["account", "get-access-token"]
        return token_result(argv)

    provider = AzureInventoryProvider(store, runner=runner, transport=lambda request, **kwargs: TelemetryResponse(
        request, tables({"operation_id": "live", "input_tokens": 12}),
    ))
    first = provider.get_inventory(str(tmp_path), ["sub"], force_refresh=True)

    assert first["source"] == "azure"
    assert len(first["resources"]) == 2
    assert first["telemetry"]["prompt_records"][0]["operation_id"] == "live"
    assert "Microsoft.Insights/components/read" in first["warning"]
    assert denied["id"] in first["warning"]
    assert "Reader on the affected resource only" in first["warning"]
    assert "client does not have authorization" in first["telemetry"]["collection_errors"][0]["detail"]
    original_calls = len(calls)

    cached = provider.get_inventory(str(tmp_path), ["sub"])

    assert len(calls) == original_calls
    assert cached["source"] == "cached"
    assert first["warning"] in cached["warning"]
    assert cached["telemetry"]["prompt_records"][0]["source"] == "cached"
    assert first["telemetry"]["prompt_records"][0]["source"] == "azure"
    provider.get_inventory(str(tmp_path), ["sub"], force_refresh=True)
    assert len(calls) == original_calls * 2


def test_workspace_network_denial_does_not_skip_linked_accessible_component(store, tmp_path):
    workspace_id = "/subscriptions/sub/resourceGroups/demo-project001-dev/providers/Microsoft.OperationalInsights/workspaces/logs"
    workspace = {
        "id": workspace_id, "name": "logs",
        "resourceGroup": "demo-project001-dev",
        "type": "Microsoft.OperationalInsights/workspaces",
        "properties": {"customerId": "workspace"},
    }
    app = component("readable", AppId="app", WorkspaceResourceId=workspace_id)

    def runner(argv, **kwargs):
        if argv[1:3] == ["group", "list"]:
            return result(argv, [])
        if argv[1:3] == ["resource", "list"]:
            return result(argv, [workspace, app])
        assert argv[1:3] == ["account", "get-access-token"]
        return token_result(argv)

    calls = []

    def transport(request, **kwargs):
        calls.append(request.full_url)
        if "api.applicationinsights.io" in request.full_url:
            return TelemetryResponse(request, tables({"operation_id": "from-app", "input_tokens": 15}))
        return TelemetryResponse(request, {"error": {"code": "NspValidationFailedError"}}, status=403)

    inventory = AzureInventoryProvider(store, runner=runner, transport=transport).get_inventory(
        str(tmp_path), ["sub"], force_refresh=True
    )

    assert inventory["telemetry"]["prompt_records"][0]["operation_id"] == "from-app"
    assert "workspace network policy denied" in inventory["warning"]
    assert "Reader" not in inventory["warning"]
    assert workspace_id in inventory["warning"]
    assert len(calls) == 2


def test_partial_inventory_failure_does_not_discard_accessible_resources(store, tmp_path):
    resource = component("readable", AppId="app")

    def runner(argv, **kwargs):
        if argv[1:3] == ["group", "list"]:
            return result(argv, error="AuthorizationFailed: group listing denied")
        if argv[1:3] == ["resource", "list"]:
            return result(argv, [resource])
        return token_result(argv)

    inventory = AzureInventoryProvider(
        store, runner=runner, transport=lambda request, **kwargs: TelemetryResponse(request, tables()),
    ).get_inventory(
        str(tmp_path), ["sub"], force_refresh=True,
        factory={"prefix_rg": "demo", "project_numbers": ["001"]},
    )

    assert inventory["resources"] == [resource | {"subscriptionId": "sub"}]
    assert "inventory collection is incomplete" in inventory["warning"]


def test_unexpected_programming_error_is_not_reported_as_azure_permission_failure(store, tmp_path, monkeypatch):
    provider = AzureInventoryProvider(store, runner=lambda argv, **kwargs: result(argv, []))

    def broken(_resources):
        raise RuntimeError("programming defect")

    monkeypatch.setattr(provider, "_collect_telemetry", broken)
    with pytest.raises(RuntimeError, match="programming defect"):
        provider.get_inventory(str(tmp_path), ["sub"], force_refresh=True)


@pytest.mark.parametrize("payload", [
    {"error": {"code": "InsufficientAccessError"}},
    {"error": {"code": "PartialError"}, "tables": []},
    {"unexpected": []},
    None,
])
def test_failed_query_payload_is_not_treated_as_successful_empty_telemetry(payload):
    with pytest.raises(AzureCollectionError):
        AzureInventoryProvider._tabular_rows(payload)


def make_service(store, inventory):
    class Inventory:
        def get_inventory(self, *args):
            return inventory

    return OperationsService(store=store, inventory=Inventory())


def test_failed_telemetry_uses_explicit_mock_prompts_without_replacing_inventory(store, tmp_path):
    service = make_service(store, {
        "source": "azure", "resource_groups": [], "resources": [component("denied")],
        "warning": "Permission denied: Microsoft.Insights/components/read",
        "telemetry": {"prompt_records": []},
    })

    overview = service.overview(str(tmp_path))

    assert overview["resource_inventory"]["resource_count"] == 1
    assert overview["prompt_summary"]["source"] == "mock"
    assert overview["prompt_summary"]["record_count"] == 30
    assert overview["monitoring"]["tokens_over_time"]["source"] == "mock"
    assert overview["source"] == "mixed"
    assert "Source: Mock" in overview["warning"]
    assert "Permission denied" in overview["warning"]
    assert store.query_prompt_records(str(tmp_path))["total"] == 0


def test_cached_prompt_rows_and_charts_are_not_labeled_azure_live(store, tmp_path):
    store.upsert_prompt_records(str(tmp_path), [{
        "operation_id": "prior", "timestamp": "2026-09-01T10:00:00Z",
        "source": "azure", "input_tokens": 40,
    }])
    service = make_service(store, {
        "source": "cached", "resource_groups": [], "resources": [],
        "warning": "Refresh failed", "telemetry": {},
    })

    overview = service.overview(str(tmp_path))

    assert overview["prompt_summary"]["source"] == "cached"
    assert overview["monitoring"]["tokens_over_time"]["source"] == "cached"
    assert overview["source"] == "mixed"
    assert overview["monitoring"]["resources_by_service_type"]["source"] == "mock"
    assert overview["prompt_summary"]["input_tokens"] == 40


def test_fresh_and_stored_prompt_rows_are_labeled_mixed(store, tmp_path):
    records = [
        {"operation_id": "prior", "source": "azure", "input_tokens": 10},
        {"operation_id": "current", "source": "azure", "input_tokens": 20},
    ]
    store.upsert_prompt_records(str(tmp_path), records)
    service = make_service(store, {
        "source": "azure", "resource_groups": [], "resources": [],
        "telemetry": {"prompt_records": [records[1]]},
    })

    overview = service.overview(str(tmp_path))

    assert overview["prompt_summary"]["source"] == "mixed"
    assert overview["monitoring"]["tokens_over_time"]["source"] == "mixed"


def test_metrics_only_preserve_real_values_while_missing_details_are_mock(store, tmp_path):
    service = make_service(store, {
        "source": "azure", "resource_groups": [], "resources": [],
        "telemetry": {
            "prompt_records": [],
            "cognitive_metric_points": [{
                "timestamp": "2026-09-01T10:00:00Z",
                "metric": "Requests", "value": 7,
            }],
        },
    })

    overview = service.overview(str(tmp_path))

    assert overview["prompt_summary"]["source"] == "mock"
    assert overview["monitoring"]["requests_over_time"]["source"] == "azure"
    assert overview["monitoring"]["requests_over_time"]["values"] == [7]
    assert overview["monitoring"]["latency_trend"]["source"] == "mock"
    assert overview["monitoring"]["success_error_rate"]["source"] == "mock"
    assert store.query_prompt_records(str(tmp_path))["total"] == 0


def test_total_inventory_failure_uses_mock_charts_but_no_fake_deployment_evidence(store, tmp_path):
    def runner(argv, **kwargs):
        return result(argv, error="AuthorizationFailed: no access")

    service = OperationsService(store=store, inventory=AzureInventoryProvider(store, runner=runner))
    overview = service.overview(str(tmp_path), force_refresh=True)

    assert overview["resource_inventory"]["source"] == "unavailable"
    assert overview["resource_inventory"]["resources"] == []
    assert overview["prompt_summary"]["source"] == "mock"
    assert overview["source"] == "mock"
    assert overview["monitoring"]["resources_by_service_type"]["source"] == "mock"
    assert overview["monitoring"]["resources_by_service_type"]["values"]
    assert overview["common_resource_groups"] == []
    assert all(region["resource_count"] == 0 for region in overview["regions"])
    assert overview["monitoring"]["snapshot_history"]["values"] == []
