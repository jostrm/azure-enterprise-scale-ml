"""Offline contracts for the Agent Chat portal entry; never contacts Azure."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest


ROOT = Path(__file__).resolve().parents[4]
PORTAL = ROOT / "portal" / "agent-chat"


def template():
    return json.loads((PORTAL / "azuredeploy.json").read_text(encoding="utf-8"))


def run_template():
    document = template()
    resources = document["resources"]
    if resources[0]["type"] == "Microsoft.Resources/deployments":
        return resources[0]["properties"]["template"]
    return document


def test_button_opens_a_real_separate_azure_template():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\((https://portal\.azure\.com/[^)]+)\)", readme)
    assert any("portal-125" in unquote(link) for link in links)
    agent_link = next(link for link in links if "/main/portal/agent-chat/azuredeploy.json" in unquote(link))
    assert "/uiFormDefinitionUri/" in agent_link
    assert "/main/portal/agent-chat/form.json" in unquote(agent_link)
    assert "does not deploy ESAF Agent Chat" in readme
    assert "existing private Dev project" in readme


def test_portal_waits_for_actual_script_success_and_does_not_create_infrastructure():
    document = run_template()
    resources = document["resources"]
    assert len(resources) == 1
    command = resources[0]
    assert command["type"] == "Microsoft.Compute/virtualMachines/runCommands"
    assert command["location"] == "[parameters('runnerLocation')]"
    properties = command["properties"]
    assert properties["asyncExecution"] is False
    assert properties["treatFailureAsDeploymentFailure"] is True
    assert properties["timeoutInSeconds"] >= 7200
    script = properties["source"]["script"]
    variable = re.fullmatch(r"\[variables\('([^']+)'\)\]", script)
    if variable:
        script = document["variables"][variable[1]]
    assert script == (PORTAL / "run.sh").read_text(encoding="utf-8")
    assert "\r" not in script, "The embedded Linux script must use LF line endings."
    assert "scriptUri" not in properties["source"]
    assert not any("Password" in name or "Secret" in name for name in document["parameters"])


def test_portal_passes_inputs_as_environment_values_not_shell_code():
    document = run_template()
    parameters = document["resources"][0]["properties"]["parameters"]
    values = {item["name"]: item["value"] for item in parameters}
    assert values["AIF_CONSUMER_ROOT"] == "[parameters('consumerRoot')]"
    assert values["AIF_PROJECT_NUMBER"] == "[parameters('projectNumber')]"
    assert values["AIF_PYTHON"] == "[parameters('pythonExecutable')]"
    assert values["AIF_IDENTITY_CLIENT_ID"] == "[parameters('managedIdentityClientId')]"
    assert values["AIF_SUBSCRIPTION_ID"] == "[parameters('projectSubscriptionId')]"
    assert values["AIF_TENANT_ID"] == "[subscription().tenantId]"
    assert values["AIF_CONFIGURATION_PATH"] == "[parameters('configurationPath')]"
    assert values["AIF_VM_IDENTITY"] == "[string(parameters('vmIdentity'))]"
    assert "AIF_RUN_ID" in values


def test_vm_metadata_supplies_location_and_identity_without_user_input():
    document = template()
    required = {key for key, value in document["parameters"].items() if "defaultValue" not in value}
    assert required == {"runnerVmName"}
    for name in ("consumerRoot", "pythonExecutable", "managedIdentityClientId",
                 "projectSubscriptionId", "runnerLocation"):
        assert document["parameters"][name]["defaultValue"] == ""
    nested = document["resources"][0]
    assert nested["type"] == "Microsoft.Resources/deployments"
    parameters = nested["properties"]["parameters"]
    location = json.dumps(parameters["runnerLocation"])
    assert "reference(" in location
    assert ".location" in location
    assert "reference(" in parameters["vmIdentity"]["value"]
    assert "identity" in parameters["vmIdentity"]["value"]
    assert "templateLink" not in nested["properties"]


def test_friendly_form_selects_vm_and_hides_optional_override_fields():
    form = json.loads((PORTAL / "form.json").read_text(encoding="utf-8"))["view"]
    steps = form["properties"]["steps"]
    basic = {item["name"]: item for item in steps[0]["elements"]}
    assert basic["runner"]["type"] == "Microsoft.Solutions.ResourceSelector"
    assert basic["runner"]["resourceType"] == "Microsoft.Compute/virtualMachines"
    assert basic["projectNumber"]["defaultValue"] == "001"
    advanced = {item["name"]: item for item in steps[1]["elements"]}
    assert advanced["consumerRoot"]["label"] == "Factory project folder on VM"
    assert advanced["pythonExecutable"]["label"] == "Prepared Python on VM"
    for name in ("consumerRoot", "pythonExecutable", "managedIdentityClientId",
                 "configurationPath", "projectSubscriptionId"):
        field = advanced[name]
        assert field["defaultValue"] == ""
        assert field["constraints"]["required"] is False
        assert "showAdvanced" in field["visible"]
        assert "showAdvanced" in form["outputs"]["parameters"][name]
    assert form["outputs"]["kind"] == "ResourceGroup"
    assert form["outputs"]["resourceGroupId"] == "[first(split(steps('basics').runner.id, '/providers/'))]"
    assert form["outputs"]["location"] == "[steps('basics').runner.location]"
    assert form["outputs"]["parameters"]["runnerVmName"] == "[steps('basics').runner.name]"
    parameters = template()["parameters"]
    assert set(form["outputs"]["parameters"]) <= set(parameters)
    assert "runId" not in form["outputs"]["parameters"]


def test_agent_readme_explains_button_inside_requested_use_case_section():
    text = (ROOT / "usecase_code/40-agent-factory/40-aifactory-agent/readme.md").read_text(encoding="utf-8")
    section = text.split("## Use case template example", 1)[1].split("\n## ", 1)[0]
    assert "### Deploy ESAF Agent Chat to Azure" in section
    assert "uiFormDefinitionUri" in section
    assert "Factory project folder on VM" in section and "Prepared Python on VM" in section
    assert "/opt/esaf/consumer" in section and ".venv-agent-operator/bin/python" in section
    assert "multiple" in section.lower() and "identity" in section.lower()


def test_all_agent_buttons_use_the_same_form_and_published_template():
    paths = ("README.md", "documentation/v2/20-29/24-end-2-end-setup.md",
             "documentation/v2/quickstarts/04-first-agent-chat.md",
             "usecase_code/40-agent-factory/40-aifactory-agent/readme.md")
    urls = []
    for path in paths:
        text = (ROOT / path).read_text(encoding="utf-8")
        links = re.findall(r"\]\((https://portal\.azure\.com/[^)]+)\)", text)
        agent = [link for link in links if "/main/portal/agent-chat/azuredeploy.json" in unquote(link)]
        assert len(agent) == 1, path
        urls.extend(agent)
    assert len(set(urls)) == 1
    decoded = unquote(urls[0])
    assert decoded.startswith("https://portal.azure.com/#blade/Microsoft_Azure_CreateUIDef/CustomDeploymentBlade/uri/")
    assert decoded.endswith("/uiFormDefinitionUri/https://raw.githubusercontent.com/jostrm/"
                            "azure-enterprise-scale-ml/main/portal/agent-chat/form.json")


def test_compiled_template_matches_bicep(tmp_path):
    bicep = shutil.which("bicep")
    if not bicep:
        pytest.skip("Bicep compiler not installed")
    output = tmp_path / "azuredeploy.json"
    result = subprocess.run(
        [bicep, "build", str(PORTAL / "main.bicep"), "--outfile", str(output)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    actual = json.loads(output.read_text(encoding="utf-8"))
    committed = template()
    # Compiler metadata varies by the installed compiler; the executable contract must not.
    actual.pop("metadata", None)
    committed.pop("metadata", None)
    assert actual == committed
