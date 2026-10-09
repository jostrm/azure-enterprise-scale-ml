"""Offline contract tests for the read-only, aggregate-only dashboard snapshot."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "environment_setup" / "aifactory" / "bicep" / "scripts" / "dashboard_usage.py"
)
spec = importlib.util.spec_from_file_location("dashboard_usage", SCRIPT)
usage = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = usage
spec.loader.exec_module(usage)

SUB = "11111111-1111-4111-8111-111111111111"
OTHER_SUB = "22222222-2222-4222-8222-222222222222"
RG = f"/subscriptions/{SUB}/resourceGroups/project-rg"
NOW = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)


def response(value=None, *, error=False):
    return subprocess.CompletedProcess(
        [], 1 if error else 0, json.dumps(value),
        "secret-token private-person@example.com" if error else "",
    )


def resource(resource_type, name="resource", *, group=RG, **extra):
    return {"id": f"{group}/providers/{resource_type}/{name}", "type": resource_type, "name": name, **extra}


def event(identifier="event-1", caller="private-person@example.com", **extra):
    return {
        "eventDataId": identifier, "caller": caller, "claims": {"idtyp": "user"},
        "resourceId": RG + "/providers/Microsoft.Storage/storageAccounts/store",
        "resourceGroupName": "project-rg", "eventTimestamp": "2026-10-07T20:00:00Z",
        **extra,
    }


class Azure:
    def __init__(self, resources=(), handler=None):
        self.resources = list(resources)
        self.handler = handler
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        assert usage.is_read_command(args), args
        assert args[args.index("--subscription") + 1] == SUB
        if args[:2] == ("resource", "list"):
            assert args[args.index("--resource-group") + 1].lower() == "project-rg"
            return response(self.resources)
        if self.handler:
            result = self.handler(args)
            if result is not None:
                return result
        if args[:2] == ("resource", "show"):
            identifier = args[args.index("--ids") + 1]
            if "/microsoft.search/searchservices/" in identifier.lower():
                assert args[args.index("--api-version") + 1] == "2025-05-01"
                return response({
                    "id": identifier,
                    "properties": {"endpoint": f"https://{identifier.split('/')[-1].lower()}.search.windows.net"},
                })
        if "eventtypes/management/values" in args[args.index("--url") + 1]:
            return response({"value": []})
        raise AssertionError(f"Unexpected read command: {args[:2]}")


def url_of(args):
    return args[args.index("--url") + 1] if "--url" in args else ""


def test_empty_resource_group_is_not_deployed_but_empty_activity_is_zero():
    az = Azure()
    result = usage.Collector(az, NOW).collect(RG)
    assert result["observedAt"] == result["windowEnd"] == "2026-10-08T20:00:00Z"
    assert result["windowStart"] == "2026-09-08T20:00:00Z"
    assert result["metrics"]["activity"]["value"] == 0
    assert result["metrics"]["activity"]["status"] == "ok"
    for key in ("agents", "models", "storage", "adf", "search"):
        assert result["metrics"][key]["status"] == "not-deployed"
        assert result["metrics"][key]["value"] is None
    assert len(az.calls) == 2


def test_snapshot_is_cached_by_case_insensitive_rg_without_exposing_mutable_cache():
    az = Azure()
    collector = usage.Collector(az, NOW)
    first = collector.collect(RG)
    first["metrics"]["activity"]["value"] = 999
    assert collector.collect(RG.upper())["metrics"]["activity"]["value"] == 0
    assert len(az.calls) == 2


@pytest.mark.parametrize("invalid", [None, {}, ["not-a-resource"], [{"id": RG}], [
    resource("Microsoft.Storage/storageAccounts", group=RG + "-foreign")
]])
def test_malformed_discovery_does_not_become_zero_or_break_activity(invalid):
    def az(*args):
        if args[:2] == ("resource", "list"):
            return response(invalid)
        return response({"value": [event()]})
    result = usage.Collector(az, NOW).collect(RG)["metrics"]
    assert result["activity"]["value"] == 1
    assert all(result[key]["status"] == "unavailable" for key in result if key != "activity")


def test_denied_discovery_and_activity_hide_raw_errors(capsys):
    result = usage.Collector(lambda *args: response(error=True), NOW).collect(RG)
    assert all(value["status"] == "unavailable" for value in result["metrics"].values())
    text = json.dumps(result) + str(capsys.readouterr())
    assert "secret-token" not in text
    assert "private-person" not in text


def test_activity_counts_email_events_not_unique_operations_or_callers():
    events = [
        event("one"), event("two"), event("one"),
        event("app", claims={"idtyp": "app"}),
        event("app-uri", claims={"http://schemas.microsoft.com/identity/claims/idtyp": "app"}),
        event("mi", claims={"xms_mirid": "/subscriptions/managed-identity"}),
        event("system", caller="Microsoft.Insights"),
        event("object-id", caller=SUB),
        event("old", eventTimestamp="2026-09-01T00:00:00Z"),
        event("foreign", resourceId=RG + "-foreign/providers/Microsoft.Storage/storageAccounts/x",
              resourceGroupName="project-rg-foreign"),
    ]
    az = Azure(handler=lambda args: response({"value": events}))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["value"] == 2
    assert "email" in metric["detail"].lower()
    assert "human" not in metric["detail"].lower()


@pytest.mark.parametrize("caller", [None, ""])
def test_activity_without_an_email_caller_is_excluded_not_an_unknown_user(caller):
    az = Azure(handler=lambda args: response({"value": [
        event("user"), event("system", caller=caller, claims=None),
    ]}))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "ok"
    assert metric["value"] == 1
    assert metric["unclassifiedEvents"] == 0


def test_activity_paginates_and_deduplicates_event_ids():
    def handler(args):
        url = url_of(args)
        if "$skiptoken=" in url:
            return response({"value": [event("two"), event("one")]})
        return response({"value": [event("one")], "nextLink": url + "&$skiptoken=next"})
    az = Azure(handler=handler)
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]["value"] == 2
    assert len(az.calls) == 3


@pytest.mark.parametrize("continuation", [
    lambda url: url,
    lambda url: url.replace("management.azure.com", "attacker.example"),
    lambda url: url.replace(SUB, OTHER_SUB),
    lambda url: url.replace("eventtypes/management/values", "listKeys"),
    lambda url: url.replace("project-rg", "foreign-rg"),
])
def test_activity_rejects_cycles_foreign_paths_or_changed_scope(continuation):
    az = Azure(handler=lambda args: response({
        "value": [event()], "nextLink": continuation(url_of(args)),
    }))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["value"] is None
    assert metric["status"] == "unavailable"
    assert len(az.calls) == 2


@pytest.mark.parametrize("bound", ["MAX_PAGES", "MAX_ROWS"])
def test_activity_exhausting_bounds_is_unavailable(monkeypatch, bound):
    monkeypatch.setattr(usage, bound, 1)
    az = Azure(handler=lambda args: response({
        "value": [event("one"), event("two")],
        "nextLink": url_of(args) + "&$skiptoken=next",
    }))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None
    assert "incomplete" in metric["detail"].lower()


def test_invalid_group_and_naive_clock_are_rejected_before_reads():
    az = Azure()
    with pytest.raises(ValueError):
        usage.Collector(az, datetime(2026, 10, 8))
    collector = usage.Collector(az, NOW)
    for group in ("", RG + "/providers/Microsoft.Storage/storageAccounts/store", RG + "?x=x"):
        with pytest.raises(ValueError):
            collector.collect(group)
    assert az.calls == []


@pytest.mark.parametrize("args", [
    ("rest", "--method", "post", "--url", "https://management.azure.com/a"),
    ("rest", "--method", "get", "--url", "https://attacker.example", "--subscription", SUB),
    ("resource", "list", "--resource-group", "project-rg"),
    ("resource", "delete", "--ids", RG, "--subscription", SUB),
    ("account", "get-access-token", "--subscription", SUB),
    ("monitor", "activity-log", "list", "--subscription", SUB),
])
def test_boundary_rejects_unknown_or_unscoped_commands(args):
    assert not usage.is_read_command(args)


def monitor_metric(name, data, *, unit="Bytes", dimensions=None):
    return {
        "name": {"value": name}, "unit": unit,
        "timeseries": [{"metadatavalues": dimensions or [], "data": data}],
    }


def storage_handler(args):
    url = url_of(args)
    if "/metrics?" in url:
        query = parse_qs(urlsplit(url).query)
        assert query["aggregation"] == ["Average"]
        assert query["metricnames"] == ["UsedCapacity"]
        return response({"value": [monitor_metric("UsedCapacity", [
            {"timeStamp": "2026-10-07T18:00:00Z", "average": 900},
            {"timeStamp": "2026-10-08T18:00:00Z", "average": 10},
            {"timeStamp": "2026-10-08T19:00:00Z", "average": None},
        ])]})


def test_storage_sums_latest_valid_samples_across_every_account_not_over_time():
    resources = [resource("Microsoft.Storage/storageAccounts", f"store{i}") for i in range(3)]
    az = Azure(resources, storage_handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["storage"]
    assert metric["status"] == "ok"
    assert metric["value"] == 30
    assert metric["unit"] == "Bytes"
    assert metric["oldestSampleAt"] == "2026-10-08T18:00:00Z"
    assert metric["resourceCount"] == 3
    assert len([args for args in az.calls if "/metrics?" in url_of(args)]) == 3


@pytest.mark.parametrize("payload", [
    {}, {"value": []},
    {"value": [monitor_metric("UsedCapacity", [])]},
    {"value": [monitor_metric("UsedCapacity", [{"timeStamp": "2026-10-08T19:00:00Z"}])]},
    {"value": [monitor_metric("UsedCapacity", [{"timeStamp": "2026-10-08T19:00:00Z", "average": None}])]},
    {"value": [monitor_metric("UsedCapacity", [{"timeStamp": "2026-09-01T19:00:00Z", "average": 7}])]},
    {"value": [monitor_metric("UsedCapacity", [{"timeStamp": "2026-10-08T19:00:00Z", "average": -1}])]},
    {"value": [monitor_metric("UsedCapacity", [{"timeStamp": "2026-10-08T19:00:00Z", "average": True}])]},
    {"value": [monitor_metric("UsedCapacity", [{"timeStamp": "2026-10-08T19:00:00Z", "average": 2}], unit="Count")]},
])
def test_storage_missing_invalid_or_stale_samples_are_not_zero(payload):
    az = Azure([resource("Microsoft.Storage/storageAccounts")], lambda args: (
        response(payload) if "/metrics?" in url_of(args) else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["storage"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_storage_explicit_zero_is_valid():
    az = Azure([resource("Microsoft.Storage/storageAccounts")], lambda args: (
        response({"value": [monitor_metric("UsedCapacity", [
            {"timeStamp": "2026-10-08T19:00:00Z", "average": 0},
        ])]}) if "/metrics?" in url_of(args) else None
    ))
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["storage"]["value"] == 0


def test_storage_partial_accounts_cannot_be_misrepresented_as_total():
    resources = [resource("Microsoft.Storage/storageAccounts", name) for name in ("store1", "store2")]
    az = Azure(resources, lambda args: (
        response(error=True) if "/storageAccounts/store2/" in url_of(args) else storage_handler(args)
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["storage"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_adf_counts_all_completed_states_and_factories():
    def handler(args):
        url = url_of(args)
        if "/metrics?" not in url:
            return None
        query = parse_qs(urlsplit(url).query)
        assert query["aggregation"] == ["Total"]
        assert query["interval"] == ["FULL"]
        assert set(query["metricnames"][0].split(",")) == {
            "PipelineSucceededRuns", "PipelineFailedRuns", "PipelineCancelledRuns",
        }
        assert query["timespan"] == ["2026-09-08T20:00:00Z/2026-10-08T20:00:00Z"]
        return response({"value": [
            monitor_metric(name, [
                {"timeStamp": "2026-09-08T20:00:00Z", "total": 1},
                {"timeStamp": "2026-09-09T20:00:00Z", "total": 2},
            ], unit="Count") for name in query["metricnames"][0].split(",")
        ]})
    az = Azure([resource("Microsoft.DataFactory/factories", name) for name in ("one", "two")], handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["adf"]
    assert metric["status"] == "ok"
    assert metric["value"] == 18


@pytest.mark.parametrize("values", [[], [
    monitor_metric("PipelineSucceededRuns", [{"timeStamp": "2026-10-07T20:00:00Z", "total": 0}], unit="Count")
], [
    monitor_metric(name, [], unit="Count")
    for name in ("PipelineSucceededRuns", "PipelineFailedRuns", "PipelineCancelledRuns")
]])
def test_adf_missing_states_or_empty_samples_are_unavailable(values):
    az = Azure([resource("Microsoft.DataFactory/factories")], lambda args: (
        response({"value": values}) if "/metrics?" in url_of(args) else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["adf"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_boundary_rejects_subscription_mismatch_extra_flags_and_writes():
    az = Azure([resource("Microsoft.Storage/storageAccounts")], storage_handler)
    usage.Collector(az, NOW).collect(RG)
    command = next(args for args in az.calls if "/metrics?" in url_of(args))
    assert usage.is_read_command(command)
    assert not usage.is_read_command((*command, "--headers", "Authorization=secret"))
    assert not usage.is_read_command((*command, "--subscription", SUB))
    changed = list(command)
    changed[changed.index("--subscription") + 1] = OTHER_SUB
    assert not usage.is_read_command(changed)
    changed = list(command)
    changed[changed.index("--method") + 1] = "post"
    assert not usage.is_read_command(changed)


def test_timeout_is_sanitized_without_retry_and_cached(capsys):
    def az(*args):
        raise subprocess.TimeoutExpired(["secret-command"], 90, output="private-payload")
    collector = usage.Collector(az, NOW)
    result = collector.collect(RG)
    assert all(metric["status"] == "unavailable" for metric in result["metrics"].values())
    assert collector.collect(RG) == result
    assert "secret" not in json.dumps(result) + str(capsys.readouterr())
    assert "private-payload" not in json.dumps(result)


def test_programming_errors_are_not_swallowed_by_broad_exception_handling():
    def az(*args):
        raise AssertionError("a programming error, not a read failure")
    with pytest.raises(AssertionError):
        usage.Collector(az, NOW).collect(RG)


@pytest.mark.parametrize("payload", ['{"value":', "null", '"secret payload"'])
def test_invalid_json_and_non_object_activity_cannot_become_zero(payload):
    az = Azure(handler=lambda args: subprocess.CompletedProcess([], 0, payload, ""))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_explicit_zeros_for_all_adf_states_are_valid():
    values = [
        monitor_metric(name, [{"timeStamp": "2026-10-07T20:00:00Z", "total": 0}], unit="Count")
        for name in ("PipelineSucceededRuns", "PipelineFailedRuns", "PipelineCancelledRuns")
    ]
    az = Azure([resource("Microsoft.DataFactory/factories")], lambda args: (
        response({"value": values}) if "/metrics?" in url_of(args) else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["adf"]
    assert metric["status"] == "ok"
    assert metric["value"] == 0


def test_snapshot_windows_align_with_monitor_full_bucket_minute_grain():
    def handler(args):
        if "/metrics?" not in url_of(args):
            return None
        query = parse_qs(urlsplit(url_of(args)).query)
        assert query["timespan"] == ["2026-09-08T20:00:00Z/2026-10-08T20:00:00Z"]
        return response({"value": [
            monitor_metric(name, [{"timeStamp": "2026-09-08T20:00:00Z", "total": total}], unit="Count")
            for name, total in (
                ("PipelineSucceededRuns", 4), ("PipelineFailedRuns", 0), ("PipelineCancelledRuns", 0)
            )
        ]})
    collector = usage.Collector(
        Azure([resource("Microsoft.DataFactory/factories")], handler),
        NOW.replace(second=37, microsecond=12345),
    )
    result = collector.collect(RG)
    assert result["observedAt"] == "2026-10-08T20:00:00Z"
    assert result["metrics"]["adf"]["value"] == 4


@pytest.mark.parametrize("modifier", [
    lambda url: url.replace("management.azure.com", "management.azure.com@attacker.example"),
    lambda url: url.replace("management.azure.com", "management.azure.com:443"),
    lambda url: url + "&api-version=2015-04-01",
    lambda url: url + "#fragment",
    lambda url: url.replace("/subscriptions/", "/%73ubscriptions/"),
    lambda url: url + "&$filter=unbounded",
])
def test_boundary_blocks_url_confusion_and_query_widening(modifier):
    az = Azure()
    usage.Collector(az, NOW).collect(RG)
    command = list(next(args for args in az.calls if args[0] == "rest"))
    command[command.index("--url") + 1] = modifier(url_of(command))
    assert not usage.is_read_command(command)


def test_denied_second_activity_page_discards_partial_count():
    def handler(args):
        url = url_of(args)
        if "$skiptoken=" in url:
            return response(error=True)
        return response({"value": [event()], "nextLink": url + "&$skiptoken=next"})
    metric = usage.Collector(Azure(handler=handler), NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_activity_app_claim_is_excluded_even_if_another_claim_alias_disagrees():
    az = Azure(handler=lambda args: response({"value": [
        event(claims={
            "http://schemas.microsoft.com/identity/claims/idtyp": "app",
            "idtyp": "user",
        }),
    ]}))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["value"] == 0


@pytest.mark.parametrize("mutation", [
    {"eventDataId": None}, {"claims": "not-an-object"}, {"eventTimestamp": None},
    {"resourceId": None},
])
def test_matching_but_malformed_activity_is_not_silently_excluded(mutation):
    az = Azure(handler=lambda args: response({"value": [event(**mutation)]}))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_resource_discovery_is_not_shortcut_first_resource_selection():
    resources = [resource("Microsoft.Storage/storageAccounts", name) for name in ("a", "b", "c")]
    resources[1]["id"] = resources[1]["id"].upper()
    resources[1]["type"] = resources[1]["type"].upper()
    az = Azure(resources, storage_handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["storage"]
    assert metric["value"] == 30
    assert metric["resourceCount"] == 3


def test_unrelated_alert_resource_name_with_spaces_does_not_block_usage_reads():
    az = Azure([
        resource("Microsoft.Storage/storageAccounts", "store"),
        resource("Microsoft.AlertsManagement/smartDetectorAlertRules", "Failure Anomalies - insights"),
    ], storage_handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["storage"]
    assert metric["status"] == "ok"
    assert metric["value"] == 10


def test_row_and_response_bounds_never_silently_truncate(monkeypatch):
    monkeypatch.setattr(usage, "MAX_RESPONSE_BYTES", 10)
    az = Azure(handler=lambda args: response({"value": [event()]}))
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]["status"] == "unavailable"


def model_row(workspace, name, archived=False):
    return {"id": workspace["id"] + "/models/" + name, "properties": {"isArchived": archived}}


def test_model_container_omitted_archive_flag_uses_documented_false_default():
    workspace = resource("Microsoft.MachineLearningServices/workspaces", "one", kind="Default")
    az = Azure([workspace], lambda args: (
        response({"value": [{"id": workspace["id"] + "/models/model", "properties": {}}]})
        if "/models?" in url_of(args) else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["models"]
    assert metric["status"] == "ok"
    assert metric["value"] == 1
    assert metric["archivedCount"] == 0


def test_models_count_distinct_containers_including_archived_across_workspaces_and_registries():
    workspaces = [
        resource("Microsoft.MachineLearningServices/workspaces", "one", kind="Default"),
        resource("Microsoft.MachineLearningServices/workspaces", "two", kind="Default"),
        resource("Microsoft.MachineLearningServices/registries", "registry"),
    ]
    hub = resource("Microsoft.MachineLearningServices/workspaces", "hub", kind="Hub")
    project = resource("Microsoft.MachineLearningServices/workspaces", "project", kind="Project")
    def handler(args):
        url = url_of(args)
        if "/models?" not in url:
            return None
        assert "api-version=2025-06-01" in url
        assert "listViewType=All" in url
        assert "/hub/" not in url and "/project/" not in url
        workspace = next(item for item in workspaces if item["id"] + "/models?" in url)
        if "$skiptoken=" in url:
            return response({"value": [model_row(workspace, "alpha"), model_row(workspace, "archived", True)]})
        return response({"value": [model_row(workspace, "alpha")], "nextLink": url + "&$skiptoken=next"})
    metric = usage.Collector(Azure([*workspaces, hub, project], handler), NOW).collect(RG)["metrics"]["models"]
    assert metric["status"] == "ok"
    assert metric["value"] == 6
    assert metric["archivedCount"] == 3
    assert "archived" in metric["detail"]
    assert metric["resourceCount"] == 3


@pytest.mark.parametrize("payload", [
    {},
    {"value": [{"id": RG + "/providers/Microsoft.MachineLearningServices/workspaces/one/models/x"}]},
    {"value": [{"id": RG + "/providers/Microsoft.MachineLearningServices/workspaces/one/models/x/versions/1",
                "properties": {"isArchived": False}}]},
    {"value": [{"id": RG + "-foreign/providers/Microsoft.MachineLearningServices/workspaces/one/models/x",
                "properties": {"isArchived": False}}]},
    {"value": [{"id": RG + "/providers/Microsoft.MachineLearningServices/workspaces/one/models/x",
                "properties": {"isArchived": "false"}}]},
])
def test_models_malformed_version_or_foreign_containers_are_unavailable(payload):
    az = Azure([resource("Microsoft.MachineLearningServices/workspaces", "one")], lambda args: (
        response(payload) if "/models?" in url_of(args) else None
    ))
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["models"]["status"] == "unavailable"


def test_models_empty_inventory_is_explicit_zero_and_hubs_are_not_aml():
    az = Azure([resource("Microsoft.MachineLearningServices/workspaces")], lambda args: (
        response({"value": []}) if "/models?" in url_of(args) else None
    ))
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["models"]["value"] == 0
    hub = Azure([resource("Microsoft.MachineLearningServices/workspaces", kind="Hub")])
    assert usage.Collector(hub, NOW).collect(RG)["metrics"]["models"]["status"] == "not-deployed"


PROJECT = {
    "id": RG + "/providers/Microsoft.CognitiveServices/accounts/foundry/projects/private-project",
    "type": "Microsoft.CognitiveServices/accounts/projects", "name": "foundry/private-project",
}
ENDPOINT = "https://verified-account.services.ai.azure.com/api/projects/private-project"


def project_response(project=PROJECT, endpoint=ENDPOINT):
    return response({**project, "properties": {"endpoints": {"AI Foundry API": endpoint}}})


def agents_handler(args):
    if args[:2] == ("resource", "show"):
        assert args[args.index("--api-version") + 1] == "2025-06-01"
        return project_response()
    url = url_of(args)
    if ".services.ai.azure.com/" not in url:
        return None
    assert args[args.index("--resource") + 1] == "https://ai.azure.com"
    query = parse_qs(urlsplit(url).query)
    assert query["limit"] == ["100"]
    assert query["order"] == ["asc"]
    classic = "/assistants?" in url
    assert query["api-version"] == (["2025-05-01"] if classic else ["v1"])
    prefix = "asst" if classic else "agent"
    if "after" in query:
        return response({"data": [{"id": prefix + "-2", "name": "secret-agent-name"}], "has_more": False})
    return response({
        "data": [{"id": prefix + "-1", "name": "secret-agent-name", "versions": {"latest": {"version": "9"}}}],
        "has_more": True, "last_id": prefix + "-1",
    })


def test_agents_use_distinct_new_and_classic_apis_with_cursor_pagination():
    az = Azure([PROJECT], agents_handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["agents"]
    assert metric["status"] == "ok"
    assert metric["value"] == 4
    assert metric["newCount"] == metric["classicCount"] == 2
    assert metric["newStatus"] == metric["classicStatus"] == "ok"
    assert "secret-agent-name" not in json.dumps(metric)
    assert len([args for args in az.calls if ".services.ai.azure.com/" in url_of(args)]) == 4


def test_classic_failure_does_not_substitute_new_agents_or_become_zero():
    def handler(args):
        if "/assistants?" in url_of(args):
            return response(error=True)
        return agents_handler(args)
    metric = usage.Collector(Azure([PROJECT], handler), NOW).collect(RG)["metrics"]["agents"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None
    assert metric["newCount"] == 2
    assert metric["classicCount"] is None
    assert metric["classicStatus"] == "unavailable"


@pytest.mark.parametrize("endpoint", [
    "https://attacker.example/api/projects/private-project",
    "https://verified-account.services.ai.azure.com/api/projects/foreign-project",
    ENDPOINT + "?api-version=v1",
    ENDPOINT.replace("https:", "http:"),
    ENDPOINT.replace("services.ai.azure.com", "services.ai.azure.com.attacker.example"),
])
def test_agents_reject_untrusted_or_foreign_project_endpoints_before_dataplane(endpoint):
    az = Azure([PROJECT], lambda args: project_response(endpoint=endpoint) if args[:2] == ("resource", "show") else None)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["agents"]
    assert metric["status"] == "unavailable"
    assert not any(".services.ai.azure.com/" in url_of(args) for args in az.calls)


@pytest.mark.parametrize("agent_payload", [
    {"data": []},
    {"data": [], "has_more": True, "last_id": "cursor"},
    {"data": [{"id": "agent"}], "has_more": True},
    {"data": [{"name": "secret-name"}], "has_more": False},
    {"data": [{"id": "agent"}], "has_more": False, "nextLink": "https://attacker.example"},
])
def test_agents_malformed_pagination_is_unavailable(agent_payload):
    az = Azure([PROJECT], lambda args: (
        project_response() if args[:2] == ("resource", "show")
        else response(agent_payload) if ".services.ai.azure.com/" in url_of(args) else None
    ))
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["agents"]["status"] == "unavailable"


def test_search_counts_all_indexes_without_keys_stats_or_document_search():
    services = [resource("Microsoft.Search/searchServices", name) for name in ("search-one", "search-two")]
    def handler(args):
        url = url_of(args)
        if ".search.windows.net/" not in url:
            return None
        assert args[args.index("--resource") + 1] == "https://search.azure.com"
        assert urlsplit(url).path == "/indexes"
        assert parse_qs(urlsplit(url).query) == {"api-version": ["2025-09-01"], "$select": ["name"]}
        return response({"value": [{"name": "secret-index-one"}, {"name": "secret-index-two"}]})
    metric = usage.Collector(Azure(services, handler), NOW).collect(RG)["metrics"]["search"]
    assert metric["status"] == "ok"
    assert metric["value"] == 4
    assert metric["resourceCount"] == 2
    assert "secret-index" not in json.dumps(metric)


@pytest.mark.parametrize("payload", [{}, {"value": [{"other": 1}]}, {"value": [], "@odata.nextLink": "https://attacker.example/indexes"}])
def test_search_missing_invalid_or_incomplete_is_not_zero(payload):
    az = Azure([resource("Microsoft.Search/searchServices", "search-one")], lambda args: (
        response(payload) if ".search.windows.net/" in url_of(args) else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["search"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_search_explicit_empty_is_zero_but_denied_is_unavailable():
    for result, status, count in ((response({"value": []}), "ok", 0), (response(error=True), "unavailable", None)):
        az = Azure([resource("Microsoft.Search/searchServices", "search-one")], lambda args: (
            result if ".search.windows.net/" in url_of(args) else None
        ))
        metric = usage.Collector(az, NOW).collect(RG)["metrics"]["search"]
        assert metric["status"] == status
        assert metric["value"] == count


def test_agents_read_every_project_and_do_not_deduplicate_names_between_projects():
    second = {
        **PROJECT, "name": "foundry/second-project",
        "id": PROJECT["id"].replace("private-project", "second-project"),
    }
    def handler(args):
        if args[:2] == ("resource", "show"):
            project = second if args[args.index("--ids") + 1] == second["id"] else PROJECT
            return project_response(project, ENDPOINT.replace("private-project", project["name"].split("/")[-1]))
        if ".services.ai.azure.com/" in url_of(args):
            return response({"data": [{"id": "same-agent", "name": "private-name"}], "has_more": False})
    metric = usage.Collector(Azure([PROJECT, second], handler), NOW).collect(RG)["metrics"]["agents"]
    assert metric["value"] == 4
    assert metric["newCount"] == metric["classicCount"] == 2
    assert metric["resourceCount"] == 2


def test_agent_cursor_cycle_is_unavailable_and_never_retries_same_page():
    def handler(args):
        if args[:2] == ("resource", "show"):
            return project_response()
        if ".services.ai.azure.com/" in url_of(args):
            return response({"data": [{"id": "same-cursor"}], "last_id": "same-cursor", "has_more": True})
    az = Azure([PROJECT], handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["agents"]
    assert metric["value"] is None
    assert metric["newCount"] is None and metric["classicCount"] is None
    urls = [url_of(args) for args in az.calls if ".services.ai.azure.com/" in url_of(args)]
    assert len(urls) == len(set(urls)) == 4


@pytest.mark.parametrize("bound", ["MAX_PAGES", "MAX_ROWS"])
def test_agents_respect_paging_and_row_bounds(monkeypatch, bound):
    monkeypatch.setattr(usage, bound, 1)
    metric = usage.Collector(Azure([PROJECT], agents_handler), NOW).collect(RG)["metrics"]["agents"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_agents_explicit_empty_both_populations_is_zero():
    az = Azure([PROJECT], lambda args: (
        project_response() if args[:2] == ("resource", "show")
        else response({"data": [], "has_more": False}) if ".services.ai.azure.com/" in url_of(args) else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["agents"]
    assert metric["value"] == metric["newCount"] == metric["classicCount"] == 0


def test_agent_arm_metadata_for_a_different_resource_is_not_trusted():
    az = Azure([PROJECT], lambda args: (
        project_response({**PROJECT, "id": PROJECT["id"] + "-other"})
        if args[:2] == ("resource", "show") else None
    ))
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["agents"]["status"] == "unavailable"
    assert not any(".services.ai.azure.com/" in url_of(args) for args in az.calls)


def test_models_second_page_auth_failure_cannot_preserve_partial_count():
    workspace = resource("Microsoft.MachineLearningServices/workspaces", "one")
    def handler(args):
        url = url_of(args)
        if "/models?" not in url:
            return None
        if "$skiptoken=" in url:
            return response(error=True)
        return response({"value": [model_row(workspace, "private-model")], "nextLink": url + "&$skiptoken=next"})
    metric = usage.Collector(Azure([workspace], handler), NOW).collect(RG)["metrics"]["models"]
    assert metric["value"] is None
    assert "private-model" not in json.dumps(metric)


@pytest.mark.parametrize("next_link", [False, 0, {}, []])
def test_invalid_continuation_types_are_unavailable(next_link):
    metric = usage.Collector(Azure(handler=lambda args: response({
        "value": [event()], "nextLink": next_link,
    })), NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "unavailable"


def test_boundary_data_endpoints_reject_broad_gets_keys_models_and_wrong_audiences():
    az = Azure([PROJECT], agents_handler)
    usage.Collector(az, NOW).collect(RG)
    command = list(next(args for args in az.calls if "/agents?" in url_of(args)))
    for changed_url in (
        ENDPOINT + "/connections?api-version=v1",
        ENDPOINT + "/agents/example/versions?api-version=v1",
        ENDPOINT + "/openai/responses?api-version=v1",
        ENDPOINT + "/listKeys?api-version=v1",
    ):
        changed = list(command)
        changed[changed.index("--url") + 1] = changed_url
        assert not usage.is_read_command(changed)
    changed = list(command)
    changed[changed.index("--resource") + 1] = "https://attacker.example"
    assert not usage.is_read_command(changed)


def test_result_and_logs_never_expose_resource_payloads_names_or_callers(capsys):
    storage = resource("Microsoft.Storage/storageAccounts", "private-storage")
    search = resource("Microsoft.Search/searchServices", "private-search")
    model = resource("Microsoft.MachineLearningServices/workspaces", "private-workspace")
    def handler(args):
        url = url_of(args)
        if "eventtypes/management/values" in url:
            return response({"value": [event()]})
        if "/models?" in url:
            return response({"value": [model_row(model, "private-model")]})
        if ".search.windows.net/" in url:
            return response({"value": [{"name": "private-index"}]})
        if "/metrics?" in url:
            return storage_handler(args)
        if args[:2] == ("resource", "show") and "/microsoft.search/searchservices/" in args[args.index("--ids") + 1].lower():
            return None
        return agents_handler(args)
    result = usage.Collector(Azure([PROJECT, storage, search, model], handler), NOW).collect(RG)
    assert all(result["metrics"][key]["status"] == "ok" for key in ("activity", "agents", "models", "storage", "search"))
    output = json.dumps(result) + str(capsys.readouterr())
    for sensitive in ("private-", "secret-", RG, SUB, ".azure.com", ".search.windows.net", "event-1"):
        assert sensitive not in output


def test_launcher_runtime_failures_are_sanitized_without_masking_parser_errors():
    def az(*args):
        raise RuntimeError("private-path secret-token")
    result = usage.Collector(az, NOW).collect(RG)
    assert all(metric["status"] == "unavailable" for metric in result["metrics"].values())
    assert "private-path" not in json.dumps(result)
    assert "secret-token" not in json.dumps(result)


def test_foundry_arm_id_case_does_not_change_verified_endpoint_identity():
    project = {**PROJECT, "id": PROJECT["id"].upper(), "type": PROJECT["type"].upper()}
    az = Azure([project], agents_handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["agents"]
    assert metric["status"] == "ok"
    assert metric["value"] == 4


def test_inconsistent_model_archive_state_does_not_report_a_stable_total():
    workspace = resource("Microsoft.MachineLearningServices/workspaces", "one")
    az = Azure([workspace], lambda args: response({"value": [
        model_row(workspace, "changing", False), model_row(workspace, "changing", True),
    ]}) if "/models?" in url_of(args) else None)
    assert usage.Collector(az, NOW).collect(RG)["metrics"]["models"]["status"] == "unavailable"


@pytest.mark.parametrize("sample", [float("nan"), float("inf"), 10**400])
def test_invalid_or_unbounded_numeric_samples_do_not_crash_or_report_values(sample):
    az = Azure([resource("Microsoft.Storage/storageAccounts")], lambda args: (
        response({"value": [monitor_metric("UsedCapacity", [
            {"timeStamp": "2026-10-08T19:00:00Z", "average": sample},
        ])]}) if "/metrics?" in url_of(args) else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["storage"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None


def test_models_follow_live_arm_camel_case_skip_token_across_every_page():
    workspace = resource("Microsoft.MachineLearningServices/workspaces", "one")
    def handler(args):
        url = url_of(args)
        if "/models?" not in url:
            return None
        cursor = parse_qs(urlsplit(url).query).get("$skipToken", [""])[0]
        if cursor == "third":
            return response({"value": [model_row(workspace, "last", True)]})
        if cursor == "second":
            return response({
                "value": [model_row(workspace, "middle")],
                "nextLink": url.replace("$skipToken=second", "$skipToken=third"),
            })
        return response({
            "value": [model_row(workspace, f"first-{index}") for index in range(20)],
            "nextLink": url + "&$skipToken=second",
        })
    az = Azure([workspace], handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["models"]
    assert metric["status"] == "ok"
    assert metric["value"] == 22
    assert metric["archivedCount"] == 1
    assert len([args for args in az.calls if "/models?" in url_of(args)]) == 3


@pytest.mark.parametrize("endpoint", [
    None,
    "https://attacker.example",
    "https://another-service.search.windows.net",
    "https://search-one.search.windows.net/indexes",
    "https://search-one.search.windows.net?api-version=2025-09-01",
])
def test_search_endpoint_must_be_verified_in_the_exact_arm_resource_metadata(endpoint):
    service = resource("Microsoft.Search/searchServices", "search-one")
    az = Azure([service], lambda args: (
        response({"id": service["id"], "properties": {"endpoint": endpoint}})
        if args[:2] == ("resource", "show") else None
    ))
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["search"]
    assert metric["status"] == "unavailable"
    assert not any(".search.windows.net/" in url_of(args) for args in az.calls)


def test_search_reads_verified_arm_endpoint_with_optional_trailing_slash():
    service = resource("Microsoft.Search/searchServices", "search-one")
    def handler(args):
        if args[:2] == ("resource", "show"):
            return response({
                "id": service["id"].upper(),
                "properties": {"endpoint": "https://search-one.search.windows.net/"},
            })
        if ".search.windows.net/" in url_of(args):
            return response({"value": [{"name": "index"}]})
    az = Azure([service], handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["search"]
    assert metric["status"] == "ok" and metric["value"] == 1
    assert len([args for args in az.calls if args[:2] == ("resource", "show")]) == 1


@pytest.mark.parametrize("claims", [
    {"idtyp": "user"},
    {"scp": "user_impersonation", "appid": "delegated-client-id"},
    {"http://schemas.microsoft.com/identity/claims/scope": "user_impersonation"},
    '{"idtyp":"user","appid":"delegated-client-id"}',
])
def test_activity_requires_positive_user_or_delegated_scope_without_excluding_appid(claims):
    metric = usage.Collector(Azure(handler=lambda args: response({
        "value": [event(claims=claims)],
    })), NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "ok"
    assert metric["value"] == 1
    assert metric["unclassifiedEvents"] == 0


@pytest.mark.parametrize("claims", [
    None, {}, "", "malformed json", "[]", {"appid": "client"},
    {"idtyp": "user", "scp": ["malformed-scope"]},
])
def test_activity_email_with_unknown_identity_is_not_assumed_user_or_zero(claims):
    metric = usage.Collector(Azure(handler=lambda args: response({
        "value": [event(claims=claims), event(claims=claims)],
    })), NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None
    assert metric["unclassifiedEvents"] == 1
    assert metric["classifiedEvents"] == 0


def test_activity_mixed_known_and_unknown_identities_exposes_only_safe_counts():
    metric = usage.Collector(Azure(handler=lambda args: response({
        "value": [event("known"), event("unknown", claims={}), event("unknown", claims={})],
    })), NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "unavailable"
    assert metric["value"] is None
    assert metric["unclassifiedEvents"] == metric["classifiedEvents"] == 1
    assert "private-person" not in json.dumps(metric)


@pytest.mark.parametrize("include_api", [False, True])
def test_activity_official_continuation_can_omit_filter_and_api_without_query_rewrite(include_api):
    continuation = (
        f"https://management.azure.com/subscriptions/{SUB}/providers/microsoft.insights/eventtypes/management/values"
        + "?$skiptoken=opaque%2Bcursor" + ("&api-version=2015-04-01" if include_api else "")
    )
    def handler(args):
        url = url_of(args)
        assert "$select" not in parse_qs(urlsplit(url).query)
        if "$skiptoken=" in url:
            assert url == continuation
            return response({"value": [
                event("two"), event("one"),
                event("foreign", resourceId=RG.replace(SUB, OTHER_SUB) + "/providers/Microsoft.Storage/storageAccounts/x"),
                event("old", eventTimestamp="2026-01-01T00:00:00Z"),
            ]})
        return response({"value": [event("one")], "nextLink": continuation})
    az = Azure(handler=handler)
    metric = usage.Collector(az, NOW).collect(RG)["metrics"]["activity"]
    assert metric["status"] == "ok" and metric["value"] == 2
    assert len(az.calls) == 3


def test_activity_lowercase_path_continuation_is_accepted_but_scope_stays_exact():
    def handler(args):
        url = url_of(args)
        if "$skiptoken=" in url:
            return response({"value": [event("two")]})
        first = urlsplit(url)
        return response({"value": [event("one")], "nextLink": (
            first.scheme + "://" + first.netloc + first.path.upper() + "?$skiptoken=next"
        )})
    assert usage.Collector(Azure(handler=handler), NOW).collect(RG)["metrics"]["activity"]["value"] == 2


@pytest.mark.parametrize("query", [
    "api-version=2015-04-01",
    "$skiptoken=cursor&api-version=wrong",
    "$skiptoken=cursor&$select=caller",
    "$skiptoken=cursor&$filter=unbounded",
])
def test_activity_boundary_rejects_unbounded_or_changed_continuation_query(query):
    args = (
        "rest", "--method", "get", "--url",
        f"https://management.azure.com/subscriptions/{SUB}/providers/microsoft.insights/eventtypes/management/values?{query}",
        "--subscription", SUB, "--output", "json", "--only-show-errors",
    )
    assert not usage.is_read_command(args)
