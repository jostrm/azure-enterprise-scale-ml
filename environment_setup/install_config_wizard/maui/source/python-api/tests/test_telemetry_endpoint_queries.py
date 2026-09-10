import json

import pytest

from src.operations import AzureCollectionError, AzureInventoryProvider, OperationsStore, _genai_kql
from telemetry_helpers import TelemetryResponse, token_result


SUB = "612e830e-b795-424e-ba5d-cd0a5dadecf4"


def component():
    return {
        "id": f"/subscriptions/{SUB}/resourceGroups/gh-project006-eus2-dev-001/providers/Microsoft.Insights/components/app",
        "type": "Microsoft.Insights/components", "resourceGroup": "gh-project006-eus2-dev-001",
        "location": "eastus2", "properties": {"AppId": "app-id"},
    }


def test_each_query_uses_only_its_endpoint_table_namespace():
    workspace = _genai_kql()
    application = _genai_kql(application_insights=True)
    assert workspace.splitlines()[0] == "union isfuzzy=true AppDependencies, AppRequests, AppTraces"
    assert application.splitlines()[0] == "union isfuzzy=true dependencies, requests, traces"
    assert "AppDependencies" not in application
    assert 'todouble(column_ifexists("duration", customMeasurements["duration_ms"]))' in application
    assert 'todouble(column_ifexists("DurationMs", customMeasurements["duration_ms"]))' in workspace
    assert "/ 1ms" not in application
    for query in (workspace, application):
        assert "ago(30d)" in query
        assert "gen_ai.usage.input_tokens" in query
        assert "take 5000" in query
        assert "__DURATION_EXPRESSION__" not in query


def test_legacy_application_query_returns_actual_usage_instead_of_table_partial_error(tmp_path):
    def runner(argv, **kwargs):
        assert argv[argv.index("--subscription") + 1] == SUB
        assert argv[1:3] == ["account", "get-access-token"]
        assert argv[argv.index("--resource") + 1] == "https://api.applicationinsights.io"
        return token_result(argv)

    def transport(request, **kwargs):
        query = json.loads(request.data)["query"]
        assert "AppRequests" not in query
        payload = {"tables": [{
            "name": "PrimaryResult",
            "columns": [{"name": key} for key in ("operation_id", "input_tokens", "duration_ms")],
            "rows": [["actual-operation", 23, 140.0]],
        }]}
        return TelemetryResponse(request, payload)

    rows = AzureInventoryProvider(
        OperationsStore(tmp_path / "ops.db"), runner=runner, transport=transport,
    )._query_app_insights(component())
    assert len(rows) == 1
    assert rows[0]["input_tokens"] == 23
    assert rows[0]["latency_ms"] == 140
    assert rows[0]["source"] == "azure"


@pytest.mark.parametrize("code", ["NspValidationFailedError", "InsufficientAccessError", "PartialError"])
def test_real_query_errors_are_not_hidden_by_endpoint_fix(tmp_path, code):
    def runner(argv, **kwargs):
        return token_result(argv)

    def transport(request, **kwargs):
        return TelemetryResponse(request, {"error": {"code": code}, "tables": []})

    with pytest.raises(AzureCollectionError, match=code):
        AzureInventoryProvider(
            OperationsStore(tmp_path / "ops.db"), runner=runner, transport=transport,
        )._query_app_insights(component())
