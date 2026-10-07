"""Offline contract for the retained connectivity-hub Portal dashboard."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = ROOT / "bootstrap" / "lib" / "all-factories-dashboard.bicep"


def test_native_dashboard_has_one_hub_scoped_identity_and_explicit_subscription_selection():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "name: 'all-ai-factories'" in source
    assert "'hidden-title': 'All AI Factories'" in source
    assert "param selectedSubscriptionIds array" in source
    assert "@minLength(1)" in source
    assert "factoryId" not in source
    assert "commonResourceGroup" not in source
    assert "Microsoft.Portal/dashboards@" in source


def test_native_dashboard_does_not_pretend_to_execute_custom_billing_logic():
    source = TEMPLATE.read_text(encoding="utf-8")
    assert "Extension/HubsExtension/PartType/MarkdownPart" in source
    assert "CostAnalysisPinPart" not in source
    assert "numericAggregationSupported: false" in source
    assert "Forecast does not support grouping" in source
    assert "CostUSD" not in source
    assert "local API" in source
    assert "full-month forecast" in source
    assert "currency" in source
    assert "not a factories-only total" in source
    assert "Dev / Stage / Prod" in source
    assert "costanalysis" in source
    assert "/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/" in source
    assert "uriComponent('/subscriptions/${subscriptionId}')" in source
    assert "http://localhost" not in source
    assert "Microsoft.Resources/deploymentScripts" not in source
    assert "Microsoft.Authorization/roleAssignments" not in source


def test_dashboard_is_an_explicit_separate_reviewed_hub_stage():
    source = (ROOT / "bootstrap/lib/all_factories_dashboard.py").read_text(encoding="utf-8")
    assert '"hub_dashboard": "reviewed-native-cost-drillthrough-v1"' in source
    assert '"requires_established_hub_coordination": True' in source
    assert '"bootstrap/lib/all-factories-dashboard.bicep"' in source
    assert 'def validate_receipt(' in source
    assert 'expected_plan_hash' in source
    assert 'foundation.lock_blob(plan["hub_resource_group_id"])' in source


def test_bicep_compiles_offline_to_only_one_portal_dashboard(tmp_path):
    bicep = shutil.which("bicep")
    if not bicep:
        pytest.skip("Existing Bicep CLI required for compilation")
    output = tmp_path / "all-factories-dashboard.json"
    result = subprocess.run(
        [bicep, "build", str(TEMPLATE), "--outfile", str(output)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    compiled = json.loads(output.read_text(encoding="utf-8"))
    assert [item["type"] for item in compiled["resources"]] == ["Microsoft.Portal/dashboards"]
    assert compiled["parameters"]["selectedSubscriptionIds"]["minLength"] == 1
    assert compiled["resources"][0]["name"] == "all-ai-factories"
    assert compiled["resources"][0]["tags"] == "[variables('dashboardTags')]"
    assert compiled["variables"]["dashboardTags"]["hidden-title"] == "All AI Factories"
    properties = compiled["variables"]["dashboardProperties"]
    introduction = properties["lenses"][0]["parts"]
    assert "subscriptionParts" in introduction
    subscription_parts = compiled["variables"]["copy"][0]
    assert subscription_parts["name"] == "subscriptionParts"
    settings = subscription_parts["input"]["metadata"]["settings"]["content"]["settings"]
    assert settings["markdownSource"] == 1
    assert "/#blade/Microsoft_Azure_CostManagement/Menu/open/costanalysis/scope/" in settings["content"]
