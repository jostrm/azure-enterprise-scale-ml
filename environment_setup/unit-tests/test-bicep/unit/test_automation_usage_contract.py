"""Offline executable contracts; no Azure SDK, login, or cloud calls are needed."""

import ast
import base64
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings" / "automation" / "projectteam" / "foundry-usage" / "foundry_usage_report.py"
SUB, TENANT, OBJECT, WORKSPACE = ("11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444")


@pytest.fixture
def report(monkeypatch):
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and node.module.startswith(("azure.", "reportlab.")))]
    module = types.ModuleType("offline_automation_usage_report")
    module.__file__ = str(SCRIPT)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(tree, str(SCRIPT), "exec"), module.__dict__)
    module.HttpResponseError = type("HttpResponseError", (Exception,), {})
    return module


def args(monkeypatch, output, extra=()):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--subscription-id", SUB,
        "--resource-group", "orange-project017-weu-dev-001", "--workspace-id", WORKSPACE,
        "--automation-json", str(output), "--tenant-id", TENANT, "--expected-object-id", OBJECT,
        "--as-of-date", "2026-09-14", "--days", "2", "--output", str(output.with_suffix(".pdf")), *extra])


def test_strict_main_uses_only_selected_cli_and_emits_sparse_aggregate_json(report, monkeypatch, tmp_path):
    output = tmp_path / "report.json"
    args(monkeypatch, output)
    calls = []
    report.ScopedCliCredential = lambda *values: calls.append(values) or object()
    report.DefaultAzureCredential = lambda **kwargs: pytest.fail("No ambient/service-principal fallback")
    report.ResourceManagementClient = lambda credential, subscription: calls.append(subscription)
    report.MonitorManagementClient = lambda credential, subscription: object()
    report.LogsQueryClient = lambda credential: object()
    resource = report.Resource("/subscriptions/" + SUB + "/resourceGroups/orange-project017-weu-dev-001/providers/Microsoft.CognitiveServices/accounts/foundry",
                               "foundry", report.COGNITIVE_ACCOUNT_TYPE, "AIServices")
    report.discover_resources = lambda *values: ([resource], [], [])
    def metrics(*values, strict=False):
        assert strict is True
        return [report.MetricPoint("foundry", resource.type, "ModelRequests", "gpt-4o", "not exported",
                                   datetime(2026, 9, 13, tzinfo=timezone.utc), 4)]
    report.collect_metric_points = metrics
    def telemetry(*values, strict=False):
        assert strict is True
        return [report.TelemetryPoint("foundry", "gpt-4o", datetime(2026, 9, 13, tzinfo=timezone.utc),
                                      0, 0, 0, 0, 2)]
    report.collect_telemetry = telemetry
    report.write_pdf = lambda *values: None
    charts = []
    report.write_chart_pdf = lambda *values: charts.append(values)
    assert report.main() == 0
    document = json.loads(output.read_text())
    assert calls[0] == (SUB, TENANT, OBJECT)
    assert document["contract"] == "aifactory.aggregate-report.v1"
    assert document["workspace_id"] == WORKSPACE and document["subscription_id"] == SUB
    assert document["daily"][0]["metrics"] == {"requests": 4, "sessions": 2}
    assert charts[0][3]["Foundry"] == [4, None]
    assert charts[1][3]["Foundry"] == [None, None]
    assert "not exported" not in output.read_text()
    assert "sessionId" not in output.read_text() and "dimensions" not in output.read_text()


def token(tenant, object_id):
    encoded = base64.urlsafe_b64encode(json.dumps({"tid": tenant, "oid": object_id}).encode()).decode().rstrip("=")
    return SimpleNamespace(token=f"header.{encoded}.signature")


def test_cli_identity_checked_on_every_token_without_global_account_changes(report):
    kwargs_seen = []
    credential = SimpleNamespace(get_token=lambda *args, **kwargs: token(TENANT, OBJECT))
    report.AzureCliCredential = lambda **kwargs: kwargs_seen.append(kwargs) or credential
    scoped = report.ScopedCliCredential(SUB, TENANT, OBJECT)
    scoped.get_token("https://management.azure.com/.default")
    assert kwargs_seen == [{"subscription": SUB}]
    with pytest.raises(RuntimeError, match="tenant differs"):
        scoped.get_token("https://management.azure.com/.default", tenant_id=WORKSPACE)
    credential.get_token = lambda *args, **kwargs: token(TENANT, WORKSPACE)
    with pytest.raises(RuntimeError, match="identity changed"):
        scoped.get_token("https://api.loganalytics.io/.default")


def test_strict_query_failure_cannot_return_fake_empty_success(report):
    def failed(**kwargs):
        raise report.HttpResponseError("private response text")
    logs = SimpleNamespace(query_workspace=failed)
    resources = [report.Resource("/resource/id", "foundry", report.COGNITIVE_ACCOUNT_TYPE, "AIServices")]
    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError, match="aggregate telemetry"):
        report.collect_telemetry(logs, WORKSPACE, resources, now, now, strict=True)
    logs.query_workspace = lambda **kwargs: SimpleNamespace(status="Partial", tables=[])
    with pytest.raises(RuntimeError, match="partial"):
        report.collect_telemetry(logs, WORKSPACE, resources, now, now, strict=True)


def test_azure_query_columns_support_current_string_column_schema(report):
    now = datetime.now(timezone.utc)
    table = SimpleNamespace(columns=["Hour", "ResourceId", "Deployment", "Requests", "UniqueSessions", "ObservedSessions"],
                            rows=[[now, "/resource/id", "model", 5, 2, 1]])
    logs = SimpleNamespace(query_workspace=lambda **kwargs: SimpleNamespace(status="Success", tables=[table]))
    resource = report.Resource("/resource/id", "foundry", report.COGNITIVE_ACCOUNT_TYPE, "AIServices")
    result = report.collect_telemetry(logs, WORKSPACE, [resource], now, now, strict=True)
    assert result[0].requests == 5 and result[0].sessions == 2


def test_strict_counter_selection_excludes_alias_duplicates_rates_and_partial_counters(report):
    def definition(name, unit="Count", aggregations=("Total",)):
        return SimpleNamespace(name=SimpleNamespace(value=name), unit=unit,
                               supported_aggregation_types=list(aggregations))
    definitions = [definition(name) for name in (
        "ModelRequests", "AzureOpenAIRequests", "TotalCalls", "SuccessfulCalls", "RAIHarmfulRequests",
        "InputTokens", "ProcessedPromptTokens", "OutputTokens", "GeneratedTokens", "TotalTokens",
        "TokenTransaction", "cacheReadInputTokens", "ephemeral5mInputTokens")]
    definitions += [definition("AzureOpenAIContextTokensCacheMatchRate", "Percent"),
                    definition("TokensPerSecond", aggregations=("Average",)),
                    definition("NormalizedTimeToFirstToken", "MilliSeconds", ("Average",)),
                    definition("PerRequestComputeConsumption")]
    selected = report.select_count_metrics(definitions, report.COGNITIVE_ACCOUNT_TYPE)
    assert selected == ["ModelRequests", "InputTokens", "OutputTokens", "cacheReadInputTokens", "TotalTokens"]
    assert report.select_count_metrics(definitions, report.SEARCH_SERVICE_TYPE) == []
    fallback = report.select_count_metrics([definition("GeneratedTokens")], report.COGNITIVE_ACCOUNT_TYPE)
    assert fallback == ["GeneratedTokens"]
    point = report.MetricPoint("foundry", report.COGNITIVE_ACCOUNT_TYPE, "GeneratedTokens", "model", "",
                               datetime(2026, 9, 13, tzinfo=timezone.utc), 3)
    assert list(report.summarize_metrics([point], timezone.utc, "day", strict=True).values()) == [{"output_tokens": 3}]


def test_no_instrumented_sessions_stays_unknown_and_cached_tokens_are_not_double_counted(report):
    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    table = SimpleNamespace(columns=["Hour", "ResourceId", "Deployment", "Requests", "UniqueSessions", "ObservedSessions"],
                            rows=[[now, "/resource/id", "model", 5, 0, 0]])
    logs = SimpleNamespace(query_workspace=lambda **kwargs: SimpleNamespace(status="Success", tables=[table]))
    resource = report.Resource("/resource/id", "foundry", report.COGNITIVE_ACCOUNT_TYPE, "AIServices")
    points = report.collect_telemetry(logs, WORKSPACE, [resource], now, now, strict=True)
    assert points[0].sessions is None
    assert "sessions" not in next(iter(report.summarize_telemetry(points, timezone.utc, "day").values()))
    values = {("2026-09-13", "foundry", "model"): {"input_tokens": 100, "output_tokens": 20, "cached_tokens": 30}}
    assert report.daily_service_values(values, [resource], ["2026-09-13"], ["token_usage"], preserve_missing=True)["Foundry"] == [120]
    values[("2026-09-13", "foundry", "model")]["tokens"] = 110
    assert report.daily_service_values(values, [resource], ["2026-09-13"], ["token_usage"], preserve_missing=True)["Foundry"] == [110]


def test_sparse_charts_do_not_invent_zeroes_or_mutate_input(report):
    resource = report.Resource("/resource/id", "foundry", report.COGNITIVE_ACCOUNT_TYPE, "AIServices")
    values = {("2026-09-13", "foundry", "model"): {"requests": 0}}
    before = json.dumps({str(key): value for key, value in values.items()})
    assert report.daily_service_values(values, [resource], ["2026-09-13", "2026-09-14"],
                                      ["requests"], preserve_missing=True)["Foundry"] == [0, None]
    assert report.daily_service_values(values, [resource], ["2026-09-13"],
                                      ["token_usage"], preserve_missing=True)["Foundry"] == [None]
    assert report.daily_service_values(values, [resource], ["2026-09-13"],
                                      ["token_usage"])["Foundry"] == [0]
    assert json.dumps({str(key): value for key, value in values.items()}) == before


def test_pdf_tables_preserve_missing_categories_without_mutating_aggregate(report):
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    values = {("2026-09-14", "foundry", "model"): {"requests": 1}}
    tables = []
    report.SimpleDocTemplate = lambda *args, **kwargs: SimpleNamespace(build=lambda story: None)
    report.landscape = lambda value: value
    report.A4 = object()
    report.cm = 1
    class Styles(dict):
        def add(self, value):
            self[value["name"]] = value
    report.getSampleStyleSheet = lambda: Styles(BodyText={}, Title={}, Heading2={})
    report.ParagraphStyle = lambda **kwargs: kwargs
    report.colors = SimpleNamespace(HexColor=lambda value: value)
    report.Paragraph = lambda *args: None
    report.Spacer = lambda *args: None
    report.PageBreak = lambda: None
    report.render_table = lambda rows, widths: tables.append(rows)
    options = SimpleNamespace(resource_group="orange-project017-weu-dev-001", days=2,
                              time_zone="UTC", automation_json="aggregate.json")
    report.write_pdf(Path("unused.pdf"), values, values, options, now.date(), [], [], [], False)
    assert tables[0][1][2:] == ["1", "Unknown", "Unknown", "Unknown", "Unknown"]
    assert values == {("2026-09-14", "foundry", "model"): {"requests": 1}}


def test_automation_requires_utc_and_explicit_identity(report, monkeypatch, tmp_path):
    args(monkeypatch, tmp_path / "ignored.json", ("--time-zone", "Europe/Berlin"))
    with pytest.raises(SystemExit):
        report.parse_args()
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--subscription-id", SUB,
        "--resource-group", "orange-project017-weu-dev-001", "--automation-json", "unused.json"])
    with pytest.raises(SystemExit):
        report.parse_args()
