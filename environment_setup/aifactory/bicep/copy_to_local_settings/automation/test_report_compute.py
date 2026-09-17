"""Offline adapter/PowerShell contract regression tests; never contact Azure."""

import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
from unittest.mock import patch

import pytest

import report_compute as reports


ROOT = Path(__file__).resolve().parent
SUB = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
ACCOUNT = f"/subscriptions/{SUB}/resourceGroups/rg-reports/providers/Microsoft.Automation/automationAccounts/reports"
JOB = "33333333-3333-3333-3333-333333333333"


def request(kind="foundry-tokens", compute="local"):
    value = reports.plan(ROOT, kind, "004", "dev", 30, compute=compute)
    value["target"].update(subscription_id=SUB, tenant_id=TENANT,
                           project_resource_group="gh-esml-project004-sdc-dev-001-rg",
                           common_resource_group="gh-esml-common-sdc-dev-001")
    if compute == "runbook":
        value["cloud_resource_id"] = ACCOUNT + "/runbooks/" + reports.RUNBOOKS[kind]
    elif compute == "logicapp":
        value["cloud_resource_id"] = f"/subscriptions/{SUB}/resourceGroups/rg-reports/providers/Microsoft.Logic/workflows/aifactory-report-dispatch"
    return value


@pytest.mark.parametrize("kind", list(reports.SCRIPTS))
@pytest.mark.parametrize("compute", ["local", "runbook", "logicapp"])
def test_samples_never_run_processes(kind, compute):
    value = request(kind)
    value.update(compute=compute, dry_run=True)
    with patch.object(reports, "_process", side_effect=AssertionError("No processes in sample mode")):
        result = reports.execute(value)
    assert result["source"] == "sample"
    assert result["status"] == "warning"
    assert result["report"]["tables"]
    assert result["report"]["charts"]
    assert result["report"]["dataSource"].startswith("Sample fixture (not live): ")
    assert result["report"]["dataSource"] == result["report"]["lineage"]["dataSource"]
    assert result["run_id"] is None


@pytest.mark.parametrize("source", ["Explicit fixture collector", {"name": "Explicit fixture collector", "reference": "fixture-only"}])
def test_accept_report_preserves_explicit_source_and_lineage_shapes(source):
    value = request()
    value["dry_run"] = True
    report = reports._sample(value)["report"]
    lineage = {"formula": "Fixture counters supplied without transformation", "inputs": {"reference": "fixture-only"}}
    report.update(dataSource=source, lineage=lineage)
    accepted = reports._accept_report(value, report)["report"]
    assert accepted["dataSource"] == source
    assert accepted["lineage"] == lineage


def test_target_required_and_no_credentials_in_config():
    value = request()
    value["target"]["tenant_id"] = ""
    assert reports.execute(value)["status"] == "failed"
    value = request()
    value["report_config"]["clientSecret"] = "never-return-this"
    result = reports.execute(value)
    assert result["status"] == "failed"
    assert "never-return-this" not in json.dumps(result)


@pytest.mark.parametrize("kind", list(reports.SCRIPTS))
@pytest.mark.parametrize("compute", ["local", "runbook", "logicapp"])
def test_all_never_becomes_an_azure_identifier(kind, compute):
    value = reports.plan(ROOT, kind, "All", "dev", 30, compute=compute)
    assert value["report_config"]["naming"]["projectNumber"] == ""
    with patch.object(reports, "_process", side_effect=AssertionError("No processes for All")):
        result = reports.execute(value)
    assert result["status"] == "unavailable"
    assert "concrete project" in result["output"]


def test_legacy_scope_intersection_and_lineage():
    value = request()
    value["dry_run"] = True
    value["filters"] = {"aiFactory": "unknown-factory", "scaleset": "All", "project": "004"}
    assert reports.execute(value)["status"] == "unavailable"
    value["target"]["aiFactory"] = "unknown-factory"
    report = reports.execute(value)["report"]
    assert report["filters"]["project"] == "004"
    assert all(item["dataSource"] and item["lineage"]["formula"] for item in report["tables"] + report["charts"])
    assert report["lineage"]["inputs"]["target"]["project_number"] == "004"


def test_additive_target_identities_are_metadata_not_resource_names():
    value = request()
    value["dry_run"] = True
    factory, scaleset = r"C:\reviewed factories\factory001", "sdc:001"
    value["target"].update(factory=factory, scaleset=scaleset, aiFactory="older-label")
    value["filters"] = {"aiFactory": factory, "scaleset": scaleset, "project": "004"}
    validated = reports._validate(value)
    assert validated["target"]["factory"] == factory and validated["target"]["scaleset"] == scaleset
    parameters = reports._parameters(validated)
    assert parameters["ProjectResourceGroup"] == value["target"]["project_resource_group"]
    assert "factory" not in parameters and "scaleset" not in parameters
    assert factory not in parameters["ConfigJson"] and scaleset not in parameters["ConfigJson"]
    report = reports.execute(value)["report"]
    assert report["lineage"]["inputs"]["target"]["factory"] == factory
    value["filters"]["aiFactory"] = "different-factory"
    assert reports.execute(value)["status"] == "unavailable"


def test_cloud_usage_explicitly_unavailable():
    value = request("foundry-usage")
    value["compute"] = "runbook"
    with patch.object(reports, "_process", side_effect=AssertionError):
        assert reports.execute(value)["status"] == "unavailable"


def test_frozen_python_usage_does_not_launch_packaged_executable():
    with patch.object(sys, "frozen", True, create=True), patch.object(reports, "_process", side_effect=AssertionError):
        result = reports.execute(request("foundry-usage"))
    assert result["status"] == "unavailable"
    assert "regular Python interpreter" in result["output"]


def test_frozen_azure_cli_does_not_fall_back_to_packaged_executable():
    with patch.object(sys, "frozen", True, create=True), patch.object(shutil, "which", return_value=None), patch.object(reports.importlib.util, "find_spec", side_effect=AssertionError):
        with pytest.raises(reports.ReportError) as error:
            reports._az_command()
    assert error.value.status == "unavailable"


def test_runbook_exact_whitelist():
    value = request(compute="runbook")
    value["cloud_resource_id"] = ACCOUNT + "/runbooks/ThrottleNetwork"
    with patch.object(reports, "_verify_account"):
        assert reports.execute(value)["status"] == "failed"


def test_cloud_context_mismatch():
    with patch.object(reports, "_az", return_value={"id": SUB, "tenantId": SUB}):
        with pytest.raises(reports.ReportError, match="does not match"):
            reports._verify_account(request())


def test_refuse_old_runbook_before_submit():
    value = request(compute="runbook")
    with patch.object(reports, "_verify_account"), patch.object(reports, "_rest", return_value={"properties": {"state": "Published"}}) as rest:
        result = reports.execute(value)
    assert result["status"] == "unavailable"
    assert [call.args[0] for call in rest.call_args_list] == ["get"]


def test_runbook_submission_safe_parameters_no_runon():
    value = request(compute="runbook")
    with patch.object(reports, "_verify_account"), patch.object(reports, "_check_runbook"), patch.object(reports, "_rest", return_value={}) as rest:
        result = reports.execute(value)
    body = rest.call_args.kwargs["body"]
    assert body["properties"]["parameters"]["NoUpload"] == "true"
    assert body["properties"]["parameters"]["ReportFormat"] == "Json"
    assert body["properties"]["parameters"]["TenantId"] == TENANT
    assert "runOn" not in body["properties"]
    assert result["status"] == "running"
    assert result["automation_account_resource_id"] == ACCOUNT


def test_uncertain_submission_keeps_job_id():
    value = request(compute="runbook")
    with patch.object(reports, "_verify_account"), patch.object(reports, "_check_runbook"), patch.object(reports, "_rest", side_effect=reports.ReportError("Timeout")):
        result = reports.execute(value)
    assert result["status"] == "warning"
    assert result["run_id"]
    assert "check status" in result["output"]


def test_logic_refuses_throttling_tags_and_sas():
    value = request(compute="logicapp")
    with patch.object(reports, "_rest", return_value={"tags": {"aifactory-purpose": "network-throttling"}}):
        with pytest.raises(reports.ReportError, match="never be invoked"):
            reports._logic_account(value)
    with patch.object(reports, "_rest", return_value={"tags": {"aifactory-purpose": "report-dispatch", "aifactory-report-protocol": "1"}}):
        with pytest.raises(reports.ReportError, match="disable SAS"):
            reports._logic_account(value)


def test_status_refuses_other_jobs():
    value = request(compute="runbook")
    with patch.object(reports, "_verify_account"), patch.object(reports, "_rest", return_value={"properties": {"runbook": {"name": "ThrottleNetwork"}, "status": "Completed"}}):
        result = reports.status(value, JOB)
    assert result["status"] == "failed"


def test_status_completed_envelope_and_target_validation():
    value = request(compute="runbook")
    sample_request = {**value, "dry_run": True}
    envelope = reports._sample(sample_request)["report"]
    envelope["source"] = "live"
    job = {"properties": {"runbook": {"name": reports.RUNBOOKS[value["report_type"]]}, "status": "Completed", "parameters": reports._parameters(value)}}
    with patch.object(reports, "_verify_account"), patch.object(reports, "_rest", side_effect=[job, json.dumps(envelope)]):
        result = reports.status(value, JOB)
    assert result["report"]["target"]["subscription_id"] == SUB
    assert result["run_id"] == JOB
    envelope["target"]["subscription_id"] = TENANT
    with pytest.raises(reports.ReportError, match="target"):
        reports._accept_report(value, envelope)


@pytest.mark.parametrize("kind", ["showback", "foundry-tokens"])
def test_powershell_json_sample_stdout_only(kind):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime not installed")
    process = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(ROOT / reports.SCRIPTS[kind]),
         "-DryRun", "-NoUpload", "-ReportFormat", "Json"],
        capture_output=True, encoding="utf-8", check=False,
    )
    assert process.returncode == 0, process.stderr
    envelope = json.loads(process.stdout)
    assert envelope["report_type"] == kind
    assert envelope["source"] == "sample"
    assert isinstance(envelope["tables"], list)
    assert isinstance(envelope["charts"], list)


def test_showback_missing_sample_is_warning_not_crash():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime not installed")
    process = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(ROOT / reports.SCRIPTS["showback"]),
         "-DryRun", "-NoUpload", "-ReportFormat", "Json", "-ProjectNumber", "999"],
        capture_output=True, encoding="utf-8", check=False,
    )
    envelope = json.loads(process.stdout)
    assert process.returncode == 0, envelope
    assert envelope["status"] == "warning"


def test_showback_all_sample_links_remain_disabled_and_aligned():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime not installed")
    process = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File", str(ROOT / reports.SCRIPTS["showback"]),
                              "-DryRun", "-NoUpload", "-ReportFormat", "Json", "-ProjectNumber", "All"],
                             capture_output=True, encoding="utf-8", check=False)
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    chart = report["charts"][0]
    assert len(chart["labelLinks"]) == len(chart["labels"])
    assert all(link is None for link in chart["labelLinks"])
    assert report["filters"]["project"] == "All"
    assert report["lineage"]["inputs"]["costBasis"] == "ActualCost"


def test_exported_html_preserves_validated_cost_link_tooltip_and_theme():
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime not installed")
    module = ROOT / "coreteam" / "finops" / "runbooks" / "common" / "AifFactory.psm1"
    command = f"""Import-Module '{module}' -Force -WarningAction SilentlyContinue
$md = '[project001](https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/costanalysis/scope/%2Freviewed "Go to Azure Cost analysis for project 001")'
ConvertTo-ReportHtml -Markdown $md -Title '<safe>'
"""
    process = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, encoding="utf-8", check=False)
    assert process.returncode == 0
    assert '<a href="https://portal.azure.com/' in process.stdout
    assert 'title="Go to Azure Cost analysis for project 001"' in process.stdout
    assert "scoutTheme" in process.stdout and "--cp-bg" in process.stdout
    assert "<title>&lt;safe&gt;</title>" in process.stdout


@pytest.mark.parametrize("kind", ["foundry-tokens", "showback"])
def test_local_helper_configjson_and_exact_target(kind):
    if not shutil.which("pwsh"):
        pytest.skip("Optional PowerShell runtime not installed")
    value = request(kind)
    value["dry_run"] = True
    result = reports._local(reports._validate(value))
    assert result["source"] == "sample"
    assert result["report"]["target"]["subscription_id"] == SUB
    assert result["report"]["target"]["project_resource_group"] == value["target"]["project_resource_group"]


def test_cli_failure_exit_and_redaction():
    with reports._workspace() as work:
        path = work / "request.json"
        path.write_text('{"version": 0, "clientSecret": "never-return-this"}', encoding="utf-8")
        process = subprocess.run([sys.executable, str(ROOT / "report_compute.py"), "--request", str(path)], capture_output=True, encoding="utf-8")
    assert process.returncode != 0
    assert json.loads(process.stdout)["status"] == "failed"
    assert "never-return-this" not in process.stdout


def _mock_powershell(kind, functions, config=None):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime not installed")
    script = ROOT / reports.SCRIPTS[kind]
    value = request(kind)
    with reports._workspace() as work:
        config_path = work / "config.json"
        config_path.write_text(json.dumps(config or value["report_config"]), encoding="utf-8")
        command = f"""
function Disable-AzContextAutosave {{}}
function Select-AzSubscription {{}}
function Get-AzContext {{ [pscustomobject]@{{Subscription=[pscustomobject]@{{Id='{SUB}'}};Tenant=[pscustomobject]@{{Id='{TENANT}'}}}} }}
function Get-AzStorageAccount {{ throw 'UPLOAD MUST NOT RUN' }}
function Set-AzStorageBlobContent {{ throw 'UPLOAD MUST NOT RUN' }}
{functions}
& '{script}' -UseCurrentLogin -SubscriptionId '{SUB}' -TenantId '{TENANT}' -ProjectNumber '004' -ProjectResourceGroup '{value["target"]["project_resource_group"]}' -CommonResourceGroup '{value["target"]["common_resource_group"]}' -ConfigPath '{config_path}' -NoUpload -ReportFormat Json -OutputBlobStorageAccount 'blocked-upload'
"""
        process = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, encoding="utf-8")
    return process, json.loads(process.stdout)


def test_token_query_failure_is_failed_without_zero_data_or_error_body():
    process, envelope = _mock_powershell("foundry-tokens", """
function Get-AzResource { [pscustomobject]@{Name='foundry';ResourceId='/mock'} }
function Get-AzOperationalInsightsWorkspace { [pscustomobject]@{Name='la-cmn-test';CustomerId='mock'} }
function Invoke-AzOperationalInsightsQuery { throw 'secret-error-body-must-not-leak' }
""")
    assert process.returncode != 0
    assert envelope["status"] == "failed"
    assert envelope["tables"] == []
    assert "zero usage cannot be inferred" in envelope["warnings"][0]
    assert "secret-error-body" not in process.stdout


@pytest.mark.parametrize("missing_actual", [False, True])
def test_showback_no_upload_and_forecast_failure_unavailable_not_zero(missing_actual):
    value = request("showback")
    config = value["report_config"]
    config["showback"]["uploadToLake"] = True
    rg = "other-rg" if missing_actual else value["target"]["project_resource_group"]
    body = json.dumps({"properties": {"columns": [{"name": "Cost"}, {"name": "ResourceGroupName"}, {"name": "Currency"}], "rows": [[10.5, rg, "USD"]]}})
    process, envelope = _mock_powershell("showback", f"""
function Get-AzResourceGroup {{ [pscustomobject]@{{ResourceGroupName='{value["target"]["project_resource_group"]}';Tags=@{{}}}} }}
function Invoke-AzRestMethod {{
    param($Method,$Path,$Payload)
    if ($Path -like '*forecast*') {{throw 'secret-forecast-response'}}
    [pscustomobject]@{{StatusCode=200;Content='{body}'}}
}}
""", config)
    assert process.returncode == 0, envelope
    assert envelope["status"] == "warning"
    assert envelope["tables"][0]["rows"][0][-1] is None
    assert envelope["tables"][0]["rows"][0][-2] == (None if missing_actual else 10.5)
    link = envelope["charts"][0]["labelLinks"][0]
    assert link["url"].startswith("https://portal.azure.com/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/%2Fsubscriptions%2F")
    assert link["tooltip"] == "Go to Azure Cost analysis for project 004"
    assert "secret-forecast-response" not in process.stdout
    assert "UPLOAD MUST NOT RUN" not in process.stdout


@pytest.mark.parametrize("kind", ["foundry-tokens", "showback"])
def test_monitoring_bridge_remains_separate_from_envelope_mode(kind):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("Optional PowerShell runtime not installed")
    with reports._workspace() as work:
        path = work / "invalid-monitoring-request.json"
        path.write_text('{"contract":"invalid-offline-contract"}', encoding="utf-8")
        process = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", str(ROOT / reports.SCRIPTS[kind]),
             "-MonitoringRequest", str(path), "-MonitoringPython", sys.executable,
             "-ReportFormat", "Json", "-NoUpload", "-DryRun"],
            capture_output=True, encoding="utf-8", check=False,
        )
    assert process.returncode != 0
    assert "Only the strict token/showback report contract is supported" in process.stderr
    assert process.stdout.strip() == ""


def test_tenant_debug_usage_keeps_cli_scope_and_sparse_measurements(monkeypatch):
    script = ROOT / reports.SCRIPTS["foundry-usage"]
    tree = ast.parse(script.read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and node.module.startswith(("azure.", "reportlab.")))]
    module = types.ModuleType("offline_compute_usage")
    module.__file__ = str(script)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(tree, str(script), "exec"), module.__dict__)
    credentials = []
    module.AzureCliCredential = lambda **kwargs: credentials.append(kwargs) or object()
    module.DefaultAzureCredential = lambda **kwargs: pytest.fail("No ambient credential fallback")
    module.ScopedCliCredential = lambda *args: pytest.fail("Monitoring object-ID contract must remain separate")
    module.ResourceManagementClient = lambda *args: object()
    module.MonitorManagementClient = lambda *args: object()
    resource = module.Resource("/resource/id", "foundry", module.COGNITIVE_ACCOUNT_TYPE, "AIServices")
    module.discover_resources = lambda *args: ([resource], [], [])
    def metrics(*args, strict=False, warnings=None):
        assert strict is False
        assert isinstance(warnings, list)
        return [module.MetricPoint("foundry", resource.type, "Requests", "model", "not exported",
                                   datetime(2026, 9, 14, tzinfo=timezone.utc), 0)]
    module.collect_metric_points = metrics
    module.write_pdf = lambda *args: None
    charts = []
    module.write_chart_pdf = lambda *args: charts.append(args)
    with reports._workspace() as work:
        output = work / "aggregate.json"
        monkeypatch.setattr(sys, "argv", [
            str(script), "--subscription-id", SUB, "--tenant-id", TENANT,
            "--resource-group", "selected-project", "--days", "2", "--as-of-date", "2026-09-14",
            "--debug-json", str(output), "--output", str(work / "usage.pdf"),
        ])
        assert module.main() == 0
        aggregate = json.loads(output.read_text(encoding="utf-8"))
    assert credentials == [{"subscription": SUB, "tenant_id": TENANT}]
    assert aggregate["daily"] == {"2026-09-14|foundry|model": {"requests": 0}}
    assert aggregate["sessions_available"] is False
    assert aggregate["warnings"]
    assert aggregate["period"]["days"] == 2
    assert charts[0][3]["Foundry"] == [None, 0]
    assert charts[1][3]["Foundry"] == [None, None]
