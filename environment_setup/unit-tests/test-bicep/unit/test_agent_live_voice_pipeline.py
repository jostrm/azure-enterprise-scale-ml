"""Contract for the late project-pipeline step that deploys the live-voice AI Factory Agent chat application."""
from __future__ import annotations

import ast
import importlib.util

import pytest

from base.config import REPO_ROOT, yaml_defaults
from domain.pipeline_contracts import ADO_ROOT, ADO_SERVICES, GHA_PHASE, evaluate, load_pipeline, objects

CHAT_FLAG = "enableFactoryChatAgent"
VOICE_FLAG = "enableAIFactoryAgentLiveVoice"
FLAGS = {
    CHAT_FLAG: "ENABLE_FACTORY_CHAT_AGENT",
    VOICE_FLAG: "ENABLE_AI_FACTORY_AGENT_LIVE_VOICE",
}
INPUTS = {
    "aifactoryAgentEntraAppId": "AIFACTORY_AGENT_ENTRA_APP_ID",
    "aifactoryAgentContainerAppsEnvironment": "AIFACTORY_AGENT_CONTAINER_APPS_ENVIRONMENT",
    "aifactoryAgentReaderObjectIds": "AIFACTORY_AGENT_READER_OBJECT_IDS",
    "aifactoryAgentVoiceName": "AIFACTORY_AGENT_VOICE_NAME",
    "aifactoryAgentVoiceLanguages": "AIFACTORY_AGENT_VOICE_LANGUAGES",
}
JOB = ADO_ROOT / "esml-infra-project" / "jobs" / "job-aifactory-agent-live-voice.yaml"
LAUNCHER = REPO_ROOT / "usecase_code/40-agent-factory/47-aifactory-agent-live-voice/deploy.py"
STEP = "Deploy AI Factory Agent live voice (project001 Dev)"
PREVIOUS_STEP = "Deploy AI Factory MCP and AI Gateway SKU (project001 Dev)"
CALL = "47-aifactory-agent-live-voice/deploy.py\" apply --apply"


def launcher_inputs():
    source = LAUNCHER.read_text(encoding="utf-8")
    start = source.index("INPUTS = (") + len("INPUTS = ")
    return set(ast.literal_eval(source[start:source.index(")\n", start) + 1]))


@pytest.mark.parametrize("flag,public", FLAGS.items())
@pytest.mark.parametrize("value", ["false", "true"])
def test_github_binds_each_flag_as_a_boolean_string_that_defaults_to_false(flag, public, value):
    env = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["env"]
    context = {"vars." + other: ("false" if value == "true" else "true") for other in FLAGS.values()}
    context["vars." + public] = value
    assert evaluate(env[flag], context) == value
    assert evaluate(env[flag], {"vars." + public: ""}) == "false"


def test_github_step_follows_the_mcp_gateway_and_chat_agent_steps_with_every_launcher_input_bound():
    job = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]
    names = [step.get("name") for step in job["steps"]]
    assert names.index(STEP) == names.index(PREVIOUS_STEP) + 1
    assert names.index("Deploy Factory Chat Agent in Foundry") < names.index(STEP)
    step = job["steps"][names.index(STEP)]
    assert CALL in step["run"] and step["shell"] == "bash"
    assert launcher_inputs() - {"projectResourceGroup"} <= set(job["env"])
    for name, public in INPUTS.items():
        assert evaluate(job["env"][name], {"vars." + public: ""}) == ""
        assert f"vars.{public}" in job["env"][name]
    assert not [item for item in objects(step) if "deleteAll" in str(item.get("run", ""))]


def test_ado_template_is_included_after_the_mcp_gateway_and_maps_every_input():
    services = ADO_SERVICES.read_text(encoding="utf-8")
    assert services.index("- template: job-factory-chat-agent.yaml") < services.index("- template: job-aifactory-agent-live-voice.yaml")
    assert services.index("- template: job-aifactory-mcp-ai-gateway.yaml") < services.index("- template: job-aifactory-agent-live-voice.yaml")
    assert services.index("- template: job-aifactory-agent-live-voice.yaml") < services.index("region-report-steps.yaml")
    step = load_pipeline(JOB)["steps"][0]
    assert step["task"] == "AzureCLI@2" and step["displayName"] == "72-aifactory-agent-live-voice"
    assert step["inputs"]["azureSubscription"] == "${{ parameters.serviceConnection }}"
    assert CALL in step["inputs"]["inlineScript"]
    env = step["env"]
    assert set(env) - {"AIFACTORY_AGENT_REPOSITORY"} == launcher_inputs() - {"projectResourceGroup"}
    assert all(value == f"$({name})" for name, value in env.items() if name != "AIFACTORY_AGENT_REPOSITORY")
    assert all(name in yaml_defaults() for name in (*FLAGS, *INPUTS))


def gha_condition():
    job = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]
    return next(step for step in job["steps"] if step.get("name") == STEP)["if"]


def ado_condition():
    return load_pipeline(JOB)["steps"][0]["condition"]


@pytest.mark.parametrize("phase,flags,delete,expected", [
    ("foundry", ("false", "false"), "false", False),
    ("foundry", ("true", "false"), "false", False),  # chat alone only needs the Foundry Agent step (70-factory-chat-agent)
    ("foundry", ("true", "true"), "false", True),
    ("foundry", ("false", "true"), "false", True),  # reaches the launcher, which rejects voice without chat loudly
    ("infra", ("true", "true"), "false", False),
    ("foundry", ("true", "true"), "true", False),
])
def test_both_orchestrators_gate_identically(phase, flags, delete, expected):
    values = dict(zip(FLAGS, flags))
    for deletion in ("deleteAllServicesForProject", "deleteAllForProject"):
        others = {"deleteAllServicesForProject": "false", "deleteAllForProject": "false", deletion: delete}
        gha = {"env." + key: value for key, value in {**values, **others}.items()}
        gha.update({"inputs.phase": phase, "success": True})
        ado = {"variables." + key: value for key, value in {**values, **others}.items()}
        ado.update({"parameters.phase": phase, "succeeded": True})
        assert bool(evaluate(gha_condition(), gha)) is expected
        assert bool(evaluate(ado_condition(), ado)) is expected


def test_the_step_is_skipped_when_a_previous_step_failed():
    values = {"env.enableFactoryChatAgent": "true", "env.enableAIFactoryAgentLiveVoice": "true",
              "env.deleteAllServicesForProject": "false", "env.deleteAllForProject": "false", "inputs.phase": "foundry"}
    assert bool(evaluate(gha_condition(), {**values, "success": False})) is False


def test_launcher_is_importable_without_azure_access_and_skips_offline():
    spec = importlib.util.spec_from_file_location("agent_chat_launcher_contract", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.INPUTS and callable(module.run)
    off = {name: "false" for name in FLAGS}
    result = module.run(type("Args", (), {"command": "apply", "apply": True})(), off, lambda *_: pytest.fail("Azure contacted"))
    assert result["mode"] == "skipped" and result["mutations"] is False
