"""Offline safe token/showback adapters; no Azure login, sends or network calls."""

import importlib.util
import base64
import json
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from pathlib import Path
from urllib.error import HTTPError

import pytest


ROOT = Path(__file__).resolve().parents[4]
AUTOMATION = ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings" / "automation"
RUNBOOKS = AUTOMATION / "coreteam" / "finops" / "runbooks"
HELPER = RUNBOOKS / "common" / "monitoring_report.py"


@pytest.fixture
def adapter():
    spec = importlib.util.spec_from_file_location("monitoring_runbook_adapter", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def request_document():
    return {"contract": "aifactory.aggregate-report.v1", "report_id": "showback",
            "object_id": "33333333-3333-4333-8333-333333333333", "azure_cli": ["az"],
            "lookback_days": 2, "as_of_date": "2026-09-14",
            "scope": {"subscription_id": "11111111-1111-4111-8111-111111111111",
                      "tenant_id": "22222222-2222-4222-8222-222222222222",
                      "resource_group": "orange-project017-weu-dev-001",
                      "workspace_id": "44444444-4444-4444-8444-444444444444",
                      "window_start": "2026-09-13T00:00:00+00:00", "window_end": "2026-09-15T00:00:00+00:00"}}


def test_showback_queries_only_selected_resource_group_actual_cost(adapter, request_document):
    calls = []
    def response(request, url, body):
        calls.append((url, body))
        return {"properties": {"columns": [{"name": key} for key in ("PreTaxCost", "UsageDate", "Currency")],
                               "rows": [[12.5, 20260913, "EUR"], [-1.0, 20260914, "EUR"]]}}
    adapter.arm = response
    result = adapter.showback(request_document)
    url, body = calls[0]
    assert "/resourceGroups/orange-project017-weu-dev-001/providers/Microsoft.CostManagement/query" in url
    assert body["type"] == "ActualCost" and body["timeframe"] == "Custom"
    assert "grouping" not in body["dataset"]
    assert result["currency"] == "EUR"
    assert [row["metrics"]["actual_cost"] for row in result["daily"]] == [12.5, -1.0]
    assert "selected_project_cost_only" in result["warnings"]
    assert "gh-" not in json.dumps(result) and "sample" not in json.dumps(result)


@pytest.mark.parametrize("bad", ["pagination", "mixed_currency", "invalid_number", "duplicate", "missing_currency"])
def test_showback_rejects_incomplete_or_inconsistent_aggregates(adapter, request_document, bad):
    properties = {"columns": [{"name": key} for key in ("PreTaxCost", "UsageDate", "Currency")],
                  "rows": [[1.0, 20260913, "USD"]]}
    if bad == "pagination":
        properties["nextLink"] = "https://untrusted.example/next"
    elif bad == "mixed_currency":
        properties["rows"].append([2.0, 20260914, "EUR"])
    elif bad == "invalid_number":
        properties["rows"][0][0] = float("nan")
    elif bad == "duplicate":
        properties["rows"].append([2.0, 20260913, "USD"])
    else:
        properties["rows"][0][2] = None
    adapter.arm = lambda *args: {"properties": properties}
    with pytest.raises(ValueError):
        adapter.showback(request_document)


def test_showback_empty_is_not_sample_zero(adapter, request_document):
    adapter.arm = lambda *args: {"properties": {
        "columns": [{"name": key} for key in ("PreTaxCost", "UsageDate", "Currency")], "rows": []}}
    result = adapter.showback(request_document)
    assert result["daily"] == [] and result["currency"] is None and "no_data" in result["warnings"]


def test_redirects_and_foreign_scope_are_blocked_before_outbound_auth(adapter, request_document):
    with pytest.raises(RuntimeError, match="Redirected"):
        adapter.NoRedirect().redirect_request(None, None, None, None, None, "https://other.example/")
    with pytest.raises(ValueError, match="exact reviewed"):
        adapter.arm(request_document, "https://management.azure.com/subscriptions/other/resourceGroups/other/query?api-version=2023-03-01")


def test_cost_429_retries_respect_longest_header_and_are_bounded(adapter, request_document, monkeypatch):
    claims = {"tid": request_document["scope"]["tenant_id"], "oid": request_document["object_id"],
              "exp": time.time() + 3600, "aud": "https://management.azure.com/"}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    monkeypatch.setattr(adapter.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=f"header.{encoded}.signature"))
    attempts, sleeps = [], []
    def request(*args, **kwargs):
        attempts.append(1)
        raise HTTPError("https://management.azure.com", 429, "rate limited",
                        {"Retry-After": "2", "x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after": "5"}, None)
    monkeypatch.setattr(adapter, "build_opener", lambda *args: SimpleNamespace(open=request))
    monkeypatch.setattr(adapter.time, "sleep", sleeps.append)
    scope = request_document["scope"]
    url = f"https://management.azure.com/subscriptions/{scope['subscription_id']}/resourceGroups/{scope['resource_group']}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"
    with pytest.raises(HTTPError):
        adapter.arm(request_document, url, {"type": "ActualCost"})
    assert len(attempts) == 3 and sleeps == [5, 5]
    assert adapter.retry_delay({"Retry-After": "500"}) == 500


@pytest.mark.parametrize("relative", [Path("Update-FoundryTokenReport.ps1"), Path("showback") / "Update-ShowbackReport.ps1"])
def test_safe_branch_precedes_legacy_config_login_and_upload(relative):
    text = (RUNBOOKS / relative).read_text()
    branch = text.index("if ($MonitoringRequest)")
    assert branch < text.index("$cfg =") if "$cfg =" in text else branch < text.index("$cfg ")
    if "Import-Module" in text:
        assert branch < text.index("Import-Module")
    block = text[branch:text.index("exit $LASTEXITCODE", branch)]
    assert "monitoring_report.py" in block and "-I -B" in block
    assert not any(command in block for command in ("Connect-AzAccount", "Set-AzContext", "Start-AzAutomationRunbook", "Set-AzStorageBlobContent"))


def test_real_powershell_token_entrypoint_uses_only_owned_adapter(tmp_path, request_document):
    powershell = shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell 7 is unavailable on this test runner")
    runtime = tmp_path / "runtime"
    runbooks = runtime / "coreteam" / "finops" / "runbooks"
    (runbooks / "common").mkdir(parents=True)
    script = runbooks / "Update-FoundryTokenReport.ps1"
    script.write_bytes((RUNBOOKS / script.name).read_bytes())
    (runbooks / "common" / "monitoring_report.py").write_bytes(HELPER.read_bytes())
    usage = runtime / "projectteam" / "foundry-usage" / "foundry_usage_report.py"
    usage.parent.mkdir(parents=True)
    usage.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "def main():\n"
        "    destination=Path(sys.argv[sys.argv.index('--automation-json')+1])\n"
        "    destination.write_text(json.dumps({'report_id':'foundry-usage','daily':[{'metrics':{'requests':9,'input_tokens':42}}],'warnings':[]}))\n"
        "    return 0\n")
    request_document["report_id"] = "foundry-token"
    request = tmp_path / "monitoring-request.json"
    request.write_text(json.dumps(request_document))
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(script),
                             "-MonitoringRequest", str(request), "-MonitoringPython", sys.executable],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30, shell=False)
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "aggregate.json").read_text())
    assert document["report_id"] == "foundry-token"
    assert document["daily"][0]["metrics"] == {"input_tokens": 42}
    assert "token_pricing_not_evaluated" in document["warnings"]
