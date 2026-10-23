"""Defender for Cloud defaults for services other than Key Vault secrets, offline.

Resource logs reach the Log Analytics workspace by default for the common and admin Key Vaults, AI Search,
AI Services and Databricks, and AI Search accepts only Entra ID (key access disabled) unless an operator turns
aiSearchDisableLocalAuth off. No consumer in this repository uses an AI Search key (agent knowledge index,
Foundry and hub connections, indexers, pipelines and the MCP all use Entra ID or managed identities).
"""
from pathlib import Path
import re

import pytest

from base.arm_expressions import arm_value, compile_bicep, parameters_with_defaults, resources


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
RG_LEVEL = BICEP / "esml-common/main/13-rgLevel.bicep"
SEARCH = BICEP / "modules/aiSearch.bicep"
SEARCH_DEPLOYMENT = BICEP / "modules/services/aiSearchDeployment.bicep"
ENTRYPOINTS = (BICEP / "esml-genai-1/03-cognitive-services.bicep", BICEP / "esml-genai-1/03b-ai-search.bicep")
DATA_PLATFORM = BICEP / "esml-genai-1/07-ml-data-platform.bicep"


def module_body(source, symbol):
    match = re.search(rf"^module {symbol} '[^']*'[^\n]*$", source, re.M)
    assert match, symbol
    return match[0], source[match.end():source.index("\n}", match.end())]


# --- resource logs ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("symbol,vault,after", [("kvCmnDiagnostics", "kvNameCommon", "kvCmn"),
                                                ("kvAdminDiagnostics", "kvNameCommonAdmin", "kvAdmin")])
def test_common_and_admin_vaults_send_audit_events_to_log_analytics(symbol, vault, after):
    source = RG_LEVEL.read_text(encoding="utf-8")
    header, body = module_body(source, symbol)
    assert "/diagnostics/keyVaultDiagnostics.bicep'" in header
    assert "if(!deployOnlyAIGatewayNetworking)" in header.replace(" ", "")
    assert re.search(rf"^\s+keyVaultName: {vault}$", body, re.M)
    assert re.search(r"^\s+logAnalyticsWorkspaceId: logAnalyticsWorkspaceOpInsight!?\.outputs\.logAnalyticsWkspId$",
                     body, re.M)
    assert re.search(rf"^\s+{after}$", body, re.M)


def test_key_vault_diagnostics_always_include_audit_events():
    source = (BICEP / "modules/diagnostics/keyVaultDiagnostics.bicep").read_text(encoding="utf-8")
    assert source.count("category: 'AuditEvent'") == 2  # silver and bronze; gold sends allLogs
    assert "categoryGroup: 'allLogs'" in source


@pytest.mark.parametrize("path", [SEARCH_DEPLOYMENT, *ENTRYPOINTS])
@pytest.mark.parametrize("flag", ["skipDiagAISearch", "skipDiagAIServices"])
def test_search_and_ai_services_diagnostics_are_on_by_default(path, flag):
    source = path.read_text(encoding="utf-8")
    if f"param {flag} " in source:
        assert f"param {flag} bool = false" in source


def test_databricks_workspace_sends_resource_logs_to_log_analytics():
    source = DATA_PLATFORM.read_text(encoding="utf-8")
    start = source.index("avm/res/databricks/workspace:")
    body = source[start:source.index("\n}", start)]
    settings = re.search(r"^\s+diagnosticSettings: \[(.*?)^\s+\]", body, re.M | re.S)
    assert settings, "Databricks workspace has no diagnosticSettings"
    assert "workspaceResourceId: logAnalyticsWorkspaceOpInsight.id" in settings[1]
    assert "categoryGroup: 'allLogs'" in settings[1]


# --- AI Search key access ---------------------------------------------------------------------------------

def search_properties(**values):
    template = compile_bicep(SEARCH)
    parameters = parameters_with_defaults(template, {"aiSearchName": "srch", "subnetName": "snet", "tags": {},
                                                     "location": "swedencentral", "enableSharedPrivateLink": False,
                                                     "privateEndpointName": "pe", "vnetName": "vnet",
                                                     "vnetResourceGroupName": "rg", **values})
    service = next(item for item in resources(template) if item["type"] == "Microsoft.Search/searchServices")
    return {key: arm_value(service["properties"][key], parameters, template)
            for key in ("disableLocalAuth", "authOptions")}


def test_search_disables_key_access_by_default():
    # ARM rejects authOptions when local authentication is disabled.
    assert search_properties() == {"disableLocalAuth": True, "authOptions": None}


def test_search_keeps_keys_and_the_bearer_challenge_when_the_operator_opts_out():
    assert search_properties(disableLocalAuth=False) == {
        "disableLocalAuth": False,
        "authOptions": {"aadOrApiKey": {"aadAuthFailureMode": "http401WithBearerChallenge"}}}


def test_search_key_switch_reaches_bicep_in_both_providers():
    templates = BICEP / "copy_to_local_settings"
    ado = (templates / "azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
           ).read_text(encoding="utf-8")
    gha = (templates / "github-actions/infra-project-phase.yml").read_text(encoding="utf-8")
    # ADO maps the variable through env and keeps the Bicep default when an older variables.yaml lacks it.
    assert "    AI_SEARCH_DISABLE_LOCAL_AUTH: $(aiSearchDisableLocalAuth)" in ado
    assert "[[ \"$AI_SEARCH_DISABLE_LOCAL_AUTH\" != '$''(aiSearchDisableLocalAuth)' ]] || AI_SEARCH_DISABLE_LOCAL_AUTH=true" in ado
    assert '--parameters aiSearchDisableLocalAuth="$AI_SEARCH_DISABLE_LOCAL_AUTH"' in ado
    assert '--parameters aiSearchDisableLocalAuth="${{ env.aiSearchDisableLocalAuth }}"' in gha
    assert "aiSearchDisableLocalAuth: ${{ vars.AI_SEARCH_DISABLE_LOCAL_AUTH || 'true' }}" in gha


def test_search_key_switch_reaches_the_module_from_both_entrypoints():
    deployment = SEARCH_DEPLOYMENT.read_text(encoding="utf-8")
    assert "param aiSearchDisableLocalAuth bool = true" in deployment
    assert "disableLocalAuth: aiSearchDisableLocalAuth" in deployment
    for path in ENTRYPOINTS:
        source = path.read_text(encoding="utf-8")
        assert "param aiSearchDisableLocalAuth bool = true" in source, path.name
        orchestration = re.search(r"module\s+\w+\s+'[^']*aiSearchDeployment\.bicep'[^\n]*\n(.*?)\n\}", source, re.S)
        assert "aiSearchDisableLocalAuth: aiSearchDisableLocalAuth" in orchestration[1], path.name
