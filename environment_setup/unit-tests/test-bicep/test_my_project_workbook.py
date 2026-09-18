"""Offline compiled-workbook and SQL/KQL structural parity regressions.

These tests do not execute KQL in Azure or validate Portal rendering. The small
ARM evaluator materializes only the expression subset emitted by this workbook,
so assertions inspect the deployed serializedData, not an unconnected fixture.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[3]
BICEP = Path(os.environ.get("AIFACTORY_MY_PROJECT_BICEP_ROOT",
                           str(ROOT / "environment_setup" / "aifactory" / "bicep")))
MODULE = BICEP / "modules" / "myProjectWorkbook.bicep"
PROJECT = BICEP / "modules" / "projectDash01.bicep"
STAGE = BICEP / "esml-genai-1" / "10-aifactory-dashboards.bicep"
ASSETS = BICEP / "modules" / "workbooks" / "my-project"
RG = "/subscriptions/11111111-1111-4111-8111-111111111111/resourceGroups/project-001-test"
COMPONENT = RG + "/providers/Microsoft.Insights/components/project-insights"
WORKSPACE = RG.replace("project-001-test", "common-test") + "/providers/Microsoft.OperationalInsights/workspaces/shared"
WIRING = (
    "enableMyProjectDashboard", "myProjectApplicationInsightsResourceId",
    "myProjectLogAnalyticsResourceId", "myProjectFactoryId", "myProjectScaleSetId",
    "myProjectTelemetryEnvironment", "myProjectTimeZone", "myProjectCoverage",
    "myProjectStateHistoryDays",
)
OUTPUTS = ("myProjectWorkbookId", "myProjectWorkbookName", "myProjectWorkbookUrl", "myProjectSourceIds")


def compile_bicep(path):
    az = shutil.which("az")
    if not az:
        pytest.fail("Azure CLI/Bicep is required for compiled workbook regressions")
    command = [az]
    if os.name == "nt" and Path(az).suffix.lower() in (".cmd", ".bat"):
        cli_python = Path(az).resolve().parent.parent / "python.exe"
        assert cli_python.is_file(), "Expected installed Azure CLI Python runtime"
        command = [str(cli_python), "-X", "utf8", "-IBm", "azure.cli"]
    result = subprocess.run(
        [*command, "bicep", "build", "--file", str(path), "--no-restore", "--stdout"],
        cwd=ROOT, capture_output=True, encoding="utf-8", timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class Arm:
    def __init__(self, template, overrides=None):
        self.template = template
        self.params = {
            name: value.get("defaultValue")
            for name, value in template.get("parameters", {}).items()
        }
        self.params.update(overrides or {})
        self.cache = {}
        self.index = {}

    def variable(self, name):
        if name not in self.cache:
            copies = {entry["name"]: entry for entry in self.template["variables"].get("copy", [])}
            if name in copies:
                entry = copies[name]
                result = []
                for index in range(self.value(entry["count"])):
                    self.index[name] = index
                    result.append(self.value(entry["input"]))
                self.cache[name] = result
            else:
                self.cache[name] = self.value(self.template["variables"][name])
        return self.cache[name]

    def value(self, value):
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if not isinstance(value, str) or not value.startswith("[") or not value.endswith("]"):
            return value
        text = value[1:-1]
        pos = 0

        def parse():
            nonlocal pos
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if text[pos] == "'":
                pos += 1
                out = ""
                while True:
                    if text[pos] == "'":
                        pos += 1
                        if pos < len(text) and text[pos] == "'":
                            out += "'"
                            pos += 1
                            continue
                        break
                    out += text[pos]
                    pos += 1
            elif text[pos].isdigit() or text[pos] == "-":
                match = re.match(r"-?\d+", text[pos:])
                out = int(match[0])
                pos += len(match[0])
            else:
                match = re.match(r"[A-Za-z_][A-Za-z_0-9]*", text[pos:])
                assert match, text[pos:pos + 100]
                name = match[0]
                pos += len(name)
                assert text[pos] == "(", text[pos:pos + 100]
                pos += 1
                args = []
                while text[pos] != ")":
                    args.append(parse())
                    while text[pos].isspace():
                        pos += 1
                    if text[pos] != ",":
                        break
                    pos += 1
                assert text[pos] == ")"
                pos += 1
                out = self.call(name, args)
            while pos < len(text) and text[pos] in ".[":
                if text[pos] == ".":
                    pos += 1
                    match = re.match(r"[A-Za-z_][A-Za-z_0-9]*", text[pos:])
                    pos += len(match[0])
                    out = out[match[0]]
                else:
                    pos += 1
                    key = parse()
                    assert text[pos] == "]"
                    pos += 1
                    out = out[key]
            return out

        result = parse()
        assert not text[pos:].strip(), text[pos:pos + 100]
        return result

    def call(self, name, args):
        name = name.lower()
        if name == "variables":
            return self.variable(args[0])
        if name == "parameters":
            return self.value(self.params[args[0]])
        if name == "copyindex":
            return self.index[args[0]]
        if name == "createarray":
            return args
        if name == "createobject":
            return dict(zip(args[::2], args[1::2]))
        if name == "concat":
            return sum(args, []) if isinstance(args[0], list) else "".join(args)
        if name == "union":
            result = {}
            for arg in args:
                result.update(arg)
            return result
        if name == "string":
            return args[0] if isinstance(args[0], str) else json.dumps(args[0], separators=(",", ":"), ensure_ascii=False)
        if name == "json":
            return json.loads(args[0])
        if name == "format":
            return args[0].format(*args[1:])
        if name == "replace":
            return args[0].replace(args[1], args[2])
        if name == "base64":
            return base64.b64encode(args[0].encode()).decode()
        if name == "length":
            return len(args[0])
        if name in ("toupper", "tolower"):
            return args[0].upper() if name == "toupper" else args[0].lower()
        if name == "uricomponent":
            return quote(args[0], safe="")
        if name == "resourcegroup":
            return {"id": RG}
        if name == "tenant":
            return {"tenantId": "22222222-2222-4222-8222-222222222222"}
        if name == "resourceid":
            return RG + "/providers/" + args[0] + "/" + args[1]
        if name == "guid":
            # ARM's documented namespace and separator.
            return str(uuid.uuid5(uuid.UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830"), "-".join(args)))
        if name in ("true", "false"):
            return name == "true"
        if name == "equals":
            return args[0] == args[1]
        if name == "if":
            return args[1] if args[0] else args[2]
        raise AssertionError(f"Unsupported ARM expression: {name}")


@pytest.fixture(scope="module")
def compiled():
    return compile_bicep(STAGE)


@pytest.fixture(scope="module")
def project_template(compiled):
    return next(r for r in compiled["resources"] if r["type"] == "Microsoft.Resources/deployments")["properties"]["template"]


@pytest.fixture(scope="module")
def workbook_template(project_template):
    return next(
        r for r in project_template["resources"]
        if r["type"] == "Microsoft.Resources/deployments" and "my-project-workbook" in r["name"]
    )["properties"]["template"]


def materialize(template, **overrides):
    arm = Arm(template, {
        "location": "swedencentral", "projectNumber": "001", "env": "test",
        "telemetryEnvironment": "stage", "applicationInsightsResourceId": COMPONENT,
        "logAnalyticsResourceId": WORKSPACE, "projectResourceGroupId": RG, **overrides,
    })
    return arm, json.loads(arm.value(template["resources"][0]["properties"]["serializedData"]))


@pytest.fixture(scope="module")
def workbook(workbook_template):
    return materialize(workbook_template)[1]


def items(workbook):
    return {item["name"]: item for item in workbook["items"]}


def parameters(workbook):
    return {
        p["name"]: p for item in workbook["items"] if item["type"] == 9
        for p in item["content"]["parameters"]
    }


def test_only_saved_workbook_and_deterministic_name(workbook_template):
    assert [r["type"] for r in workbook_template["resources"]] == ["Microsoft.Insights/workbooks"]
    arm, _ = materialize(workbook_template)
    expected = arm.variable("workbookName")
    assert expected == materialize(workbook_template)[0].variable("workbookName")
    assert expected != materialize(workbook_template, projectNumber="002")[0].variable("workbookName")
    assert expected != materialize(workbook_template, env="prod")[0].variable("workbookName")
    assert expected == materialize(workbook_template, telemetryEnvironment="custom")[0].variable("workbookName")
    assert "guid(resourceGroup().id, 'aifactory.my-project.v1'" in workbook_template["variables"]["workbookName"]
    assert arm.value(workbook_template["resources"][0]["properties"]["sourceId"]) == COMPONENT


def test_enable_disable_and_stage_outputs(compiled, project_template):
    deployment = next(r for r in project_template["resources"] if "my-project-workbook" in r["name"])
    assert deployment["condition"] == "[parameters('enableMyProjectDashboard')]"
    for template in (compiled, project_template):
        assert template["parameters"]["enableMyProjectDashboard"]["defaultValue"] is True
        assert template["parameters"]["myProjectFactoryId"]["defaultValue"] == ""
        assert template["parameters"]["myProjectScaleSetId"]["defaultValue"] == ""
        assert template["parameters"]["myProjectCoverage"]["defaultValue"] == {}
        for output in OUTPUTS:
            assert output in template["outputs"]
    for output in OUTPUTS:
        assert "if(parameters('enableMyProjectDashboard')" in project_template["outputs"][output]["value"]
    stage_deployment = next(r for r in compiled["resources"] if r["type"] == "Microsoft.Resources/deployments")
    for param in WIRING:
        assert stage_deployment["properties"]["parameters"][param]["value"] == f"[parameters('{param}')]"
    assert "myProjectWorkbookUrl" in compiled["outputs"]["dashboardOutputs"]["value"]
    assert "myProjectWorkbookUrl" in compiled["outputs"]["dashboardAccess"]["value"]
    assert Arm(compiled, {"env": "test"}).value(compiled["parameters"]["myProjectTelemetryEnvironment"]["defaultValue"]) == "stage"


def test_naming_outputs_scope_and_override_wiring(project_template):
    deployment = next(r for r in project_template["resources"] if "my-project-workbook" in r["name"])
    wired = deployment["properties"]["parameters"]
    insights = json.dumps(wired["applicationInsightsResourceId"])
    workspace = json.dumps(wired["logAnalyticsResourceId"])
    assert "applicationInsightName" in insights
    assert "laWorkspaceName" in workspace
    assert "commonResourceGroupName" in workspace
    assert "rgResourceId" in insights
    assert "myProjectApplicationInsightsResourceId" in insights
    assert "myProjectLogAnalyticsResourceId" in workspace
    text = MODULE.read_text(encoding="utf-8")
    assert "listKeys" not in text and "listSecrets" not in text


def test_dashboard_existing_layout_and_native_cost_preserved():
    text = PROJECT.read_text(encoding="utf-8")
    for position in (
        "x: 0, y: 0, colSpan: 12, rowSpan: 2",
        "x: 0, y: 2, colSpan: 6, rowSpan: 8",
        "x: 6, y: 2, colSpan: 6, rowSpan: 8",
        *(f"x: {x}, y: 10, colSpan: 1, rowSpan: 1" for x in range(4)),
        "x: 0, y: 11, colSpan: 12, rowSpan: 8",
        "x: 0, y: 19, colSpan: 12, rowSpan: 3",
    ):
        assert position in text
    assert "], myProjectEntryParts)" in text
    assert "var myProjectEntryParts = enableMyProjectDashboard ?" in text
    assert "Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/" in text
    assert "[📊 Open Cost Analysis](${costAnalysisUrl}" in text


def test_workbook_schema_shapes_and_real_query_items(workbook):
    assert workbook["version"] == "Notebook/1.0"
    assert workbook["fallbackResourceIds"] == [WORKSPACE]
    all_items = items(workbook)
    assert len(all_items) == len(workbook["items"])
    assert len(all_items) >= 20
    for item in all_items.values():
        assert item["type"] in (1, 3, 9, 10)
        if item["type"] != 3:
            continue
        content = item["content"]
        assert content["version"] == "KqlItem/1.0"
        assert content["queryType"] == 0
        assert content["crossComponentResources"] == [WORKSPACE]
        assert content["resourceType"] == "microsoft.operationalinsights/workspaces"
        assert content["timeContext"] == {"durationMs": 0}
        assert content["visualization"] in ("table", "tiles", "timechart")
        assert content["query"]
        if content["visualization"] == "timechart":
            assert content["chartSettings"]["xAxis"] == "Day"
            assert isinstance(content["chartSettings"]["yAxis"], list)
        if content["visualization"] == "tiles":
            for field in ("titleContent", "leftContent", "subtitleContent", "secondaryContent"):
                assert content["tileSettings"][field]["formatter"] == 1
    formatter = all_items["source-links"]["content"]["gridSettings"]["formatters"][0]
    assert formatter == {"columnMatch": "Source", "formatter": 1, "formatOptions": {"linkColumn": "Url", "linkTarget": "Url"}}
    assert "__COMPONENT__" not in json.dumps(workbook)
    assert "__HISTORY_DAYS__" not in json.dumps(workbook)


def test_templates_scope_selection_and_coverage_defaults(workbook):
    params = parameters(workbook)
    assert params["Template"]["value"] == "retail-chat"
    assert {v["value"] for v in json.loads(params["Template"]["jsonData"])} == {"retail-chat", "booking-chat", "support-chat"}
    assert {v["label"] for v in json.loads(params["Navigation"]["jsonData"])} == {"Usage & outcomes", "Cost", "Model tokens"}
    assert params["Store"]["value"] == "All"
    for name in ("Factory", "ScaleSet"):
        assert params[name]["isRequired"]
        assert params[name]["value"] == ""
        assert "AppEvents" in params[name]["query"]
        assert "tostring(Properties['project'])" in params[name]["query"]
        assert "tostring(Properties.environment)" in params[name]["query"]
        assert "tolower(_ResourceId) ==" in params[name]["query"]
    assert "{Factory:base64}" in params["ScaleSet"]["query"]
    for name in ("Questions", "Devices", "Feedback", "Cart", "Bookings", "Cases", "StateBaseline", "Metering", "Billing"):
        assert params[name + "Complete"]["value"] == "false"
    assert "Project" not in params and "Environment" not in params


def test_opaque_identifiers_and_query_substitution(workbook_template):
    factory = "factory:/canonical/path:'quoted'\\name"
    scale_set = "scale:canonical:/id"
    _, workbook = materialize(workbook_template, factoryId=factory, scaleSetId=scale_set)
    params = parameters(workbook)
    assert params["Factory"]["value"] == factory
    assert params["ScaleSet"]["value"] == scale_set
    assert base64.b64encode(factory.encode()).decode() in params["Factory"]["query"]
    assert factory not in params["Factory"]["query"]
    for item in workbook["items"]:
        for query in ([item["content"]["query"]] if item["type"] == 3 else []):
            tokens = re.findall(r"\{([A-Za-z]+)(?::([^}]+))?\}", query)
            assert all(name in params and (formatting == "base64" or
                       (name == "TokenTimeRange" and formatting in ("start", "end")))
                       for name, formatting in tokens)
    query = items(workbook)["common-cards"]["content"]["query"]
    assert base64.b64encode(COMPONENT.encode()).decode() in query
    assert "let Project = base64_decode_tostring('MDAx')" in query
    assert "let Environment = base64_decode_tostring('c3RhZ2U=')" in query


def test_shared_metric_queries_are_template_independent(workbook):
    for name in ("common-cards", "conversations-questions-daily", "feedback-daily", "questions-per-conversation-daily"):
        query = items(workbook)[name]["content"]["query"]
        assert "{Template" not in query
        assert "dcount" not in query.lower()
        assert "count_distinct" not in query.lower()  # exact summarize/distinct/count without approximation limits
    query = items(workbook)["common-cards"]["content"]["query"]
    for field in ("event_id", "question_id", "conversation_id", "device_id", "rating", "quantity", "entity_id", "status"):
        assert "Properties." + field in query
    for forbidden in ("Properties.prompt", "Properties.phone", "Properties.client_IP", "Properties.message", "Properties.completion"):
        assert forbidden not in query
    assert "| project-away event_id\n    | distinct *" in query.replace("\r\n", "\n")
    assert "Single-question rate (not abandonment)" in query
    assert "Q and DevicesComplete and QuestionsWithDevice == QuestionCount" in query
    assert "Q and F" in query
    assert "Questions >= 3" in query
    assert "LatestStates" in query and "StateBaselineComplete" in query


def test_filters_precede_aggregation_and_conflicts_reject(workbook):
    for name in ("common-cards", "cost-summary"):
        query = items(workbook)[name]["content"]["query"]
        aggregation = query.index("| summarize")
        for required in (
            "tolower(_ResourceId) == tolower(Component)", "tostring(Properties.factory) == Factory",
            "tostring(Properties.environment) == Environment", "Store == 'All' or store == Store",
        ):
            assert query.index(required) < aggregation
        assert "Variants > 1" in query
    usage = items(workbook)["common-cards"]["content"]["query"]
    assert usage.index("let UsageValid") < usage.index("summarize arg_max")
    assert "QuestionConflicts == 0 and VoteConflicts == 0 and StateConflicts == 0" in usage
    assert "item_count != 1" in usage
    assert "summarize Variants = count() by store, event_id" in usage


def test_local_calendar_dates_dense_days_and_dst(workbook):
    params = parameters(workbook)
    assert {x["value"] for x in json.loads(params["DatePreset"]["jsonData"])} == {"1", "7", "30", "custom"}
    query = items(workbook)["common-cards"]["content"]["query"]
    assert "datetime_utc_to_local" in query and "datetime_local_to_utc" in query
    assert "between (0 .. 29)" in query
    assert "LastLocalDate + 1d, Zone" in query
    assert "range Offset from 0 to 29 step 1" in query
    assert "iff(Q, toreal(coalesce(Questions, 0)), real(null))" in query
    assert "iff(d > 0.0, n / d, real(null))" in query
    assert "timeZoneOffset" not in query and "offsetHours" not in query
    zone = ZoneInfo("Europe/Berlin")
    for start, end, hours in (("2026-03-29", "2026-03-30", 23), ("2026-10-25", "2026-10-26", 25)):
        bounds = [datetime.fromisoformat(day).replace(tzinfo=zone).astimezone(timezone.utc) for day in (start, end)]
        assert (bounds[1] - bounds[0]).total_seconds() / 3600 == hours


def test_cost_basis_currency_privacy_attribution_and_explicit_rates(workbook):
    query = items(workbook)["cost-summary"]["content"]["query"]
    for expected in (
        "Name == 'aifactory.chat.meter'", "quantity * unit_price / price_unit_quantity",
        "Concrete(rate_reference)", "Concrete(evidence_reference)", "Concrete(allocation_method)",
        "Concrete(billing_reference)", "Concrete(attribution_reference)", "by basis, currency",
        "^session_[A-Za-z0-9_-]{8,64}$", "^ipkey_[0-9a-f]{32,64}$",
        "not(HasRawIP(", "CostConflicts == 0 and InvalidCosts == 0",
        "iff(isempty(session_key), 'Unattributed', session_key)",
        "iff(isempty(network_key), 'Unattributed', network_key)",
        "distinct store, session_key, basis, currency", "iff(basis == 'estimated', MeteringComplete, BillingComplete)",
        "meter == 'audio_input_seconds' and unit == 'seconds'",
        "meter == 'audio_output_characters' and unit == 'characters'",
        "unit == 'tokens' and charge_type == 'paygo'",
    ):
        assert expected in query
    assert "Properties.client_IP" not in query and "Properties.ip" not in query
    assert not re.search(r"unit_price\s*=\s*(?:decimal\()?[\d.]+", query)
    assert "dcount(" not in query
    for name in ("cost-daily", "cost-service-daily"):
        assert "Currency == base64_decode_tostring('{ChartCurrency:base64}')" in items(workbook)[name]["content"]["query"]
    for name in ("session-daily", "network-daily", "meter-details"):
        tail = items(workbook)[name]["content"]["query"].split("let DailyServiceCosts", 1)[1]
        assert "currency" in tail and "basis" in tail


def test_sql_structural_parity_exact_cohorts_and_duplicate_conflicts(workbook):
    """Independent relational cases document intended KQL semantics, not cloud execution."""
    db = sqlite3.connect(":memory:")
    db.execute("create table events(event_id, day, store, conversation, question, device)")
    rows = [
        ("q1", "2026-09-01", "A", "one", "1", "d1"),
        ("q1", "2026-09-01", "A", "one", "1", "d1"),
        ("q2", "2026-09-02", "A", "one", "2", "d1"),
        ("q3", "2026-09-02", "B", "one", "1", "d2"),
    ]
    db.executemany("insert into events values (?,?,?,?,?,?)", rows)
    db.execute("create view exact as select distinct * from events")
    period = db.execute("select count(*) from (select distinct store,conversation from exact)").fetchone()[0]
    daily = db.execute("select day,count(*) from (select distinct day,store,conversation from exact) group by day").fetchall()
    assert period == 2 and sum(count for _, count in daily) == 3
    assert db.execute("select count(*) from exact").fetchone()[0] == 3
    db.execute("insert into events values ('q1','2026-09-01','A','other','1','d1')")
    assert db.execute("select event_id from (select distinct * from events) group by event_id having count(*)>1").fetchall() == [("q1",)]
    query = items(workbook)["common-cards"]["content"]["query"]
    assert "summarize Questions = count() by store, conversation_id" in query
    assert "distinct Day, store, conversation_id | summarize Conversations = count() by Day" in query
    db.close()


def test_native_token_metrics_are_real_scoped_controls_and_not_alias_sums(workbook):
    params = parameters(workbook)
    native = [item for item in workbook["items"] if item["type"] == 10]
    assert len(native) == 5
    for item in native:
        content = item["content"]
        assert content["version"] == "MetricsItem/2.0"
        assert content["resourceType"] == "microsoft.cognitiveservices/accounts"
        assert content["resourceIds"] == ["{TokenMetricAccount}"]
        assert content["resourceParameter"] == "TokenMetricAccount"
        assert content["resourceLimit"] == 1
        assert content["timeContextFromParameter"] == "TokenTimeRange"
        assert content["chartType"] in (0, 2)
        assert item["conditionalVisibility"]["parameterName"] == "TokenMetricView"
        for metric in content["metrics"]:
            assert metric["aggregation"] == 1  # Total, not Count/Average
            assert metric["namespace"] == content["resourceType"]
            assert metric["splitByLimit"] == 100
            assert not metric.get("filters")
            if "openai" in item["name"]:
                assert metric["splitBy"] == ["ModelDeploymentName", "ModelVersion"]
                assert metric["metric"].endswith(("-ProcessedPromptTokens", "-GeneratedTokens"))
            else:
                assert metric["splitBy"] == ["ModelDeploymentName", "ModelName", "ModelVersion"]
                assert metric["metric"].endswith(("-InputTokens", "-OutputTokens", "-cacheReadInputTokens"))
    assert params["TokenMetricProfile"]["value"] == "foundry"
    assert {x["value"] for x in json.loads(params["TokenMetricProfile"]["jsonData"])} == {"foundry", "openai"}
    assert params["TokenTimeRange"]["value"] == {"durationMs": 604800000}
    assert params["TokenMetricAccount"]["type"] == 5
    assert params["TokenMetricAccount"]["queryType"] == 1
    assert 'id =~ "{TokenAccount:escapejson}"' in params["TokenMetricAccount"]["query"]
    assert "AccountSelected and WindowValid" in params["TokenMetricView"]["query"]
    assert "Navigation:base64" in params["TokenMetricView"]["query"]
    assert "Profile in ('foundry', 'openai')" in params["TokenMetricView"]["query"]
    assert "CacheRate" not in json.dumps(native)


def test_token_inventory_exact_rg_kinds_and_parameter_fail_closed(workbook):
    params = parameters(workbook)
    prefix = RG.lower() + "/providers/microsoft.cognitiveservices/accounts/"
    for name in ("TokenAccount", "TokenAccountInventory", "TokenMetricAccount"):
        param = params[name]
        assert param["queryType"] == 1
        assert param["resourceType"] == "microsoft.resourcegraph/resources"
        assert param["crossComponentResources"] == [RG]
        assert f"tolower(id) startswith '{prefix}'" in param["query"]
        assert "array_length(split(id, '/')) == 9" in param["query"]
        assert "['kind'] in~ ('AIServices', 'OpenAI')" in param["query"]
        assert "type =~ 'microsoft.cognitiveservices/accounts'" in param["query"]
        assert not param["typeSettings"]["additionalResourceOptions"]
    assert params["TokenAccount"]["type"] == 5
    assert params["TokenAccount"]["isRequired"] and not params["TokenAccount"]["multiSelect"]
    assert params["TokenAccount"]["value"] == ""
    query = items(workbook)["tokens-log-model-totals"]["content"]["query"]
    assert "AccountId startswith AccountPrefix" in query
    assert "substring(AccountId, strlen(AccountPrefix)) !contains '/'" in query
    assert "AccountId in (Inventory | project AccountId)" in query
    assert "AccountId == SelectedAccount" in query
    assert "isnotempty(SelectedAccount)" in query
    assert "tostring(Accounts['kind'])" in query
    assert "Accounts.kind" not in query
    for forbidden in ("{Factory", "{ScaleSet", "{Store", "{DatePreset", "{FromDate", "{ToDate", "Complete:base64", "aifactory.chat"):
        assert forbidden not in query
    assert "EndUtc - StartUtc <= 31d" in query
    assert "SafeZone = iff(ZoneValid, Zone, 'UTC')" in query
    assert "TimeGenerated >= StartUtc and TimeGenerated < EndUtc" in query
    # Neighbour RGs, child resources, blank and wildcard selections cannot match.
    valid = prefix + "actual-account"
    inventory = {valid}
    def scoped(value):
        value = value.lower()
        return (value.startswith(prefix) and "/" not in value[len(prefix):] and value in inventory)
    assert scoped(valid.upper())
    assert not any(scoped(value) for value in ("", "*", RG + "-other/providers/microsoft.cognitiveservices/accounts/a",
                                              valid + "/deployments/model", valid + "-other"))


def test_token_request_usage_nulls_privacy_and_explicit_source_separation(workbook):
    all_items = items(workbook)
    query = all_items["tokens-log-model-totals"]["content"]["query"]
    assert "Category == 'AzureOpenAIRequestUsage'" in query
    assert "column_ifexists('properties_s', '')" in query
    assert "tostring(Response.usage)" in query
    assert "U.prompt_tokens_details.cached_tokens" in query
    assert "U.input_tokens_details.cached_tokens" in query
    assert "by AccountId, Day, Deployment, ModelName, ModelVersion" in query
    assert "iff(IdentityValid and MissingCached == 0, CachedSum, long(null))" in query
    assert "MissingCached > 0, 'Partial — cached total withheld'" in query
    assert "Variants > 1" in query
    assert "IdentityValid=ConflictingRecords == 0 and InvalidRecords == 0" in query
    assert "rows without request identity retained" in query
    assert "ModelKey=tostring(pack_array(ModelName, ModelVersion))" in query
    assert "base64_decode_tostring('{TokenDeployment:base64}')" in query
    assert "base64_decode_tostring('{TokenModel:base64}')" in query
    assert "ModelName=coalesce" in query
    assert "ModelName=Deployment" not in query
    assert "https://portal.azure.com/#resource" in query
    assert "url_encode_component(Deployment)" in query
    for forbidden in ("AppEvents", "AppDependencies", "AzureMetrics", "CacheRate", "coalesce(CachedTokens, 0)",
                      "U.prompt_tokens, 0", "RequestResponse\n"):
        assert forbidden not in query.replace("// Access/query errors are not suppressed. No AppDependencies, RequestResponse or metrics union.", "")
    # No raw request fields survive normalization; RequestId is internal only.
    projection = query.split("| project Day=startofday", 1)[1].split("| serialize", 1)[0]
    for forbidden in ("Response", "ResponseBody", " P,", "Extra", "prompt", "client_IP"):
        assert forbidden not in projection
    final_projection = query.split("| project Account, AccountId", 1)[1].split(";", 1)[0]
    assert "RequestId," not in final_projection.replace("MissingRequestId,", "")
    assert "CachedCoverage" in final_projection and "Deduplication" in final_projection
    assert all_items["tokens-log-daily"]["content"]["visualization"] == "timechart"
    assert "datetime_utc_to_local(TimeGenerated, SafeZone)" in query
    assert all_items["tokens-log-validation"]["content"]["query"].endswith(
        "'Observed request logs only; missing fields/series are not measured zero')")
    notice = all_items["tokens-notice"]["content"]["json"]
    for expected in ("never added together", "Unavailable, not zero", "never add input + cached",
                     "request logs", "not billable cost", "supported-metrics", "prompt-caching"):
        assert expected in notice


def test_native_token_dashboard_direct_link_and_no_live_fixture_ids(workbook_template):
    text = PROJECT.read_text(encoding="utf-8")
    assert "x: 0, y: 22, colSpan: 12, rowSpan: 3" in text
    assert "myProjectWorkbook!.outputs.tokensUrl" in text
    arm, workbook = materialize(workbook_template)
    url = arm.value(workbook_template["outputs"]["tokensUrl"]["value"])
    assert "/WorkbookViewerBlade/" in url
    assert "/ConfigurationId/" + quote(arm.variable("workbookId"), safe="") in url
    assert "/NotebookParams/" + quote('{"Navigation":"tokens"}', safe="") in url
    text = json.dumps(workbook)
    assert "__PROJECT_RG__" not in text and "__ACCOUNT_PREFIX__" not in text
    for live_identifier in ("aif2bltscaae001dev", "e0ad3e19-1d5a-4f2b-9974-3f098dc7fd62",
                            "349658", "27795", "2025-11-13"):
        assert live_identifier not in text


def test_verified_flat_token_schema_and_independent_log_freshness(workbook):
    all_items = items(workbook)
    query = all_items["tokens-log-model-totals"]["content"]["query"]
    input_mapping = query.split("InputRaw=coalesce", 1)[1].split("OutputRaw=", 1)[0]
    output_mapping = query.split("OutputRaw=coalesce", 1)[1].split("CachedRaw=", 1)[0]
    cached_mapping = query.split("CachedRaw=coalesce", 1)[1].split("| extend InputValues", 1)[0]
    assert "P.promptTokens" in input_mapping
    assert "P.generatedTokens" in output_mapping
    assert "P.cachedTokens" in cached_mapping
    assert "pack_array(column_ifexists('generatedTokens_d', real(null)))[0]" in output_mapping
    for field in ("modelDeploymentName", "modelName", "modelVersion"):
        assert f"tostring(P.{field})" in query
    assert "FirstObservedUtc=min(TimeGenerated), LastObservedUtc=max(TimeGenerated)" in query
    assert "FirstObservedUtc=min(FirstObservedUtc), LastObservedUtc=max(LastObservedUtc)" in query
    assert "LastObservationAge=now() - LastObservedUtc" in query
    assert "GapToWindowEnd=EndUtc - LastObservedUtc" in query
    validation = all_items["tokens-log-validation"]["content"]["query"]
    assert "LastObservedUtc=max(LastObservedUtc)" in validation
    assert "GapToWindowEnd=EndUtc - LastObservedUtc" in validation
    notice = all_items["tokens-log-schema-and-freshness"]["content"]["json"]
    assert "Native Metrics may have newer observations than request logs" in notice
    assert "missing cached field remains null" in notice
    assert "do not require nested" in notice


def test_token_scalar_and_array_normalization_contract(workbook):
    """Reference cases for the emitted KQL; live Kusto execution is a separate validation."""
    def normalized(raw):
        if raw is None:
            return None
        values = raw if isinstance(raw, list) else [raw]
        if not values or any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or value != math.floor(value)
            for value in values
        ):
            return None
        total = sum(values)
        return int(total) if math.isfinite(total) and total < 2**63 else None

    # Customer schema shape; these values are test inputs, never workbook data.
    flat = {"promptTokens": [2518], "generatedTokens": [124], "cachedTokens": [0]}
    assert tuple(normalized(flat[field]) for field in flat) == (2518, 124, 0)
    assert normalized([100, 20, 3]) == 123
    assert normalized([0, 0]) == normalized(0) == 0
    assert normalized(123) == normalized([123.0]) == 123
    for missing_or_invalid in (None, [], [None], [100, None], [1, -1], -1, [0.5],
                               [float("nan")], [float("inf")], [True], ["100"], [[100]], [2**63]):
        assert normalized(missing_or_invalid) is None
    query = items(workbook)["tokens-log-model-totals"]["content"]["query"]
    assert "gettype(v) == 'array' and array_length(v) > 0" in query
    assert "v, pack_array(v)" in query  # Empty/missing rows are retained, not mv-expanded away.
    assert "or not(isfinite(n))" in query
    assert "n < 0 or n != floor(n, 1.0)" in query
    for field in ("Input", "Output", "Cached"):
        assert f"mv-apply Element={field}Values" in query
        assert f"Invalid{field}Elements=countif(InvalidTokenElement(Element))" in query
        assert f"iff(Invalid{field}Elements == 0, toreal(array_sum({field}Values)), real(null))" in query
        assert f"isnotnull({field}Raw)" in query
        assert f"isnull(tolong({field}Value))" in query
    for field in flat:
        assert f"toreal(P.{field})" not in query


def test_sql_token_partial_cache_and_inclusive_input_semantics():
    """Independent relational regression, not claimed to execute KQL or validate Azure UI."""
    db = sqlite3.connect(":memory:")
    db.executescript("""
        create table tokens(deployment, model, version, request_id, input, output, cached);
        insert into tokens values
          ('prod', 'model-a', 'v1', 'r1', 100, 20, null),
          ('prod', 'model-a', 'v1', 'r1', 100, 20, null),
          ('prod', 'model-a', 'v1', 'r2', 200, 30, 0),
          ('prod', 'model-a', 'v2', 'r3', 50, 10, 25),
          ('other', 'model-a', 'v1', 'r4', 60, 15, 0);
        create view distinct_requests as select distinct * from tokens;
    """)
    rows = db.execute("""
        select deployment,model,version,sum(input),sum(output),
          case when count(cached)=count(*) then sum(cached) else null end
        from distinct_requests group by deployment,model,version
    """).fetchall()
    assert ("prod", "model-a", "v1", 300, 50, None) in rows
    assert ("prod", "model-a", "v2", 50, 10, 25) in rows
    assert ("other", "model-a", "v1", 60, 15, 0) in rows
    assert sum(row[3] for row in rows) == 410  # Not 435: cached is already part of input.
    db.close()


def test_sql_structural_parity_latest_feedback_state_and_cost_separation(workbook):
    db = sqlite3.connect(":memory:")
    db.executescript("""
        create table votes(store,conversation,question,instant,rating);
        insert into votes values ('A','one','1',1,'down'),('A','one','1',2,'up'),('B','outside','1',2,'down');
        create table states(store,entity,instant,status);
        insert into states values ('A','old',1,'in_progress'),('A','done',2,'solved'),('A','future',99,'open');
        create table costs(basis,currency,session,quantity,unit_price,price_unit_quantity,amount);
        insert into costs values
          ('estimated','USD','session_abcdefgh',2000,3,1000000,null),
          ('actual','USD',null,1,null,null,4),
          ('allocated','USD',null,1,null,null,2),
          ('estimated','EUR',null,1000,4,1000000,null);
    """)
    latest = db.execute("""
        select rating,count(*) from (
            select *,row_number() over(partition by store,conversation,question order by instant desc) n from votes
        ) where n=1 group by rating
    """).fetchall()
    assert dict(latest) == {"down": 1, "up": 1}
    # Pre-window old entity survives as an active baseline; future state does not.
    assert db.execute("select count(*) from states where instant<10 and status in ('open','in_progress')").fetchone()[0] == 1
    totals = db.execute("""
        select basis,currency,sum(case when basis='estimated' then 1.0*quantity*unit_price/price_unit_quantity else amount end)
        from costs group by basis,currency
    """).fetchall()
    assert len(totals) == 4
    assert ("estimated", "USD", .006) in totals
    assert db.execute("select count(*) from costs where session is null").fetchone()[0] == 3
    usage = items(workbook)["common-cards"]["content"]["query"]
    assert "join kind=inner (Cohort) on store, conversation_id" in usage
    assert "EventKind in ('booking_status', 'case_status')" in usage
    assert "status in ('open', 'in_progress')" in usage
    db.close()
