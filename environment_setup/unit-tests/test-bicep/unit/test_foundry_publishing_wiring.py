"""Native Foundry channel preparation is optional, late, and never publishes."""
import json
import runpy

import pytest

from base.config import REPO_ROOT
from domain.pipeline_contracts import ADO_ROOT, ADO_SERVICES, GHA_PHASE, evaluate, load_pipeline

STEP = "Prepare Foundry agent for Microsoft 365"
TEMPLATE = "job-foundry-publishing.yaml"
KEYS = {
    "botFoundryProjectResourceId": "",
    "botFoundryAgentName": "",
    "botEnableM365PublicEndpoint": "false",
}
INPUTS = {
    "enableBotService", "enableAIFoundry", "deleteAllServicesForProject",
    "deleteAllForProject", "dev_test_prod_sub_id", "tenantId", *KEYS,
}


def gha_step():
    return next(s for s in load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["steps"]
                if s.get("name") == STEP)


def ado_step():
    return load_pipeline(ADO_ROOT / "esml-infra-project" / "jobs" / TEMPLATE)["steps"][0]


def test_native_preparation_is_unconfigured_by_default():
    values = json.loads((REPO_ROOT / "environment_setup/aifactory/variables.json").read_text())
    assert {key: values["dev"][key] for key in KEYS} == KEYS
    select = runpy.run_path(str(REPO_ROOT / "environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py"))["selected_values"]
    for environment in ("dev", "stage", "test", "prod"):
        effective, _ = select(values, environment)
        assert {key: effective[key] for key in KEYS} == KEYS
    env = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["env"]
    for key in KEYS:
        assert key in env
    assert INPUTS <= set(env)


@pytest.mark.parametrize("phase,enabled,deleting,expected", [
    ("foundry", "true", "false", True),
    ("foundry", "false", "false", False),
    ("infra", "true", "false", False),
    ("foundry", "true", "true", False),
])
def test_providers_gate_preparation_with_existing_bot_flag(phase, enabled, deleting, expected):
    values = {
        "enableBotService": enabled, "deleteAllServicesForProject": deleting,
        "deleteAllForProject": deleting,
    }
    gha = {"env." + key: value for key, value in values.items()}
    gha.update({"inputs.phase": phase, "success": True})
    ado = {"variables." + key: value for key, value in values.items()}
    ado.update({"parameters.phase": phase, "succeeded": True})
    assert bool(evaluate(gha_step()["if"], gha)) is expected
    assert bool(evaluate(ado_step()["condition"], ado)) is expected


def test_both_providers_plan_then_apply_the_reviewed_target():
    ado = ado_step()
    assert set(ado["env"]) - {"FOUNDRY_PUBLISHING_REPOSITORY"} == INPUTS
    for script in (gha_step()["run"], ado["inputs"]["inlineScript"]):
        assert script.index(' plan ') < script.index(' apply ')
        assert "--reviewed-plan" in script and "--apply" in script
        assert "prepare-foundry-publishing.py" in script
        assert "account set" not in script
        assert "mktemp" in script and "trap " in script


def test_preparation_follows_all_agent_creation():
    names = [s.get("name") for s in load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["steps"]]
    assert names.index("Deploy AI Factory Agent live voice (any project, Dev)") < names.index(STEP)
    assert names.index(STEP) < names.index("Remove run-specific reviewed configuration")
    ado = ADO_SERVICES.read_text(encoding="utf-8")
    assert ado.index("job-aifactory-agent-live-voice.yaml") < ado.index(TEMPLATE)


def test_native_mode_does_not_create_an_unrelated_bot_or_fabricate_an_application():
    source = (REPO_ROOT / "environment_setup/aifactory/bicep/esml-genai-1/11-integration.bicep").read_text(encoding="utf-8")
    assert "param botFoundryAgentName string = ''" in source
    assert "&& !useNativeFoundryPublishing" in source
    assert "'agent-001'" not in source
    assert "agentEndpointTemplate" not in source
    assert "agentEndpoint: botAgentEndpoint" in source
    module = (REPO_ROOT / "environment_setup/aifactory/bicep/modules/botService.bicep").read_text(encoding="utf-8")
    assert "auto-creates an Azure AD App Registration" not in module
    assert "required for Foundry listing" not in module


def test_native_selection_reaches_integration_in_both_providers():
    from domain.pipeline_contracts import deployments
    for path, value in ((ADO_SERVICES, "$BOT_FOUNDRY_AGENT_NAME"),
                        (GHA_PHASE, "$botFoundryAgentName")):
        integration = next(d for d in deployments(load_pipeline(path)) if d.module == "11-integration.bicep")
        assert integration.parameters["botFoundryAgentName"] == value


@pytest.mark.parametrize("environment", ["stage", "test", "prod"])
@pytest.mark.parametrize("later", [{}, {"stage_prod": {}}, {"test": {}, "prod": {}}])
def test_existing_configs_never_inherit_dev_native_target_or_network_consent(environment, later):
    select = runpy.run_path(str(REPO_ROOT / "environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py"))["selected_values"]
    values, _ = select({"dev": {
        "botFoundryProjectResourceId": "/dev-project",
        "botFoundryAgentName": "dev-agent",
        "botEnableM365PublicEndpoint": "true",
        "enableBotService": "true",
    }, **later}, environment)
    assert {key: values[key] for key in KEYS} == KEYS
    assert values["enableBotService"] == "true"


def test_explicit_later_environment_target_and_consent_override_resets():
    select = runpy.run_path(str(REPO_ROOT / "environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py"))["selected_values"]
    target = {
        "botFoundryProjectResourceId": "/production-project",
        "botFoundryAgentName": "production-agent",
        "botEnableM365PublicEndpoint": "true",
    }
    values, section = select({"dev": {**target, "botFoundryAgentName": "dev-agent"}, "prod": target}, "prod")
    assert {key: values[key] for key in KEYS} == target
    assert section == "prod"
