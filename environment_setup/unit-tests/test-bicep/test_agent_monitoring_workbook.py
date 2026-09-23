"""Credential-free regression checks for the opt-in shared agent workbook."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"


@pytest.fixture(scope="module")
def phase():
    compiler = shutil.which("bicep")
    if not compiler:
        pytest.skip("Standalone Bicep is required for the compiled phase-10 check.")
    result = subprocess.run(
        [compiler, "build", str(BICEP / "esml-genai-1" / "10-aifactory-dashboards.bicep"),
         "--no-restore", "--stdout"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def nested_resources(template):
    resources = template.get("resources", [])
    for resource in resources.values() if isinstance(resources, dict) else resources:
        if not resource.get("existing"):
            yield resource
        nested = resource.get("properties", {}).get("template")
        if nested:
            yield from nested_resources(nested)


def test_agent_workbook_default_off_and_common_rg_singleton(phase):
    assert phase["parameters"]["enableAgentMonitoring"]["defaultValue"] is False
    assert phase["parameters"]["agentMonitoringWorkspaceResourceId"]["defaultValue"] == ""
    agent = next(resource for resource in phase["resources"]
                 if "10-agent-monitoring" in resource["name"])
    assert agent["condition"] == "[parameters('enableAgentMonitoring')]"
    assert agent["resourceGroup"] == "[variables('commonResourceGroup')]"
    assert agent["properties"]["parameters"]["workspaceResourceId"]["value"] == (
        "[parameters('agentMonitoringWorkspaceResourceId')]")
    workbook = agent["properties"]["template"]
    assert workbook["parameters"]["workspaceResourceId"]["minLength"] == 1
    assert {resource["type"] for resource in nested_resources(workbook)} == {"Microsoft.Insights/workbooks"}
    compiled = json.dumps(workbook)
    assert "Microsoft.OperationalInsights/workspaces" in compiled
    assert "customerId" in compiled
    assert "validWorkspacePath" in compiled
    text = (BICEP / "modules" / "monitoring" / "agentMonitoringWorkbook.bicep").read_text(encoding="utf-8")
    assert "enableAgentMonitoring ? sourceWorkspace.properties.customerId : ''" in text


def test_phase_outputs_and_optional_navigation_do_not_enable_collection(phase):
    assert {"agentMonitoringWorkbookId", "agentMonitoringWorkbookUrl"} <= phase["outputs"].keys()
    assert {resource["type"] for resource in nested_resources(phase)} <= {
        "Microsoft.Resources/deployments", "Microsoft.Portal/dashboards", "Microsoft.Insights/workbooks",
    }
    project = next(resource for resource in phase["resources"]
                   if "10-dashboard" in resource["name"])
    assert "enableAgentMonitoring" in json.dumps(project["properties"]["parameters"]["agentMonitoringWorkbookResourceId"])
    template = project["properties"]["template"]
    assert template["parameters"]["agentMonitoringWorkbookResourceId"]["defaultValue"] == ""
    text = (BICEP / "modules" / "projectDash01.bicep").read_text(encoding="utf-8")
    assert "empty(agentMonitoringWorkbookResourceId) ? []" in text
    assert "], myProjectEntryParts), agentMonitoringEntryParts)" in text
    assert "position: { x: 0, y: 25" in text


def test_canonical_kql_has_six_families_complete_sums_and_separate_value_tiers(phase):
    agent = next(resource for resource in phase["resources"] if "10-agent-monitoring" in resource["name"])
    compiled = json.dumps(agent["properties"]["template"])
    query = (BICEP / "modules" / "monitoring" / "agentMonitoringCanonical.kql").read_text()
    for field in ("requests", "input_tokens", "output_tokens", "latency_ms_sum", "latency_samples",
                  "successful_requests", "evaluated_responses", "quality_passed_responses",
                  "actual_cost", "amortized_cost", "token_estimated_cost", "security_findings"):
        assert field in compiled and field in query
    for section in ("usage", "tokens", "reliability", "cost", "value", "security"):
        assert f"Section == \\\"{section}\\\"" in compiled
    assert "AvailableObservations == Observations" in query
    assert "Observations == 1" in query
    assert "array_length(Currencies) == 1 and MissingCurrency == 0" in query
    assert "QualifiedCount == Observations and Observations > 0" in query
    assert "QualifiedValueCount == Observations and Observations > 0" in query
    assert "QualifiedValueCount=countif(Qualified and CapacityValid and Referenced(C.provenance.labor_rate_per_hour))" in query
    assert "'qualified_capacity_value', 'Class', 'qualified-capacity', 'Unit', Currency, 'Count', QualifiedValueCount" in query
    assert "ALL rows require qualified outcome inputs, labor rate and rate reference" in query
    assert "Values.latency_ms_sum) / todouble(Values.latency_samples)" in query
    assert "modeled-time-saving" in query and "qualified-capacity" in query
    assert "'verified_realized_value'" in query and "'Value', real(null)" in query
    assert "abs(Total) <= 9007199254740991.0" in query
    assert "abs(Value) <= 9007199254740991.0" in query
    assert "tostring(C.source) == 'live'" in query
    assert "array_length(Links) == 1 and MissingLinks == 0" in query
    rows = (BICEP / "modules" / "monitoring" / "agentMonitoringRows.kql").read_text()
    assert "aifactory.agent-observations/v1" in rows and "aifactory.agent-observations/v2" in rows
