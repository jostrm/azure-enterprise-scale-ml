"""Deterministic offline tests for the project deletion command-line boundary."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "environment_setup/aifactory/bicep/scripts/project-deletion.py"
spec = importlib.util.spec_from_file_location("project_deletion", SCRIPT)
deletion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deletion)
SUB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RG = "project-002"
GROUP = f"/subscriptions/{SUB}/resourceGroups/{RG}"
NETWORK = f"/subscriptions/{SUB}/resourceGroups/network"
DBX = "Microsoft.Databricks/workspaces"
ML = "Microsoft.MachineLearningServices/workspaces"
DBX_ID = f"{GROUP}/providers/{DBX}/dbx"
ML_ID = f"{GROUP}/providers/{ML}/aml"
ENDPOINTS = ML_ID + "/onlineEndpoints"
EP_ID = ENDPOINTS + "/ep"
VNETS = NETWORK + "/providers/Microsoft.Network/virtualNetworks"
VNET = VNETS + "/shared"
NSGS = NETWORK + "/providers/Microsoft.Network/networkSecurityGroups"
FOUNDRY_TYPE = "Microsoft.CognitiveServices/accounts"
FOUNDRY_ID = f"{GROUP}/providers/{FOUNDRY_TYPE}/foundry"


def body(resource_id=DBX_ID, state="Succeeded"):
    parts = resource_id.split("/")
    result = {"id": resource_id, "name": parts[-1], "properties": {}}
    if "/providers/" in resource_id:
        provider = resource_id.split("/providers/")[-1].split("/")
        result["type"] = "/".join([provider[0], *provider[1::2]])
    if state is not None:
        result["properties"]["provisioningState"] = state
    return result


def error(code="ResourceNotFound", message="The resource is absent."):
    return SimpleNamespace(returncode=1, stdout="", stderr=f"ERROR: ({code}) {message}")


def raw_error(text):
    return SimpleNamespace(returncode=1, stdout="", stderr=text)


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        assert 0 < seconds <= 2
        self.now += seconds


class FakeAzure:
    def __init__(self, steps, clock):
        self.steps = list(steps)
        self.calls = []
        self.clock = clock

    def __call__(self, command, **kwargs):
        assert isinstance(command, list)
        assert command[0].endswith("az.cmd")
        assert kwargs["env"]["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no"
        assert kwargs["env"]["MSYS_NO_PATHCONV"] == "1"
        assert kwargs["env"]["MSYS2_ARG_CONV_EXCL"] == "*"
        assert kwargs.get("shell", False) is False
        assert kwargs["timeout"] > 0
        assert "--subscription" in command and command[command.index("--subscription") + 1] == SUB
        assert "--only-show-errors" in command
        if command[1] == "rest":
            verb = command[command.index("--method") + 1].upper()
            target = unquote(urlsplit(command[command.index("--url") + 1]).path)
        elif command[1:3] == ["resource", "list"]:
            verb, target = "LIST", GROUP
            assert command[command.index("--resource-group") + 1] == RG
        elif command[1:3] == ["group", "delete"]:
            verb, target = "DELETE-GROUP", GROUP
            assert "--yes" in command and "--no-wait" in command
            assert command[command.index("--name") + 1] == RG
        elif command[1:4] == ["monitor", "activity-log", "list"]:
            verb, target = "ACTIVITY", GROUP
        else:
            pytest.fail(f"Unexpected Azure command: {command}")
        self.calls.append((verb, target, command, kwargs))
        assert self.steps, f"Unexpected {verb} {target}"
        expected_verb, expected_target, result = self.steps.pop(0)
        assert (verb, target.lower()) == (expected_verb, expected_target.lower())
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return result(kwargs)
        if isinstance(result, SimpleNamespace):
            return result
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")


@pytest.fixture(autouse=True)
def forbid_real_commands(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real external commands are forbidden")
    monkeypatch.setattr(deletion.subprocess, "run", forbidden)
    monkeypatch.setattr(deletion.shutil, "which", lambda name: r"C:\Azure CLI\az.cmd")


@pytest.fixture
def report_dir():
    path = ROOT / (".project-deletion-test-" + str(uuid4()))
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def invoke(steps, args, *, timeout=12, report_dir=None):
    clock = Clock()
    runner = FakeAzure(steps, clock)
    argv = ["--subscription", SUB, "--resource-group", RG,
            "--timeout-seconds", str(timeout), "--poll-seconds", "2"]
    if report_dir:
        argv.extend(["--report-dir", str(report_dir)])
    status = deletion.main(argv + args, runner=runner, clock=clock.time, sleep=clock.sleep)
    assert runner.steps == []
    assert all(call[3]["timeout"] <= timeout for call in runner.calls)
    return status, runner, clock


RESOURCE = ["resource", "--resource-type", DBX, "--name", "dbx"]
GROUP_ARGS = ["group", "--confirm-resource-group", RG]
NETWORK_ARGS = ["verify-network", "--network-resource-group", "network", "--project-number", "002"]


def test_names_authoritative_case_insensitive_prefixes_stdout_only(capsys):
    steps = [("LIST", GROUP, [
        body(DBX_ID), body(DBX_ID.replace("/dbx", "/Other")),
        body(f"{GROUP}/providers/{ML}/dbx"),
    ])]
    status, runner, _ = invoke(steps, ["names", "--resource-type", DBX.upper(),
                                     "--prefix", "DB", "--prefix", "unused"])
    assert status == 0
    assert capsys.readouterr().out == "dbx\n"
    assert len(runner.calls) == 1


def test_resource_list_generic_resource_shape_supports_null_properties(capsys):
    item = {**body(), "properties": None, "provisioningState": "Deleting", "resourceGroup": RG}
    status, _, _ = invoke([("LIST", GROUP, [item])], ["names", "--resource-type", DBX])
    assert status == 0 and capsys.readouterr().out == "dbx\n"


@pytest.mark.parametrize("name", [
    "Failure Anomalies - ain-prj002-sdc-dev-bltsc-001",
    "Défaillances détectées - 東京 - prj002",
])
def test_names_accepts_real_ancillary_alert_names_in_group_inventory(name, capsys):
    alert = f"{GROUP}/providers/Microsoft.AlertsManagement/smartDetectorAlertRules/{name}"
    status, _, _ = invoke([("LIST", GROUP, [body(alert), body()])],
                          ["names", "--resource-type", DBX])
    assert status == 0 and capsys.readouterr().out == "dbx\n"


@pytest.mark.parametrize("suffix", [
    "alert\nfake", "alert\rname", "alert\x00name", "alert\u202ename", ".", "..",
    "alert/../../other", "%2e%2e", "%252e%252e", "%2fother", "alert%0aname",
    "alert\\other", "alert?api-version=evil", "alert#fragment",
])
def test_generic_inventory_names_reject_traversal_controls_and_url_delimiters(suffix):
    alert = f"{GROUP}/providers/Microsoft.AlertsManagement/smartDetectorAlertRules/{suffix}"
    status, _, _ = invoke([("LIST", GROUP, [body(alert), body()])],
                          ["names", "--resource-type", DBX])
    assert status != 0


@pytest.mark.parametrize("provider,kind", [
    ("Microsoft.Alert Management", "smartDetectorAlertRules"),
    ("Microsoft.AlertsManagement", "smart DetectorAlertRules"),
    ("Microsoft.警告", "smartDetectorAlertRules"),
    ("Microsoft.AlertsManagement", "規則"),
])
def test_generic_inventory_namespace_and_type_syntax_stays_strict(provider, kind):
    alert = f"{GROUP}/providers/{provider}/{kind}/ordinary name"
    status, _, _ = invoke([("LIST", GROUP, [body(alert), body()])],
                          ["names", "--resource-type", DBX])
    assert status != 0


def test_names_supports_app_insights_read_only_without_provider_extensions(capsys):
    insights = "Microsoft.Insights/components"
    resource_id = f"{GROUP}/providers/{insights}/appinsights-prj002"
    status, runner, _ = invoke([
        ("LIST", GROUP, [body(resource_id), body()]),
    ], ["names", "--resource-type", insights.upper(), "--prefix", "APPINSIGHTS-"])
    assert status == 0
    assert capsys.readouterr().out == "appinsights-prj002\n"
    assert [call[0] for call in runner.calls] == ["LIST"]


def test_generic_name_lookup_rejects_nested_provider_scope():
    insights = "Microsoft.Insights/components"
    resource_id = f"{GROUP}/providers/Microsoft.Fake/things/parent/providers/{insights}/component"
    status, _, _ = invoke([
        ("LIST", GROUP, [body(resource_id)]),
    ], ["names", "--resource-type", insights])
    assert status != 0


@pytest.mark.parametrize("resource_type", [
    "", "Microsoft.Insights", "Microsoft.Insights/components/../../workspaces",
    "Microsoft.Insights/components?api-version=2020-01-01", "Microsoft.Insights/components\n",
])
def test_names_rejects_unsafe_generic_types_without_commands(resource_type):
    assert deletion.main(["--subscription", SUB, "--resource-group", RG,
                          "names", "--resource-type", resource_type]) != 0


@pytest.mark.parametrize("result", [
    {}, None, {"value": []}, [None], [{"name": "dbx", "type": DBX}],
    [body(DBX_ID.replace(RG, "managed-group"))],
    [body(DBX_ID.replace(SUB, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))],
    [{**body(), "name": "unrelated"}],
    [{**body(), "type": ML}], [body(), body()],
    [body(f"{GROUP}/providers/Microsoft.Fake/things/parent/providers/{DBX}/dbx")],
    SimpleNamespace(returncode=0, stdout='[{"id":"one","id":"two"}]', stderr=""),
    SimpleNamespace(returncode=0, stdout="[] trailing", stderr=""),
])
def test_names_reject_malformed_or_out_of_scope_inventory(result, capsys):
    status, _, _ = invoke([("LIST", GROUP, result)], ["names", "--resource-type", DBX])
    assert status != 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("result, expected", [
    (error("ResourceGroupNotFound"), 0),
    (error("ResourceNotFound"), 1),
    (error("AuthorizationFailed", "403 ResourceGroupNotFound is mentioned"), 1),
])
def test_names_only_exact_group_not_found_is_empty(result, expected):
    status, _, _ = invoke([("LIST", GROUP, result)], ["names", "--resource-type", DBX])
    assert status == expected


@pytest.mark.parametrize("result, expected", [
    (error(), 0), (error("ResourceGroupNotFound"), 0),
    (raw_error('{"error":{"code":"ResourceNotFound","message":"gone"}}'), 0),
    (raw_error('ERROR: {"error":{"code":"ResourceNotFound","message":"gone"}}'), 0),
    (error("AuthorizationFailed", "403: ResourceNotFound was in a previous request"), 1),
    (raw_error('{"error":{"code":"AuthorizationFailed","message":"ResourceNotFound"}}'), 1),
    (raw_error('ERROR: 403 Forbidden: {"code":"ResourceNotFound"}'), 1),
    (raw_error("ERROR: (AuthorizationFailed) denied\nERROR: (ResourceNotFound) old error"), 1),
    (raw_error('{"error":{"code":"AuthorizationFailed","code":"ResourceNotFound"}}'), 1),
    (SimpleNamespace(returncode=1, stderr="ERROR: HTTP 403 Forbidden",
                     stdout='{"error":{"code":"ResourceNotFound"}}'), 1),
    (raw_error('{"status":403,"error":{"code":"ResourceNotFound","message":"denied"}}'), 1),
    (raw_error('{"error":{"code":"ResourceNotFound"},"code":"AuthorizationFailed"}'), 1),
])
def test_exact_not_found_recognition(result, expected):
    status, runner, _ = invoke([("GET", DBX_ID, result)], RESOURCE)
    assert status == expected
    assert len(runner.calls) == 1


@pytest.mark.parametrize("text,expected", [
    ('ERROR: Not Found({"error":{"code":"ResourceNotFound","message":"gone"}})', 0),
    ('ERROR: Not Found({"error":{"code":"ResourceGroupNotFound","message":"gone"}})', 0),
    ('ERROR: Not Found({\n"error": {"code": "ResourceNotFound", "message": "gone"}\n})', 0),
    ('ERROR: Forbidden({"error":{"code":"AuthorizationFailed","message":"ResourceNotFound"}})', 1),
    ('ERROR: Forbidden({"error":{"code":"ResourceNotFound","message":"contradictory"}})', 1),
    ('ERROR: Bad Request({"error":{"code":"ResourceNotFound","message":"contradictory"}})', 1),
    ('ERROR: Not Found({"status":403,"error":{"code":"ResourceNotFound"}})', 1),
    ('ERROR: Not Found({"error":{"code":"ResourceNotFound","code":"AuthorizationFailed"}})', 1),
    ('ERROR: Not Found({"error":{"code":"ResourceNotFound"}}) trailing', 1),
    ('ERROR: Not Found({"error":{"code":"ResourceNotFound"}})\nERROR: Forbidden({"error":{"code":"AuthorizationFailed"}})', 1),
    ('ERROR: Not Found({"error":{"code":"ResourceNotFound"}})\nERROR: Not Found({"error":{"code":"ResourceNotFound"}})', 1),
    ('ERROR: Not Found({"outer":{"error":{"code":"ResourceNotFound"}}})', 1),
    ('ERROR: Not Found({"error":{"innererror":{"code":"ResourceNotFound"}}})', 1),
    ('ERROR: Not Found({"error":[{"code":"ResourceNotFound"},{"code":"ResourceNotFound"}]})', 1),
    ('ERROR: Not Found({"error":{"code":"ResourceNotFound","details":[{"code":"AuthorizationFailed"}]}})', 1),
    ('ERROR: Not Found({"error":{"code":"ResourceNotFound"},"errors":[{"code":"AuthorizationFailed"}]})', 1),
    ('ERROR: (ResourceNotFound) gone\nERROR: (ResourceNotFound) duplicate', 1),
])
def test_azure_cli_core_rest_wrapped_errors_are_exact_and_status_consistent(text, expected):
    status, runner, _ = invoke([("GET", DBX_ID, raw_error(text))], RESOURCE)
    assert status == expected and len(runner.calls) == 1


@pytest.mark.parametrize("wrapper,code,expected", [
    ("Conflict", "RequestConflict", 0),
    ("Conflict", "AnotherOperationInProgress", 0),
    ("Conflict", "ApplianceBeingDeleted", 0),
    ("Forbidden", "RequestConflict", 1),
])
def test_wrapped_rest_conflicts_reconcile_only_with_matching_http_status(wrapper, code, expected):
    steps = [("GET", DBX_ID, body()),
             ("DELETE", DBX_ID, raw_error(f'ERROR: {wrapper}({{"error":{{"code":"{code}","message":"busy"}}}})'))]
    if expected == 0:
        steps.append(("GET", DBX_ID, error()))
    status, runner, _ = invoke(steps, RESOURCE)
    assert status == expected
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1


def test_already_deleting_polls_without_submitting():
    status, runner, _ = invoke([
        ("GET", DBX_ID, body(state="Deleting")),
        ("GET", DBX_ID, body(state="Deleting")),
        ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0
    assert all(call[0] == "GET" for call in runner.calls)


def test_case_insensitive_resource_id_rollback_remains_a_reported_failure(report_dir):
    status, runner, _ = invoke([
        ("GET", DBX_ID, {**body(state="Deleting"), "id": DBX_ID.upper()}),
        ("GET", DBX_ID, {**body(), "id": DBX_ID.upper()}),
    ], RESOURCE, report_dir=report_dir)
    assert status != 0 and all(call[0] == "GET" for call in runner.calls)
    report = json.loads((report_dir / "last-deletion.json").read_text())
    assert report["error"]["code"] == "ResourceDeletionFailed"


@pytest.mark.parametrize("state", ["Creating", "Updating", "Accepted"])
def test_busy_to_stable_submits_once_then_requires_absence(state):
    status, runner, _ = invoke([
        ("GET", DBX_ID, body(state=state)), ("GET", DBX_ID, body()),
        ("DELETE", DBX_ID, None),
        ("GET", DBX_ID, body()), ("GET", DBX_ID, body(state="Deleting")),
        ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1


@pytest.mark.parametrize("code", ["RequestConflict", "AnotherOperationInProgress", "ApplianceBeingDeleted"])
def test_conflicts_reconcile_deleting_and_do_not_overlap(code):
    status, runner, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, error(code)),
        ("GET", DBX_ID, body(state="Deleting")), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1


def test_conflict_stable_retry_is_bounded_and_rereads_before_write():
    status, runner, clock = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, error("RequestConflict")),
        ("GET", DBX_ID, body()), ("GET", DBX_ID, body()),
        ("DELETE", DBX_ID, None), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0
    assert clock.now >= 2
    assert sum(call[0] == "DELETE" for call in runner.calls) == 2


def test_conflict_retries_stop_at_three_with_original_provider_error(capsys):
    steps = [("GET", DBX_ID, body())]
    for attempt in range(3):
        steps.extend([("DELETE", DBX_ID, error("ApplianceBeingDeleted")), ("GET", DBX_ID, body())])
        if attempt < 2:
            steps.append(("GET", DBX_ID, body()))
    status, runner, _ = invoke(steps, RESOURCE)
    assert status != 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 3
    assert "ApplianceBeingDeleted" in capsys.readouterr().err


def test_conflict_busy_reconciliation_waits_until_stable_before_retry():
    status, runner, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, error("AnotherOperationInProgress")),
        ("GET", DBX_ID, body(state="Updating")), ("GET", DBX_ID, body(state="Updating")),
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, None), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 2


@pytest.mark.parametrize("code", ["AuthorizationFailed", "ScopeLocked", "Conflict"])
def test_nonretryable_submission_never_retries(code, capsys):
    status, _, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, error(code, "Remove the blocker.")),
    ], RESOURCE)
    assert status != 0
    captured = capsys.readouterr()
    assert code in captured.err and DBX_ID in captured.err and "Remove the blocker" in captured.err


def test_multiline_provider_failure_keeps_actionable_nested_code(capsys):
    status, _, _ = invoke([
        ("GET", DBX_ID, body()),
        ("DELETE", DBX_ID, error("ResourceGroupDeletionBlocked",
                                 "Deletion failed.\nDetails: (ApplianceBeingDeleted) Wait for the workspace.")),
    ], RESOURCE)
    assert status != 0
    assert "ApplianceBeingDeleted" in capsys.readouterr().err


@pytest.mark.parametrize("resource_type,version", [
    (DBX, "2024-05-01"), (ML, "2024-10-01"),
    ("Microsoft.DataFactory/factories", "2018-06-01"),
    ("Microsoft.CognitiveServices/accounts", "2025-06-01"),
    ("Microsoft.Portal/dashboards", "2020-09-01-preview"),
    ("Microsoft.Insights/components", "2020-02-02"),
])
def test_supported_types_use_pinned_rest_api_versions(resource_type, version):
    resource_id = f"{GROUP}/providers/{resource_type}/resource"
    status, runner, _ = invoke([("GET", resource_id, error())],
                              ["resource", "--resource-type", resource_type, "--name", "resource"])
    assert status == 0
    command = runner.calls[0][2]
    assert urlsplit(command[command.index("--url") + 1]).query == f"api-version={version}"


def test_app_insights_delete_uses_rest_and_waits_for_absence():
    resource_type = "Microsoft.Insights/components"
    resource_id = f"{GROUP}/providers/{resource_type}/component"
    status, runner, _ = invoke([
        ("GET", resource_id, body(resource_id)), ("DELETE", resource_id, None),
        ("GET", resource_id, body(resource_id, "Deleting")), ("GET", resource_id, error()),
    ], ["resource", "--resource-type", resource_type, "--name", "component"])
    assert status == 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1
    for _, _, command, _ in runner.calls:
        assert command[1] == "rest"
        assert urlsplit(command[command.index("--url") + 1]).query == "api-version=2020-02-02"


@pytest.mark.parametrize("name", [
    "Project 002 telemetry", "Projet 002 télémétrie 東京", "Project (002) telemetry: prod",
])
def test_app_insights_names_to_resource_pipeline_preserves_valid_names_and_encodes_urls(name, capsys):
    resource_type = "Microsoft.Insights/components"
    resource_id = f"{GROUP}/providers/{resource_type}/{name}"
    status, _, _ = invoke([("LIST", GROUP, [body(resource_id)])],
                          ["names", "--resource-type", resource_type])
    assert status == 0
    discovered = capsys.readouterr().out.splitlines()
    assert discovered == [name]
    status, runner, _ = invoke([
        ("GET", resource_id, body(resource_id)), ("DELETE", resource_id, None),
        ("GET", resource_id, error()),
    ], ["resource", "--resource-type", resource_type, "--name", discovered[0]])
    assert status == 0
    for _, _, command, _ in runner.calls:
        url = command[command.index("--url") + 1]
        assert " " not in url and all(ord(character) < 128 for character in url)
        assert urlsplit(url).path == quote(resource_id, safe="/-._")
        assert urlsplit(url).query == "api-version=2020-02-02"


def test_app_insights_state_supports_unicode_and_internal_spaces(capsys):
    name = "Project 002 télémétrie"
    resource_type = "Microsoft.Insights/components"
    resource_id = f"{GROUP}/providers/{resource_type}/{name}"
    status, runner, _ = invoke([("GET", resource_id, body(resource_id, "Deleting"))],
                              ["state", "--resource-type", resource_type, "--name", name])
    assert status == 0
    assert capsys.readouterr().out == "deleting\n"
    assert [call[0] for call in runner.calls] == ["GET"]


@pytest.mark.parametrize("action", ["resource", "state"])
@pytest.mark.parametrize("name", [
    "", "a" * 261, ".", "..", "trailing.", "trailing ", "a/b", "a\\b",
    "a?api-version=evil", "a#fragment", "a%20b", "%252e%252e", "a&b",
    "a\nb", "a\rb", "a\x00b", "a\u202eb", "parent/../other",
])
def test_app_insights_name_rejects_forbidden_characters_and_scope_escapes(action, name):
    assert deletion.main(["--subscription", SUB, "--resource-group", RG, action,
                          "--resource-type", "Microsoft.Insights/components", "--name", name]) != 0


@pytest.mark.parametrize("action", ["resource", "state"])
@pytest.mark.parametrize("name", [
    "Project 002 dashboard", "project_dashboard", "project.dashboard", "project@dashboard",
    "x", "a" * 161, "ダッシュボード",
])
def test_portal_dashboard_resource_name_follows_documented_rules_not_display_title(action, name):
    assert deletion.main(["--subscription", SUB, "--resource-group", RG, action,
                          "--resource-type", "Microsoft.Portal/dashboards", "--name", name]) != 0


@pytest.mark.parametrize("state", ["Deleting", "Updating", "Succeeded", "Failed"])
def test_state_query_is_read_only_lowercase_and_stdout_clean(state, capsys):
    status, runner, _ = invoke([("GET", FOUNDRY_ID, body(FOUNDRY_ID, state))],
                              ["state", "--resource-type", FOUNDRY_TYPE, "--name", "foundry"])
    assert status == 0
    captured = capsys.readouterr()
    assert captured.out == state.lower() + "\n" and captured.err == ""
    assert [call[0] for call in runner.calls] == ["GET"]


@pytest.mark.parametrize("response,expected", [
    (error(), 0), (error("ResourceGroupNotFound"), 0),
    (error("AuthorizationFailed", "403; ResourceNotFound is not authoritative"), 1),
    (body(FOUNDRY_ID, None), 1), (body(FOUNDRY_ID, "Unknown"), 1),
    (body(FOUNDRY_ID, "Absent"), 1),
    (body(FOUNDRY_ID.replace("/foundry", "/other")), 1),
])
def test_state_query_absence_requires_exact_404_and_unknown_is_failure(response, expected, capsys, report_dir):
    status, runner, _ = invoke([("GET", FOUNDRY_ID, response)],
                              ["state", "--resource-type", FOUNDRY_TYPE, "--name", "foundry"],
                              report_dir=report_dir)
    assert status == expected
    captured = capsys.readouterr()
    assert captured.out == ("absent\n" if expected == 0 else "")
    assert [call[0] for call in runner.calls] == ["GET"]
    report = json.loads((report_dir / "last-deletion.json").read_text())
    assert report["status"] == ("succeeded" if expected == 0 else "failed")
    assert list(report_dir.glob("deletion-state-*.json"))


def test_delete_not_found_still_confirms_with_get():
    status, runner, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, error()), ("GET", DBX_ID, error()),
    ], RESOURCE)
    assert status == 0 and runner.calls[-1][0] == "GET"


def test_accepted_submission_times_out_without_success_report(report_dir):
    status, runner, clock = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, None),
        ("GET", DBX_ID, body()), ("GET", DBX_ID, body()),
    ], RESOURCE, timeout=4, report_dir=report_dir)
    assert status != 0 and clock.now == 4
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1
    report = json.loads((report_dir / "last-deletion.json").read_text())
    assert report["status"] == "timeout"
    assert DBX_ID in json.dumps(report)


def test_subprocess_timeout_is_uncertain_no_retry_and_deadline_bounded(report_dir):
    def timeout(kwargs):
        raise subprocess.TimeoutExpired("az", kwargs["timeout"], stderr="secret raw output")
    status, runner, _ = invoke([
        ("GET", DBX_ID, body(state="Updating")), ("GET", DBX_ID, body()),
        ("DELETE", DBX_ID, timeout),
    ], RESOURCE, timeout=5, report_dir=report_dir)
    assert status != 0
    assert runner.calls[-1][3]["timeout"] <= 3
    report = (report_dir / "last-deletion.json").read_text()
    assert "secret raw output" not in report and '"status": "timeout"' in report


def test_read_error_after_submission_is_not_absence():
    status, runner, _ = invoke([
        ("GET", DBX_ID, body()), ("DELETE", DBX_ID, None),
        ("GET", DBX_ID, error("AuthorizationFailed")),
    ], RESOURCE)
    assert status != 0
    assert sum(call[0] == "DELETE" for call in runner.calls) == 1


def test_ml_already_deleting_does_not_list_or_delete_children():
    status, runner, _ = invoke([
        ("GET", ML_ID, body(ML_ID, "Deleting")), ("GET", ML_ID, error()),
    ], ["resource", "--resource-type", ML, "--name", "aml"])
    assert status == 0
    assert len(runner.calls) == 2


def test_ml_pages_are_validated_and_children_absent_before_workspace_delete():
    second = f"https://management.azure.com{ENDPOINTS}?api-version=2024-10-01&$skiptoken=next"
    ep2 = ENDPOINTS + "/ep2"
    status, runner, _ = invoke([
        ("GET", ML_ID, body(ML_ID)),
        ("GET", ENDPOINTS, {"value": [body(EP_ID)], "nextLink": second}),
        ("GET", ENDPOINTS, {"value": [body(ep2)]}),
        ("GET", EP_ID, body(EP_ID)), ("DELETE", EP_ID, None),
        ("GET", EP_ID, body(EP_ID, "Deleting")), ("GET", EP_ID, error()),
        ("GET", ep2, error()),
        ("GET", ML_ID, body(ML_ID)), ("DELETE", ML_ID, None),
        ("GET", ML_ID, error()),
    ], ["resource", "--resource-type", ML, "--name", "aml"])
    assert status == 0
    writes = [call[1] for call in runner.calls if call[0] == "DELETE"]
    assert writes == [EP_ID, ML_ID]


@pytest.mark.parametrize("response", [
    error("AuthorizationFailed"), error(), {"value": None}, {},
    {"value": [body(EP_ID.replace("/aml/", "/other/"))]},
    {"value": [], "nextLink": "https://evil.example/endpoints"},
    {"value": [], "nextLink": f"https://management.azure.com{GROUP}/providers/{ML}/other/onlineEndpoints?api-version=2024-10-01"},
    {"value": [], "nextLink": f"https://management.azure.com{ENDPOINTS}?api-version=2099-01-01"},
])
def test_ml_child_list_failure_or_scope_escape_prevents_all_writes(response):
    status, runner, _ = invoke([
        ("GET", ML_ID, body(ML_ID)), ("GET", ENDPOINTS, response),
    ], ["resource", "--resource-type", ML, "--name", "aml"])
    assert status != 0
    assert all(call[0] == "GET" for call in runner.calls)


def test_ml_child_delete_failure_preserves_workspace():
    status, runner, _ = invoke([
        ("GET", ML_ID, body(ML_ID)), ("GET", ENDPOINTS, {"value": [body(EP_ID)]}),
        ("GET", EP_ID, body(EP_ID)), ("DELETE", EP_ID, error("ScopeLocked")),
    ], ["resource", "--resource-type", ML, "--name", "aml"])
    assert status != 0
    assert not any(call[:2] == ("DELETE", ML_ID) for call in runner.calls)


def test_ml_later_page_failure_prevents_deletion_of_earlier_page_children():
    link = f"https://management.azure.com{ENDPOINTS}?api-version=2024-10-01&$skiptoken=2"
    status, runner, _ = invoke([
        ("GET", ML_ID, body(ML_ID)),
        ("GET", ENDPOINTS, {"value": [body(EP_ID)], "nextLink": link}),
        ("GET", ENDPOINTS, error("AuthorizationFailed")),
    ], ["resource", "--resource-type", ML, "--name", "aml"])
    assert status != 0 and all(call[0] == "GET" for call in runner.calls)


def test_pagination_cycle_is_failure_without_writes():
    first = f"https://management.azure.com{ENDPOINTS}?api-version=2024-10-01"
    status, runner, _ = invoke([
        ("GET", ML_ID, body(ML_ID)), ("GET", ENDPOINTS, {"value": [], "nextLink": first}),
    ], ["resource", "--resource-type", ML, "--name", "aml"])
    assert status != 0 and all(call[0] == "GET" for call in runner.calls)


def test_group_requires_exact_confirmation_before_any_command():
    with pytest.raises(SystemExit):
        deletion.main(["--subscription", SUB, "--resource-group", RG, "group"])
    assert deletion.main(["--subscription", SUB, "--resource-group", RG,
                          "group", "--confirm-resource-group", "other"]) != 0


def test_group_absent_is_success_without_inventory():
    status, runner, _ = invoke([("GET", GROUP, error("ResourceGroupNotFound"))], GROUP_ARGS)
    assert status == 0 and len(runner.calls) == 1


def test_group_already_deleting_only_polls():
    status, runner, _ = invoke([
        ("GET", GROUP, body(GROUP, "Deleting")), ("GET", GROUP, error("ResourceGroupNotFound")),
    ], GROUP_ARGS)
    assert status == 0 and all(call[0] == "GET" for call in runner.calls)


def test_group_waits_for_databricks_before_single_group_submission():
    status, runner, _ = invoke([
        ("GET", GROUP, body(GROUP)), ("LIST", GROUP, [body()]),
        ("GET", DBX_ID, body(state="Deleting")), ("GET", DBX_ID, error()),
        ("GET", GROUP, body(GROUP)), ("DELETE-GROUP", GROUP, None),
        ("GET", GROUP, body(GROUP)), ("GET", GROUP, body(GROUP, "Deleting")),
        ("GET", GROUP, error("ResourceGroupNotFound")),
    ], GROUP_ARGS)
    assert status == 0
    assert [call[0] for call in runner.calls].count("DELETE-GROUP") == 1
    assert not any(call[0] == "DELETE" for call in runner.calls)


@pytest.mark.parametrize("state", ["Succeeded", "Failed"])
def test_group_rollback_fails_immediately_preserving_primary_diagnostic(state, capsys, report_dir):
    status, runner, clock = invoke([
        ("GET", GROUP, body(GROUP, "Deleting")), ("GET", GROUP, body(GROUP, state)),
        ("LIST", GROUP, [body(state="Deleting")]),
        ("ACTIVITY", GROUP, error("AuthorizationFailed")),
    ], GROUP_ARGS, report_dir=report_dir)
    assert status != 0 and clock.now < 12
    assert all(call[0] != "DELETE-GROUP" for call in runner.calls)
    report = json.loads((report_dir / "last-deletion.json").read_text())
    assert report["status"] == "failed"
    assert "rollback" in report["error"]["message"].lower()
    assert DBX_ID in json.dumps(report)
    assert "rollback" in capsys.readouterr().err.lower()


def test_group_rollback_diagnostics_accept_real_ancillary_alert_name(report_dir):
    alert = GROUP + "/providers/Microsoft.AlertsManagement/smartDetectorAlertRules/Failure Anomalies - ain-prj002-sdc-dev-bltsc-001"
    status, _, _ = invoke([
        ("GET", GROUP, body(GROUP, "Deleting")), ("GET", GROUP, body(GROUP)),
        ("LIST", GROUP, [body(alert)]), ("ACTIVITY", GROUP, []),
    ], GROUP_ARGS, report_dir=report_dir)
    assert status != 0
    report = json.loads((report_dir / "last-deletion.json").read_text())
    assert report["diagnostics"][0]["remaining"][0]["id"] == alert
    assert report["error"]["code"] == "GroupDeletionFailed"


def test_group_rejected_submission_is_failure_without_retry(capsys):
    status, runner, _ = invoke([
        ("GET", GROUP, body(GROUP)), ("LIST", GROUP, []),
        ("GET", GROUP, body(GROUP)),
        ("DELETE-GROUP", GROUP, error("ResourceGroupDeletionBlocked", "ApplianceBeingDeleted")),
    ], GROUP_ARGS)
    assert status != 0
    assert "ApplianceBeingDeleted" in capsys.readouterr().err
    assert len([c for c in runner.calls if c[0] == "DELETE-GROUP"]) == 1


def test_group_preflight_inventory_failure_prevents_delete():
    status, runner, _ = invoke([
        ("GET", GROUP, body(GROUP)), ("LIST", GROUP, error("AuthorizationFailed")),
    ], GROUP_ARGS)
    assert status != 0 and len(runner.calls) == 2


def test_group_preflight_cannot_outlive_databricks_deletion_deadline():
    status, runner, clock = invoke([
        ("GET", GROUP, body(GROUP)), ("LIST", GROUP, [body()]),
        ("GET", DBX_ID, body(state="Deleting")), ("GET", DBX_ID, body(state="Deleting")),
        ("GET", DBX_ID, body(state="Deleting")),
    ], GROUP_ARGS, timeout=4)
    assert status != 0 and clock.now == 4
    assert all(call[0] != "DELETE-GROUP" for call in runner.calls)


@pytest.mark.parametrize("response", [
    {**body(GROUP), "name": None},
    {**body(GROUP), "name": 4},
    {**body(), "properties": {"provisioningState": 4}},
])
def test_malformed_get_is_nonzero_with_failure_report(response, report_dir):
    resource_id = response["id"]
    status, _, _ = invoke([("GET", resource_id, response)],
                          GROUP_ARGS if resource_id == GROUP else RESOURCE, report_dir=report_dir)
    assert status != 0
    assert json.loads((report_dir / "last-deletion.json").read_text())["status"] == "failed"


def test_group_never_observed_deleting_times_out_without_repeating():
    status, runner, clock = invoke([
        ("GET", GROUP, body(GROUP)), ("LIST", GROUP, []), ("GET", GROUP, body(GROUP)),
        ("DELETE-GROUP", GROUP, None),
        ("GET", GROUP, body(GROUP)), ("GET", GROUP, body(GROUP)),
    ], GROUP_ARGS, timeout=4)
    assert status != 0 and clock.now == 4
    assert len([c for c in runner.calls if c[0] == "DELETE-GROUP"]) == 1


@pytest.mark.parametrize("name,expected", [
    ("snt-PRJ002-aca", 1), ("snt-prj0020-aca", 0), ("snt-prj003-aca", 0), ("shared", 0),
])
def test_network_exact_project_token_read_only(name, expected):
    status, runner, _ = invoke([
        ("GET", VNETS, {"value": [body(VNET)]}),
        ("GET", VNET + "/subnets", {"value": [body(VNET + "/subnets/" + name)]}),
        ("GET", NSGS, {"value": []}),
    ], NETWORK_ARGS)
    assert status == expected and all(call[0] == "GET" for call in runner.calls)


def test_network_nsg_pagination_detects_remaining_project_resource(capsys):
    next_link = f"https://management.azure.com{NSGS}?api-version=2024-05-01&$skiptoken=next"
    status, _, _ = invoke([
        ("GET", VNETS, {"value": []}),
        ("GET", NSGS, {"value": [body(NSGS + "/nsg-prj0020-aca")], "nextLink": next_link}),
        ("GET", NSGS, {"value": [body(NSGS + "/nsg-PRJ002-aca")]}),
    ], NETWORK_ARGS)
    assert status != 0
    assert "nsg-PRJ002-aca" in capsys.readouterr().err


@pytest.mark.parametrize("response", [
    error("AuthorizationFailed"), error("ResourceGroupNotFound"),
    {"value": [body(VNET.replace("/network/", "/other/"))]},
    {"value": [], "nextLink": f"https://management.azure.com{VNETS.replace('/network/', '/other/')}?api-version=2024-05-01"},
])
def test_network_inspection_errors_never_report_success(response):
    status, _, _ = invoke([("GET", VNETS, response)], NETWORK_ARGS)
    assert status != 0


def test_subnet_scope_cannot_escape_parent_vnet():
    status, _, _ = invoke([
        ("GET", VNETS, {"value": [body(VNET)]}),
        ("GET", VNET + "/subnets", {"value": [body(VNET.replace("/shared", "/other") + "/subnets/snt-prj002-aca")]}),
    ], NETWORK_ARGS)
    assert status != 0


def test_nsg_inspection_failure_is_not_hidden_by_empty_subnets():
    status, _, _ = invoke([
        ("GET", VNETS, {"value": []}), ("GET", NSGS, error("AuthorizationFailed")),
    ], NETWORK_ARGS)
    assert status != 0


def test_network_project_filter_applies_to_subnet_leaf_not_parent_vnet():
    vnet = VNETS + "/prj002-shared"
    subnet = body(vnet + "/subnets/other-project")
    subnet["name"] = "prj002-shared/other-project"
    status, _, _ = invoke([
        ("GET", VNETS, {"value": [body(vnet)]}),
        ("GET", vnet + "/subnets", {"value": [subnet]}),
        ("GET", NSGS, {"value": []}),
    ], NETWORK_ARGS)
    assert status == 0


def test_report_success_atomic_and_errors_redacted(report_dir):
    status, _, _ = invoke([("GET", DBX_ID, error())], RESOURCE, report_dir=report_dir)
    assert status == 0
    assert json.loads((report_dir / "last-deletion.json").read_text())["status"] == "succeeded"
    status, _, _ = invoke([
        ("GET", DBX_ID, error("AuthorizationFailed", "Bearer fake-secret access_token=abc sig=xyz")),
    ], RESOURCE, report_dir=report_dir)
    assert status != 0
    report = (report_dir / "last-deletion.json").read_text()
    assert "fake-secret" not in report and "=abc" not in report and "=xyz" not in report
    assert '"status": "failed"' in report
    assert not list(report_dir.glob("*.part"))


def test_quoted_secret_redaction_keeps_entire_value_private(report_dir):
    status, _, _ = invoke([
        ("GET", DBX_ID, error("AuthorizationFailed", 'client_secret="multiple word secret" password: "long secret text"')),
    ], RESOURCE, report_dir=report_dir)
    assert status != 0
    report = (report_dir / "last-deletion.json").read_text()
    assert "word secret" not in report and "secret text" not in report


@pytest.mark.parametrize("flag,value", [
    ("--timeout-seconds", "0"), ("--timeout-seconds", "nan"),
    ("--timeout-seconds", "999999999"), ("--poll-seconds", "-1"),
    ("--poll-seconds", "inf"),
])
def test_invalid_deadline_configuration_rejected_without_commands(flag, value):
    with pytest.raises(SystemExit):
        deletion.main(["--subscription", SUB, "--resource-group", RG, flag, value, *RESOURCE])


@pytest.mark.parametrize("arguments", [
    ["--subscription", "not-a-guid", "--resource-group", RG, *RESOURCE],
    ["--subscription", SUB, "--resource-group", "../other", *RESOURCE],
    ["--subscription", SUB, "--resource-group", RG, "resource", "--resource-type", DBX, "--name", "dbx/../../managed"],
    ["--subscription", SUB, "--resource-group", RG, "resource", "--resource-type", "Microsoft.Fake/things", "--name", "x"],
    ["--subscription", SUB, "--resource-group", RG, *NETWORK_ARGS[:-1], "0020"],
])
def test_unsafe_scope_or_type_rejected_without_commands(arguments):
    assert deletion.main(arguments) != 0


def test_windows_msi_cli_bypasses_batch_argument_interpretation(tmp_path):
    launcher = tmp_path / "wbin" / "az.cmd"
    launcher.parent.mkdir()
    launcher.write_text("@echo off", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.touch()
    assert deletion.cli_prefix(str(launcher), windows=True) == [str(python), "-IBm", "azure.cli"]
    assert deletion.cli_prefix(str(launcher), windows=False) == [str(launcher)]


def test_non_msi_cli_launcher_is_preserved(tmp_path):
    launcher = str(tmp_path / "bin" / "az.cmd")
    assert deletion.cli_prefix(launcher, windows=True) == [launcher]
