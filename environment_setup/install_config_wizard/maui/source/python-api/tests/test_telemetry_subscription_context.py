import json
import subprocess

import pytest

from src.operations import AzureCollectionError, AzureInventoryProvider, OperationsStore
from telemetry_helpers import TelemetryResponse, tables, token_result


SUB = "612e830e-b795-424e-ba5d-cd0a5dadecf4"
OTHER_SUB = "11111111-1111-4111-8111-111111111111"


def resource(kind, subscription=SUB):
    return {
        "id": f"/subscriptions/{subscription}/resourceGroups/factory-common-dev/providers/{kind}/test",
        "subscriptionId": subscription,
        "name": "test",
        "resourceGroup": "factory-common-dev",
        "location": "swedencentral",
        "type": kind,
    }


def response(argv, value, error=None):
    return subprocess.CompletedProcess(argv, 1 if error else 0, json.dumps(value), error or "")


@pytest.fixture
def store(tmp_path):
    return OperationsStore(tmp_path / "operations.db")


def test_workspace_token_and_http_use_resource_subscription_not_cli_default(store):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[argv.index("--subscription") + 1] == SUB
        assert kwargs["shell"] is False
        assert argv[1:3] == ["account", "get-access-token"]
        assert argv[argv.index("--resource") + 1] == "https://api.loganalytics.io"
        return token_result(argv)

    def transport(request, **kwargs):
        assert request.full_url == "https://api.loganalytics.io/v1/workspaces/workspace-guid/query"
        query = json.loads(request.data)["query"]
        assert query.splitlines()[0] == "union isfuzzy=true AppDependencies, AppRequests, AppTraces"
        return TelemetryResponse(request, tables())

    provider = AzureInventoryProvider(store, runner=runner, transport=transport)
    assert provider._query_workspace("workspace-guid", resource("Microsoft.OperationalInsights/workspaces")) == []
    assert len(calls) == 1
    assert not any(argv[1:3] == ["account", "set"] for argv in calls)


def test_workspace_metadata_lookup_uses_the_same_subscription(store):
    def runner(argv, **kwargs):
        assert argv[argv.index("--subscription") + 1] == SUB
        assert argv[1:5] == ["monitor", "log-analytics", "workspace", "show"]
        return response(argv, {"customerId": "workspace-guid"})

    provider = AzureInventoryProvider(store, runner=runner)
    assert provider._workspace_customer_id(resource("Microsoft.OperationalInsights/workspaces")) == "workspace-guid"


def test_app_insights_lookup_and_data_plane_query_use_resource_subscription_and_audience(store):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[argv.index("--subscription") + 1] == SUB
        if argv[1:3] == ["resource", "show"]:
            return response(argv, {"properties": {"AppId": "app-guid"}})
        assert argv[1:3] == ["account", "get-access-token"]
        assert argv[argv.index("--resource") + 1] == "https://api.applicationinsights.io"
        return token_result(argv)

    def transport(request, **kwargs):
        query = json.loads(request.data)["query"]
        assert query.splitlines()[0] == "union isfuzzy=true dependencies, requests, traces"
        assert all(table not in query for table in ("AppDependencies", "AppRequests", "AppTraces"))
        assert 'todouble(column_ifexists("duration", customMeasurements["duration_ms"]))' in query
        return TelemetryResponse(request, tables())

    assert AzureInventoryProvider(store, runner=runner, transport=transport)._query_app_insights(
        resource("Microsoft.Insights/components")
    ) == []
    assert len(calls) == 2


def test_cognitive_definition_and_metrics_requests_are_both_subscription_scoped(store):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[argv.index("--subscription") + 1] == SUB
        if argv[3] == "list-definitions":
            return response(argv, [{"name": {"value": "AzureOpenAIRequests"}}])
        assert argv[3] == "list"
        return response(argv, {"value": []})

    assert AzureInventoryProvider(store, runner=runner)._query_cognitive_metrics(
        resource("Microsoft.CognitiveServices/accounts")
    ) == []
    assert len(calls) == 2


def test_each_resource_keeps_its_own_subscription_without_mutating_global_cli(store):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return token_result(argv)

    provider = AzureInventoryProvider(
        store, runner=runner, transport=lambda request, **kwargs: TelemetryResponse(request, tables()),
    )
    for subscription in (SUB, OTHER_SUB):
        workspace = resource("Microsoft.OperationalInsights/workspaces", subscription)
        workspace.pop("subscriptionId")
        provider._query_workspace("workspace-guid", workspace)
    assert [argv[argv.index("--subscription") + 1] for argv in calls] == [SUB, OTHER_SUB]


@pytest.mark.parametrize("metadata", [{}, {"subscriptionId": "--unexpected"},
    {"id": f"/subscriptions/{SUB}/resourceGroups/x", "subscriptionId": OTHER_SUB}])
def test_missing_or_conflicting_subscription_does_not_fall_back_to_default_account(store, metadata):
    def forbidden(*args, **kwargs):
        pytest.fail("No CLI query may be sent without a trustworthy resource subscription.")

    with pytest.raises(AzureCollectionError):
        AzureInventoryProvider(store, runner=forbidden)._query_workspace("workspace-guid", metadata)


def test_pre_fix_cache_cannot_resurrect_wrong_tenant_permission_errors(store, tmp_path):
    old_scope = {
        "subscriptions": [SUB], "subscription_tenants": {}, "tenant_ids": [], "prefix": "", "suffix": "",
    }
    store.save_snapshot(str(tmp_path), "azure", {
        "source": "azure", "configuration_scope": old_scope,
        "subscriptions": [SUB], "resource_groups": [], "resources": [],
        "warning": "Cached default-tenant permission denied",
    })
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[argv.index("--subscription") + 1] == SUB
        return response(argv, [])

    result = AzureInventoryProvider(store, runner=runner).get_inventory(str(tmp_path), [SUB])
    assert result["source"] == "azure"
    assert result["warning"] is None
    assert len(calls) == 2
    assert result["configuration_scope"]["telemetry_auth_scope"] == "explicit-token-https-v3"


def test_workspace_link_discovered_after_arm_expansion_reuses_successful_query(store):
    workspace = resource("Microsoft.OperationalInsights/workspaces")
    workspace["properties"] = {"customerId": "workspace-guid"}
    component = resource("Microsoft.Insights/components")
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        assert argv[argv.index("--subscription") + 1] == SUB
        if argv[1:3] == ["resource", "show"]:
            return response(argv, {"properties": {"AppId": "app-guid", "WorkspaceResourceId": workspace["id"]}})
        assert argv[1:3] == ["account", "get-access-token"]
        assert argv[argv.index("--resource") + 1] == "https://api.loganalytics.io"
        return token_result(argv)

    telemetry, warnings = AzureInventoryProvider(
        store, runner=runner, transport=lambda request, **kwargs: TelemetryResponse(request, tables()),
    )._collect_telemetry([workspace, component])
    assert warnings == []
    assert telemetry["prompt_records"] == []
    assert len(calls) == 2
    assert not any("api.applicationinsights.io" in " ".join(argv) for argv in calls)


def test_failed_workspace_query_still_allows_scoped_application_insights_fallback(store):
    workspace = resource("Microsoft.OperationalInsights/workspaces")
    workspace["properties"] = {"customerId": "workspace-guid"}
    component = resource("Microsoft.Insights/components")

    def runner(argv, **kwargs):
        assert argv[argv.index("--subscription") + 1] == SUB
        if argv[1:3] == ["resource", "show"]:
            return response(argv, {"properties": {"AppId": "app-guid", "WorkspaceResourceId": workspace["id"]}})
        assert argv[1:3] == ["account", "get-access-token"]
        return token_result(argv)

    calls = []

    def transport(request, **kwargs):
        calls.append(request.full_url)
        if "api.applicationinsights.io" in request.full_url:
            return TelemetryResponse(request, tables({"operation_id": "readable-app", "input_tokens": 10}))
        return TelemetryResponse(request, {"error": {"code": "NspValidationFailedError"}}, status=403)

    telemetry, warnings = AzureInventoryProvider(
        store, runner=runner, transport=transport,
    )._collect_telemetry([workspace, component])
    assert telemetry["prompt_records"][0]["operation_id"] == "readable-app"
    assert len(warnings) == 1
    assert "network policy" in warnings[0]
    assert len(calls) == 2
