"""Pipeline contract for the opt-in Factory Chat Agent Foundry deployment."""
from __future__ import annotations

import ast
import importlib.util
import json

import pytest

from base.config import REPO_ROOT, env_defaults, yaml_defaults
from domain.pipeline_contracts import (
    ADO_ROOT, ADO_SERVICES, FEATURES, GHA_PHASE, evaluate, load_pipeline,
)

FLAG = "enableFactoryChatAgent"
PUBLIC_FLAG = "ENABLE_FACTORY_CHAT_AGENT"
VARIABLES_JSON = REPO_ROOT / "environment_setup/aifactory/variables.json"
JOB = ADO_ROOT / "esml-infra-project" / "jobs" / "job-factory-chat-agent.yaml"
LAUNCHER = REPO_ROOT / "usecase_code/40-agent-factory/46-factory-chat-agent/deploy.py"
STEP = "Deploy Factory Chat Agent in Foundry"


def launcher_inputs():
    source = LAUNCHER.read_text(encoding="utf-8")
    start = source.index("INPUTS = (") + len("INPUTS = ")
    return set(ast.literal_eval(source[start:source.index(")\n", start) + 1]))


def gha_step():
    return next(step for step in load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["steps"]
                if step.get("name") == STEP)


def ado_step():
    return load_pipeline(JOB)["steps"][0]


def test_every_template_declares_the_flag_disabled_next_to_aifactory_mcp():
    assert json.loads(VARIABLES_JSON.read_text(encoding="utf-8"))["dev"][FLAG] == "false"
    assert yaml_defaults()[FLAG] == "false"
    assert env_defaults()[PUBLIC_FLAG] == "false"

    for path, before, value, after in (
        (VARIABLES_JSON, '"enableAIFactoryMCP"', f'"{FLAG}"', '"enableAIGatewaySKU"'),
        (ADO_ROOT / "variables" / "variables.yaml",
         "enableAIFactoryMCP:", f"{FLAG}:", "enableAIGatewaySKU:"),
        (REPO_ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template",
         "ENABLE_AI_FACTORY_MCP=", f"{PUBLIC_FLAG}=", "ENABLE_AI_GATEWAY_SKU="),
    ):
        text = path.read_text(encoding="utf-8")
        assert text.index(before) < text.index(value) < text.index(after)


def test_flag_is_a_deployable_pipeline_feature():
    assert FEATURES[PUBLIC_FLAG] == FLAG


@pytest.mark.parametrize("value", ["false", "true"])
def test_github_binds_the_flag_as_a_boolean_string(value):
    env = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["env"]
    assert evaluate(env[FLAG], {"vars." + PUBLIC_FLAG: value}) == value
    assert evaluate(env[FLAG], {"vars." + PUBLIC_FLAG: ""}) == "false"


def test_github_step_runs_after_private_mcp_and_before_mcp_gateway():
    job = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]
    names = [step.get("name") for step in job["steps"]]
    assert names.index("Deploy private Azure MCP") < names.index(STEP)
    assert names.index(STEP) < names.index("Deploy AI Factory MCP and AI Gateway SKU (project001 Dev)")
    step = gha_step()
    assert '46-factory-chat-agent/deploy.py" apply --apply' in step["run"]
    assert launcher_inputs() <= set(job["env"])


def test_ado_template_is_included_in_the_same_order_and_maps_every_input():
    services = ADO_SERVICES.read_text(encoding="utf-8")
    assert services.index("- template: job-private-azure-mcp.yaml") < services.index(
        "- template: job-factory-chat-agent.yaml")
    assert services.index("- template: job-factory-chat-agent.yaml") < services.index(
        "- template: job-aifactory-mcp-ai-gateway.yaml")
    step = ado_step()
    assert step["task"] == "AzureCLI@2"
    assert step["inputs"]["azureSubscription"] == "${{ parameters.serviceConnection }}"
    assert '46-factory-chat-agent/deploy.py" apply --apply' in step["inputs"]["inlineScript"]
    assert set(step["env"]) - {"FACTORY_CHAT_AGENT_REPOSITORY"} == launcher_inputs()
    assert all(value == f"$({name})" for name, value in step["env"].items()
               if name != "FACTORY_CHAT_AGENT_REPOSITORY")


@pytest.mark.parametrize("phase,enabled,foundry,delete_services,delete_project,expected", [
    ("foundry", "false", "true", "false", "false", False),
    ("foundry", "true", "true", "false", "false", True),
    ("infra", "true", "true", "false", "false", False),
    ("foundry", "true", "false", "false", "false", True),
    ("foundry", "true", "true", "true", "false", False),
    ("foundry", "true", "true", "false", "true", False),
])
def test_both_orchestrators_gate_identically(
    phase, enabled, foundry, delete_services, delete_project, expected,
):
    values = {
        FLAG: enabled,
        "enableAIFoundry": foundry,
        "deleteAllServicesForProject": delete_services,
        "deleteAllForProject": delete_project,
    }
    gha = {"env." + key: value for key, value in values.items()}
    gha.update({"inputs.phase": phase, "success": True})
    ado = {"variables." + key: value for key, value in values.items()}
    ado.update({"parameters.phase": phase, "succeeded": True})
    assert bool(evaluate(gha_step()["if"], gha)) is expected
    assert bool(evaluate(ado_step()["condition"], ado)) is expected


def test_launcher_import_is_offline_and_side_effect_free():
    spec = importlib.util.spec_from_file_location("factory_chat_agent_launcher_contract", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.INPUTS and callable(module.run)
