"""GitHub OIDC client assertions live five minutes; azure/login caches only the ARM token. A step that needs a token for
another audience (storage data plane) long after the job's login fails with AADSTS700024 (aif-138, 2026-10-30, step
102-project-lake-access 44 minutes after login), so the workflow logs in again right before it."""

from pathlib import Path

import pytest
import yaml

from domain.pipeline_contracts import evaluate

ROOT = Path(__file__).resolve().parents[4]
PHASE = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/infra-project-phase.yml"


def _steps():
    workflow = yaml.safe_load(PHASE.read_text(encoding="utf-8"))
    return workflow["jobs"]["deploy-project"]["steps"]


def test_a_fresh_oidc_login_runs_right_before_the_lake_access_data_plane_step():
    steps = _steps()
    names = [step.get("name", "") for step in steps]
    lake = names.index("102-project-lake-access")
    refresh = [index for index, step in enumerate(steps[:lake])
               if step.get("uses", "").startswith("azure/login@") and "Refresh" in step.get("name", "")]
    assert refresh, "no OIDC refresh login before 102-project-lake-access"
    # Only other refresh logins sit between the refresh and the data-plane step.
    assert all(steps[i].get("uses", "").startswith("azure/login@") for i in range(refresh[0], lake))
    conditions = {steps[i]["if"] for i in refresh}
    assert any("inputs.json_identity_auth" in c and "!" not in c for c in conditions)
    assert any("!inputs.json_identity_auth" in c and "AZURE_CLIENT_ID != ''" in c for c in conditions)
    for i in refresh:
        assert steps[i]["with"]["client-id"] in ("${{ inputs.azure_client_id }}", "${{ env.AZURE_CLIENT_ID }}")
        assert "inputs.phase == 'infra'" in steps[i]["if"]


# byor-159 runs 43175705193 and 43188010696: "Deploy Factory Chat Agent in Foundry" failed with AADSTS700024 because the
# job's login happened long before the last (Foundry add-on) steps of the foundry phase.
FOUNDRY_ADDON_STEPS = (
    "Deploy Factory Chat Agent in Foundry",
    "Deploy AI Factory MCP and AI Gateway SKU (project001 Dev)",
    "Deploy AI Factory Agent live voice (any project, Dev)",
    "Prepare Foundry agent for Microsoft 365",
)
FOUNDRY_ADDON_FLAGS = ("enableFactoryChatAgent", "enableAIFactoryMCP", "enableAIGatewaySKU",
                       "addAIFactoryMCP2AIGatewaySKU", "enableAIFactoryAgentLiveVoice", "enableBotService")
JSON_IDENTITY = "${{ inputs.azure_client_id }}"
ENVIRONMENT_IDENTITY = "${{ env.AZURE_CLIENT_ID }}"


def _foundry_refresh():
    steps = _steps()
    names = [step.get("name", "") for step in steps]
    first = min(names.index(name) for name in FOUNDRY_ADDON_STEPS)
    pair = steps[first - 2:first]
    assert all(step.get("uses", "").startswith("azure/login@") and "Refresh" in step.get("name", "")
               for step in pair), "two OIDC refresh logins must directly precede the Foundry add-on steps"
    return {step["with"]["client-id"]: step for step in pair}


def _context(overrides=None):
    context = {"success": True, "inputs.phase": "foundry", "inputs.json_identity_auth": True,
               "env.AZURE_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
               "env.deleteAllServicesForProject": "false", "env.deleteAllForProject": "false",
               **{f"env.{flag}": "false" for flag in FOUNDRY_ADDON_FLAGS}}
    context.update(overrides or {})
    return context


def test_a_fresh_oidc_login_pair_runs_right_before_the_foundry_addon_steps():
    pair = _foundry_refresh()
    assert set(pair) == {JSON_IDENTITY, ENVIRONMENT_IDENTITY}
    assert pair[JSON_IDENTITY]["with"] == {"client-id": JSON_IDENTITY, "tenant-id": "${{ inputs.azure_tenant_id }}",
                                           "subscription-id": "${{ inputs.azure_subscription_id }}"}
    assert pair[ENVIRONMENT_IDENTITY]["with"] == {"client-id": ENVIRONMENT_IDENTITY,
                                                  "tenant-id": "${{ secrets.TENANT_ID }}",
                                                  "subscription-id": "${{ vars.AZURE_SUBSCRIPTION_ID }}"}


@pytest.mark.parametrize("flag", FOUNDRY_ADDON_FLAGS)
def test_the_foundry_refresh_runs_for_its_identity_when_any_addon_is_enabled(flag):
    pair = _foundry_refresh()
    json_run = _context({f"env.{flag}": "true"})
    assert bool(evaluate(pair[JSON_IDENTITY]["if"], json_run)) is True
    assert bool(evaluate(pair[ENVIRONMENT_IDENTITY]["if"], json_run)) is False
    environment_run = {**json_run, "inputs.json_identity_auth": False}
    assert bool(evaluate(pair[JSON_IDENTITY]["if"], environment_run)) is False
    assert bool(evaluate(pair[ENVIRONMENT_IDENTITY]["if"], environment_run)) is True


@pytest.mark.parametrize("override", [
    {"inputs.phase": "infra"},
    {"success": False},
    {"env.deleteAllServicesForProject": "true"},
    {"env.deleteAllForProject": "true"},
    {f"env.{flag}": "false" for flag in FOUNDRY_ADDON_FLAGS},
])
@pytest.mark.parametrize("json_identity", [True, False])
def test_the_foundry_refresh_is_skipped_outside_a_live_foundry_addon_run(override, json_identity):
    pair = _foundry_refresh()
    context = _context({**{f"env.{flag}": "true" for flag in FOUNDRY_ADDON_FLAGS},
                        "inputs.json_identity_auth": json_identity, **override})
    assert not any(bool(evaluate(step["if"], context)) for step in pair.values())


def test_the_environment_identity_refresh_needs_a_client_id():
    pair = _foundry_refresh()
    context = _context({"env.enableFactoryChatAgent": "true", "inputs.json_identity_auth": False,
                        "env.AZURE_CLIENT_ID": ""})
    assert bool(evaluate(pair[ENVIRONMENT_IDENTITY]["if"], context)) is False
