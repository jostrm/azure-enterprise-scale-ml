"""Contract for the AI Factory MCP & AI Gateway SKU flags and their late project-pipeline step."""
from __future__ import annotations

import ast
import importlib.util
import json

import pytest

from base.config import REPO_ROOT, env_defaults, yaml_defaults
from domain.pipeline_contracts import (
    ADO_GATEWAY, ADO_ROOT, ADO_SERVICES, CONFIG_ONLY_EXCEPTIONS, EXTRA_FEATURES, FEATURES, GHA_GATEWAY, GHA_PHASE,
    evaluate, load_pipeline, objects,
)

FLAGS = {
    "enableAIFactoryMCP": "ENABLE_AI_FACTORY_MCP",
    "enableAIGatewaySKU": "ENABLE_AI_GATEWAY_SKU",
    "addAIFactoryMCP2AIGatewaySKU": "ADD_AI_FACTORY_MCP_2_AI_GATEWAY_SKU",
}
INPUTS = {
    "aifactoryMcpImage": "AIFACTORY_MCP_IMAGE",
    "aifactoryMcpApiImage": "AIFACTORY_MCP_API_IMAGE",
    "aifactoryMcpEntraAppId": "AIFACTORY_MCP_ENTRA_APP_ID",
    "aifactoryMcpContainerAppsEnvironment": "AIFACTORY_MCP_CONTAINER_APPS_ENVIRONMENT",
    "aiGatewaySkuResourceId": "AI_GATEWAY_SKU_RESOURCE_ID",
    "aiGatewaySkuOutboundSubnetId": "AI_GATEWAY_SKU_OUTBOUND_SUBNET_ID",
    "aifactoryMcpClassicApimResourceIds": "AIFACTORY_MCP_CLASSIC_APIM_RESOURCE_IDS",
    "aifactoryMcpContainerAppResourceId": "AIFACTORY_MCP_CONTAINER_APP_RESOURCE_ID",
}
# Publishes the MCP on the AI gateway pipeline's classic APIM; it needs enableAIFactoryMCP, so it adds no gate.
APIM_FLAG = {"addAIFactoryMCP2APIM": "ADD_AI_FACTORY_MCP_2_APIM"}
APIM_GATEWAY = {
    "apimGatewaySubscriptionId": "APIM_GATEWAY_SUBSCRIPTION_ID",
    "apimGatewayResourceGroup": "APIM_GATEWAY_RESOURCE_GROUP",
    "apimGatewayServiceName": "APIM_GATEWAY_SERVICE_NAME",
}
VARIABLES_JSON = REPO_ROOT / "environment_setup/aifactory/variables.json"
JOB = ADO_ROOT / "esml-infra-project" / "jobs" / "job-aifactory-mcp-ai-gateway.yaml"
LAUNCHER = REPO_ROOT / "usecase_code/40-agent-factory/45-aifactory-mcp-gateway/deploy.py"
STEP = "Deploy AI Factory MCP and AI Gateway SKU (project001 Dev)"
GATEWAY_STEP = "Expose the AI Factory MCP on APIM"
POOL_STEP = "Deploy APIM Azure OpenAI pool"


def launcher_tuple(name):
    source = LAUNCHER.read_text(encoding="utf-8")
    start = source.index(f"\n{name} = (") + len(f"\n{name} = ")
    return set(ast.literal_eval(source[start:source.index(")\n", start) + 1]))


def launcher_inputs():
    return launcher_tuple("INPUTS")


@pytest.mark.parametrize("name,public,default", [
    *((flag, public, "false") for flag, public in {**FLAGS, **APIM_FLAG}.items()),
    *((name, public, "") for name, public in INPUTS.items()),
])
def test_every_template_declares_the_exact_setting_with_safe_default(name, public, default):
    assert json.loads(VARIABLES_JSON.read_text(encoding="utf-8"))["dev"][name] == default
    assert yaml_defaults()[name] == default
    assert env_defaults()[public] == default


def test_flags_are_reviewed_pipeline_features_not_configuration_only():
    flags = {**FLAGS, **APIM_FLAG}
    assert {**FEATURES, **EXTRA_FEATURES}.items() >= {public: flag for flag, public in flags.items()}.items()
    assert not set(flags.values()) & set(CONFIG_ONLY_EXCEPTIONS)


@pytest.mark.parametrize("flag,public", FLAGS.items())
@pytest.mark.parametrize("value", ["false", "true"])
def test_github_binds_each_flag_as_a_boolean_string(flag, public, value):
    env = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["env"]
    context = {"vars." + other: ("false" if value == "true" else "true") for other in FLAGS.values()}
    context["vars." + public] = value
    assert evaluate(env[flag], context) == value
    assert evaluate(env[flag], {"vars." + public: ""}) == "false"


def test_github_step_runs_last_in_foundry_with_every_launcher_input_bound():
    job = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]
    names = [step.get("name") for step in job["steps"]]
    assert names.index(STEP) == names.index("Deploy Factory Chat Agent in Foundry") + 1
    step = job["steps"][names.index(STEP)]
    assert "45-aifactory-mcp-gateway/deploy.py\" apply --apply" in step["run"]
    assert launcher_inputs() - {"projectResourceGroup"} <= set(job["env"])
    for name, public in INPUTS.items():
        assert evaluate(job["env"][name], {"vars." + public: ""}) == ""
        assert f"vars.{public}" in job["env"][name]


def test_ado_template_is_included_after_azure_mcp_and_maps_every_input():
    services = ADO_SERVICES.read_text(encoding="utf-8")
    assert services.index("- template: job-private-azure-mcp.yaml") < services.index("- template: job-aifactory-mcp-ai-gateway.yaml")
    step = load_pipeline(JOB)["steps"][0]
    assert step["task"] == "AzureCLI@2"
    assert step["inputs"]["azureSubscription"] == "${{ parameters.serviceConnection }}"
    assert "45-aifactory-mcp-gateway/deploy.py\" apply --apply" in step["inputs"]["inlineScript"]
    env = step["env"]
    assert set(env) - {"MCP_GATEWAY_REPOSITORY"} == launcher_inputs() - {"projectResourceGroup"}
    assert all(value == f"$({name})" for name, value in env.items() if name != "MCP_GATEWAY_REPOSITORY")
    for name in (*FLAGS, *INPUTS):
        assert name in yaml_defaults()


def gha_condition():
    job = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]
    return next(step for step in job["steps"] if step.get("name") == STEP)["if"]


def ado_condition():
    return load_pipeline(JOB)["steps"][0]["condition"]


@pytest.mark.parametrize("phase,flags,delete,expected", [
    ("foundry", ("false", "false", "false"), "false", False),
    ("foundry", ("true", "false", "false"), "false", True),
    ("foundry", ("false", "true", "false"), "false", True),
    ("foundry", ("false", "false", "true"), "false", True),
    ("infra", ("true", "true", "true"), "false", False),
    ("foundry", ("true", "true", "true"), "true", False),
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


@pytest.mark.parametrize("value", ["false", "true"])
def test_project_step_binds_the_ai_gateway_apim_so_it_joins_the_mcp_callers(value):
    env = load_pipeline(GHA_PHASE)["jobs"]["deploy-project"]["env"]
    for name, public in APIM_FLAG.items():
        assert evaluate(env[name], {"vars." + public: value}) == value
        assert evaluate(env[name], {"vars." + public: ""}) == "false"
    for name, public in APIM_GATEWAY.items():
        assert evaluate(env[name], {"vars." + public: ""}) == ""
        assert f"vars.{public}" in env[name]


def test_apim_launcher_inputs_are_a_subset_of_the_project_inputs():
    assert launcher_tuple("APIM_INPUTS") <= launcher_inputs()
    assert {*APIM_FLAG, *APIM_GATEWAY, "aifactoryMcpEntraAppId", "aifactoryMcpContainerAppResourceId",
            "enableAIFactoryMCP"} <= launcher_tuple("APIM_INPUTS")


def gateway_step(path, key):
    steps = load_pipeline(path)
    steps = steps["steps"] if "steps" in steps else steps["jobs"]["deploy"]["steps"]
    names = [step.get(key) for step in steps]
    assert names.index(GATEWAY_STEP) == names.index(POOL_STEP) + 1, "the MCP API follows the OpenAI pool (SKU changes first)"
    return steps[names.index(GATEWAY_STEP)]


@pytest.mark.parametrize("value", ["false", "true"])
def test_ai_gateway_pipelines_publish_the_mcp_on_apim_behind_the_flag(value):
    ado = gateway_step(ADO_GATEWAY, "displayName")
    gha = gateway_step(GHA_GATEWAY, "name")
    assert bool(evaluate(ado["condition"], {"variables.addAIFactoryMCP2APIM": value})) == (value == "true")
    # Like GHA's implicit success(): a failed OpenAI pool/SKU step stops the MCP step.
    assert not evaluate(ado["condition"], {"variables.addAIFactoryMCP2APIM": "true", "success": False})
    assert bool(evaluate(gha["if"], {"env.ADD_AI_FACTORY_MCP_2_APIM": value})) == (value == "true")
    job_env = load_pipeline(GHA_GATEWAY)["jobs"]["deploy"]["env"]
    assert evaluate(job_env["ADD_AI_FACTORY_MCP_2_APIM"], {"vars.ADD_AI_FACTORY_MCP_2_APIM": ""}) == "false"
    for script in (ado["inputs"]["inlineScript"], gha["run"]):
        assert "45-aifactory-mcp-gateway/deploy.py\" apim-parameters --output" in script
        assert "esml-common/ai-gateway/apim/apim-mcp-server.bicep" in script
        assert '--parameters "@$' in script
        assert "deleteAll" not in script
        # The deployment target comes from the launcher's resolved APIM, not a second derivation in bash.
        assert '["apim_subscription_id"]' in script and '["apim_resource_group"]' in script
        assert ":-$dev_test_prod_sub_id" not in script
    assert ado["env"] == {name: f"$({name})" for name in launcher_tuple("APIM_INPUTS")}
    assert launcher_tuple("APIM_INPUTS") <= set(gha["env"])


def test_launcher_and_engine_are_importable_without_azure_access():
    spec = importlib.util.spec_from_file_location("mcp_gateway_launcher_contract", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.INPUTS and callable(module.run)
    assert not [item for item in objects(load_pipeline(JOB)) if "deleteAll" in str(item.get("inlineScript", ""))]
