"""Private Link contracts for Databricks and Event Hubs in the GenAI/ML project templates (ADO pipeline 43)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
GENAI = BICEP / "esml-genai-1"
JOB2 = (BICEP / "copy_to_local_settings" / "azure-devops" / "esml-yaml-pipelines" / "esml-infra-project"
        / "jobs" / "job-2-genai-services.yaml")


def compile_template(path, tmp_path):
    compiler = shutil.which("bicep")
    if not compiler:
        pytest.skip("Existing Bicep CLI required for cached offline compilation")
    output = tmp_path / (path.stem + ".json")
    result = subprocess.run([compiler, "build", str(path), "--no-restore", "--outfile", str(output)],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    return json.loads(output.read_text(encoding="utf-8"))


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def deployment(template, marker):
    matches = [item for item in walk(template)
               if item.get("type") == "Microsoft.Resources/deployments" and marker in str(item.get("name", ""))]
    assert len(matches) == 1, [item.get("name") for item in matches]
    return matches[0]


def resources(template):
    items = template.get("resources", [])
    return list(items.values()) if isinstance(items, dict) else list(items)


def private_endpoints(template):
    return [item for item in resources(template) if item.get("type") == "Microsoft.Network/privateEndpoints"]


def group_ids(endpoint):
    return [group for connection in endpoint["properties"]["privateLinkServiceConnections"]
            for group in connection["properties"]["groupIds"]]


def test_private_databricks_workspace_gets_ui_api_and_browser_authentication_endpoints(tmp_path):
    template = compile_template(BICEP / "modules" / "databricksPrivateEndpoints.bicep", tmp_path)
    endpoints = {group_ids(item)[0]: item for item in private_endpoints(template)}
    # One workspace-VNet databricks_ui_api endpoint serves both front-end (UI/REST) and back-end
    # (secure cluster connectivity relay); browser_authentication carries the regional SSO callback.
    assert set(endpoints) == {"databricks_ui_api", "browser_authentication"}
    for endpoint in endpoints.values():
        connection = endpoint["properties"]["privateLinkServiceConnections"][0]["properties"]
        assert "Microsoft.Databricks/workspaces" in connection["privateLinkServiceId"]
        assert endpoint["properties"]["subnet"]["id"] == "[parameters('subnetResourceId')]"
    browser = endpoints["browser_authentication"]
    assert browser["condition"] == "[parameters('enableBrowserAuthentication')]"
    # Databricks serializes private endpoint connection updates on a workspace.
    assert any("databricks_ui_api" in json.dumps(endpoints["databricks_ui_api"]) and dependency
               for dependency in browser.get("dependsOn", []))
    zone_groups = [item for item in resources(template)
                   if item.get("type") == "Microsoft.Network/privateEndpoints/privateDnsZoneGroups"]
    assert len(zone_groups) == 2
    # Empty zone ID means central DNS policy (DeployIfNotExists) owns the zone groups.
    assert all("not(empty(parameters('privateDnsZoneResourceId')))" in item["condition"] for item in zone_groups)


def test_project_template_repairs_existing_and_new_private_databricks_workspaces(tmp_path):
    template = compile_template(GENAI / "07-ml-data-platform.bicep", tmp_path)
    module = deployment(template, "07-DbxPend-")
    # Must not depend on databricksExists: an existing private workspace without endpoints is unusable.
    assert module["condition"] == ("[and(parameters('enableDatabricks'), "
                                   "not(parameters('enablePublicAccessWithPerimeter')))]")
    parameters = module["properties"]["parameters"]
    assert "genaiSubnetName" in json.dumps(parameters["subnetResourceId"])
    zone = json.dumps(parameters["privateDnsZoneResourceId"])
    assert "centralDnsZoneByPolicyInHub" in zone and "azuredatabricks" in zone
    assert json.dumps(parameters["enableBrowserAuthentication"]).count("enableDatabricksBrowserAuthPrivateEndpoint") == 1
    assert {group for endpoint in private_endpoints(module["properties"]["template"]) for group in group_ids(endpoint)} == {
        "databricks_ui_api", "browser_authentication"}


def test_private_databricks_is_never_linked_to_a_private_azure_ml_workspace(tmp_path):
    # MLflow dual-tracking with a Private Link Azure ML workspace is unsupported: every MLflow
    # run creation in Databricks fails ("Unable to connect to the linked AzureML workspace").
    template = compile_template(GENAI / "07-ml-data-platform.bicep", tmp_path)
    workspace = deployment(template, "07-Dbx-")
    link = json.dumps(workspace["properties"]["parameters"]["amlWorkspaceResourceId"])
    assert "enablePublicAccessWithPerimeter" in link
    assert link.index("enablePublicAccessWithPerimeter") < link.index("Microsoft.MachineLearningServices/workspaces")


def test_pipeline_detects_existing_databricks_by_its_real_resource_type():
    text = JOB2.read_text(encoding="utf-8")
    assert "Microsoft.Azure.Databricks/workspaces" not in text
    assert ('variable=databricksExists]$(resource_exists_fuzzy "$targetResourceGroup" '
            '"Microsoft.Databricks/workspaces"') in text


def test_event_hub_private_endpoint_uses_the_avm_zone_group_contract(tmp_path):
    template = compile_template(GENAI / "11-integration.bicep", tmp_path)
    module = deployment(template, "11-EventHub-")
    endpoints = json.dumps(module["properties"]["parameters"]["privateEndpoints"])
    # AVM event-hub/namespace 0.14 has no privateDnsZoneResourceIds property; it was silently ignored.
    assert "privateDnsZoneResourceIds" not in endpoints
    assert "privateDnsZoneGroupConfigs" in endpoints and "privateDnsZoneResourceId" in endpoints
    assert "centralDnsZoneByPolicyInHub" in endpoints


def test_basic_event_hubs_fail_fast_with_an_actionable_message(tmp_path):
    template = compile_template(GENAI / "11-integration.bicep", tmp_path)
    module = deployment(template, "11-EventHub-")
    sku = json.dumps(module["properties"]["parameters"]["skuName"])
    guard = [name for name in json.dumps(template.get("functions", [])).split('"') if name.startswith("requireEventHub")]
    assert guard and guard[0] in sku
    functions = json.dumps(template.get("functions", []))
    assert "fail(" in functions and "Basic" in functions and "Standard" in functions
