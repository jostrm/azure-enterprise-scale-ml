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


def test_button_opens_a_real_separate_azure_template():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\((https://portal\.azure\.com/[^)]+)\)", readme)
    assert any("portal-125" in unquote(link) for link in links)
    assert any("/main/portal/agent-chat/azuredeploy.json" in unquote(link) for link in links)
    assert "does not deploy ESAF Agent Chat" in readme
    assert "existing private Dev project" in readme


def test_portal_waits_for_actual_script_success_and_does_not_create_infrastructure():
    document = template()
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
    document = template()
    parameters = document["resources"][0]["properties"]["parameters"]
    values = {item["name"]: item["value"] for item in parameters}
    assert values["AIF_CONSUMER_ROOT"] == "[parameters('consumerRoot')]"
    assert values["AIF_PROJECT_NUMBER"] == "[parameters('projectNumber')]"
    assert values["AIF_PYTHON"] == "[parameters('pythonExecutable')]"
    assert values["AIF_IDENTITY_CLIENT_ID"] == "[parameters('managedIdentityClientId')]"
    assert values["AIF_SUBSCRIPTION_ID"] == "[parameters('projectSubscriptionId')]"
    assert values["AIF_TENANT_ID"] == "[subscription().tenantId]"
    assert values["AIF_CONFIGURATION_PATH"] == "[parameters('configurationPath')]"
    assert "AIF_RUN_ID" in values


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
