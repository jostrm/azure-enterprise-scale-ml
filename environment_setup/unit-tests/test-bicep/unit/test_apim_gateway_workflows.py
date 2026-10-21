"""Offline workflow contracts; Azure authentication and network calls are forbidden.

The reviewed APIM runner is opt-in (apimGatewayManagedProvisioning / APIM_GATEWAY_MANAGED_PROVISIONING,
default false). While the switch is off, both pipelines keep main's classic APIM, MCP and Kong behaviour.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

from base.config import REPO_ROOT, env_defaults, yaml_defaults
from domain.pipeline_contracts import ADO_GATEWAY, GHA_GATEWAY, deployments, evaluate, load_pipeline, objects


ADO_PIPELINE = ADO_GATEWAY.parent.parent / "infra-ai-gateway.yaml"
VARIABLES_JSON = REPO_ROOT / "environment_setup" / "aifactory" / "variables.json"
PATHS = {"ado": ADO_GATEWAY, "gha": GHA_GATEWAY}
PLAN = "Validate target and plan APIM offline"
ONLINE = "Preview or apply reviewed APIM plan"
LOCATE = "Locate APIM review artifacts even on failure"
PUBLISH = "Publish APIM plan and sanitized phase receipts"
CLASSIC = "Deploy APIM Azure OpenAI pool"
MCP = "Expose the AI Factory MCP on APIM"
KONG = "Deploy Kong edge gateway"
SWITCH = {"ado": "apimGatewayManagedProvisioning", "gha": "APIM_GATEWAY_MANAGED_PROVISIONING"}
CONFIG_FILE = {"ado": "apimGatewayConfigFile", "gha": "APIM_GATEWAY_CONFIG_FILE"}
CONFIGURED = {"ado": "variables.apimGatewayManagedConfigured", "gha": "steps.managed_apim.outputs.configured"}
RELATIVE_RUNNER = Path("environment_setup") / "aifactory" / "bicep" / "scripts" / "apim-gateway-deployment.py"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUBSCRIPTIONS = {
    "dev": "11111111-1111-1111-1111-111111111111",
    "stage": "22222222-2222-2222-2222-222222222222",
    "prod": "33333333-3333-3333-3333-333333333333",
}
LEGACY_BINDINGS = {
    "SUBSCRIPTION_ID": "SubscriptionId", "RESOURCE_GROUP": "ResourceGroup",
    "SERVICE_NAME": "ServiceName", "SKU": "Sku", "SKU_CAPACITY": "SkuCapacity",
    "API_ID": "ApiId", "API_PATH": "ApiPath", "BACKEND_POOL_NAME": "BackendPoolName",
    "AGGREGATE_TPM": "AggregateTpm", "CALLER_TPM": "CallerTpm", "RETRY_COUNT": "RetryCount",
    "ASSIGN_OPENAI_USER_ROLE": "AssignOpenAIUserRole",
    "MANAGED_IDENTITY_PRINCIPAL_ID": "ManagedIdentityPrincipalId", "BACKENDS_JSON": "BackendsJson",
}
RUNTIME_PARAMETERS = ("deploymentTarget", "action", "approvedPlan", "approvedPreview", "approveInitialPublicBootstrap")


def steps(platform):
    pipeline = load_pipeline(PATHS[platform])
    return pipeline["steps"] if platform == "ado" else pipeline["jobs"]["deploy"]["steps"]


def step(platform, name):
    matches = [item for item in objects(load_pipeline(PATHS[platform]))
               if item.get("name", item.get("displayName")) == name]
    assert len(matches) == 1
    return matches[0]


def script(item):
    return item.get("run", item.get("inputs", {}).get("script", item.get("inputs", {}).get("inlineScript", "")))


def runs(platform, name, action="plan", apim="false", managed="false", kong="false", mcp="false",
         configured="", success=True):
    """Evaluate a step gate; GitHub adds success() when the expression has no status function."""
    if platform == "gha":
        context = {"env.ENABLE_APIM": apim, "env.APIM_GATEWAY_MANAGED_PROVISIONING": managed,
                   "env.ENABLE_KONG": kong, "env.ADD_AI_FACTORY_MCP_2_APIM": mcp, "inputs.action": action}
    else:
        context = {"variables.ENABLE_APIM": apim, "variables.apimGatewayManagedProvisioning": managed,
                   "variables.ENABLE_KONG": kong, "variables.addAIFactoryMCP2APIM": mcp, "parameters.action": action,
                   "variables.apimGatewayArtifactsReady": "true"}
    context[CONFIGURED[platform]] = configured
    context["success"] = success
    item = step(platform, name)
    gate = item.get("if" if platform == "gha" else "condition")
    if gate is None:
        return success
    result = bool(evaluate(gate, context))
    if platform == "gha" and not re.search(r"\b(?:always|success|failure|cancelled)\(", gate):
        result = result and success
    return result


@pytest.fixture
def local_area():
    area = REPO_ROOT / ".apim-workflow-unit" / uuid.uuid4().hex
    area.mkdir(parents=True)
    try:
        yield area
    finally:
        shutil.rmtree(area)
        try:
            area.parent.rmdir()
        except OSError:
            pass


@pytest.fixture
def runner_module(monkeypatch):
    monkeypatch.syspath_prepend(str((REPO_ROOT / RELATIVE_RUNNER).parent))
    spec = importlib.util.spec_from_file_location("workflow_apim_runner", REPO_ROOT / RELATIVE_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def consumer_config(target="dev"):
    sub = SUBSCRIPTIONS[target]
    return {
        "schemaVersion": 1, "environment": target, "tenantId": TENANT, "subscriptionId": sub,
        "resourceGroup": "gateway-rg", "serviceName": "apim-gateway", "location": "swedencentral",
        "api": {
            "apiId": "chat-api", "apiPath": "openai", "backendPoolName": "chat-pool",
            "aggregateTokensPerMinute": 100000,
            "azureOpenAIBackends": [{
                "name": "aoai-one", "endpoint": "https://aoai-one.openai.azure.com",
                "resourceId": f"/subscriptions/{sub}/resourceGroups/ai-rg/providers/Microsoft.CognitiveServices/accounts/aoai-one",
                "weight": 1,
            }],
        },
    }


def prepare_consumer(area, monkeypatch, target="dev", layout="submodule", action="plan", deployment_target=None):
    root = area / "consumer"
    source = root / "azure-enterprise-scale-ml" if layout == "submodule" else root
    runner = source / RELATIVE_RUNNER
    runner.parent.mkdir(parents=True)
    runner.write_text("# Test placeholder; never executed.\n", encoding="utf-8")
    values = {
        "GATEWAY_REPOSITORY_ROOT": str(root), "GATEWAY_OUTPUT_DIR": str(area / "artifacts"),
        "GATEWAY_ENVIRONMENT": target, "GATEWAY_DEPLOYMENT_TARGET": deployment_target or target,
        "GATEWAY_ACTION": action, "GATEWAY_CONFIG_FILE": "",
        "GATEWAY_APPROVED_PLAN": "", "GATEWAY_APPROVE_INITIAL_PUBLIC_BOOTSTRAP": "false",
        "AZURE_TENANT_ID": TENANT, "AZURE_SUBSCRIPTION_ID": SUBSCRIPTIONS[target],
        "AZURE_LOCATION": "swedencentral", "ENABLE_APIM": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for key in LEGACY_BINDINGS:
        monkeypatch.delenv("APIM_GATEWAY_" + key, raising=False)
    return root, runner


def run_preflight(platform):
    body = script(step(platform, PLAN))
    match = re.fullmatch(r"set -euo pipefail\npython3 - <<'PY'\n(.*)\nPY\n?", body, re.S)
    assert match, "Review changes to the offline execution boundary"
    with pytest.raises(SystemExit) as result:
        exec(compile(match[1], str(PATHS[platform]), "exec"), {})
    return result.value.code


# --- Opt-in switch and defaults -------------------------------------------------------------

def test_managed_provisioning_switch_and_config_file_default_off_in_every_template():
    json_values = json.loads(VARIABLES_JSON.read_text(encoding="utf-8"))["dev"]
    for platform, values in (("ado", yaml_defaults()), ("gha", env_defaults())):
        assert values[SWITCH[platform]] == "false"
        assert values[CONFIG_FILE[platform]] == ""
    assert json_values[SWITCH["ado"]] == "false"
    assert json_values[CONFIG_FILE["ado"]] == ""
    env = load_pipeline(GHA_GATEWAY)["jobs"]["deploy"]["env"]
    assert evaluate(env["APIM_GATEWAY_MANAGED_PROVISIONING"], {"vars.APIM_GATEWAY_MANAGED_PROVISIONING": ""}) == "false"
    assert evaluate(env["APIM_GATEWAY_MANAGED_PROVISIONING"], {"vars.APIM_GATEWAY_MANAGED_PROVISIONING": "true"}) == "true"
    assert evaluate(env["APIM_GATEWAY_CONFIG_FILE"], {"vars.APIM_GATEWAY_CONFIG_FILE": ""}) == ""


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("action", ["plan", "what-if", "apply"])
@pytest.mark.parametrize("apim,kong,mcp,success", [
    (*flags, success) for flags in itertools.product(["false", "true"], repeat=3) for success in (True, False)])
def test_switch_off_keeps_main_behaviour_for_every_action(platform, action, apim, kong, mcp, success):
    values = dict(action=action, apim=apim, managed="false", kong=kong, mcp=mcp, success=success)
    # Main: the pool step and ADO Kong carry no succeeded(); the MCP step needs success; GitHub adds it implicitly.
    assert runs(platform, CLASSIC, **values) == (apim == "true" and (platform == "ado" or success))
    assert runs(platform, MCP, **values) == (mcp == "true" and success)
    assert runs(platform, KONG, **values) == (kong == "true" and (platform == "ado" or success))
    for name in (PLAN, ONLINE, PUBLISH) + ((LOCATE,) if platform == "ado" else ()):
        assert not runs(platform, name, **values)
    if platform == "gha":
        assert runs(platform, "Azure Login", **values) == success


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("action", ["plan", "what-if", "apply"])
@pytest.mark.parametrize("apim", ["false", "true"])
@pytest.mark.parametrize("configured", ["", "false", "true"])
@pytest.mark.parametrize("success", [True, False])
def test_managed_switch_routes_apim_through_the_reviewed_runner(platform, action, apim, configured, success):
    values = dict(action=action, apim=apim, managed="true", kong="true", mcp="true",
                  configured=configured, success=success)
    managed = apim == "true"
    # Dependent publications wait until the runner reports the managed APIM configured in this run.
    dependent = not managed or configured == "true"
    assert not runs(platform, CLASSIC, **values)
    assert runs(platform, PLAN, **values) == (managed and success)
    assert runs(platform, ONLINE, **values) == (managed and action != "plan" and success)
    assert runs(platform, PUBLISH, **values) == managed
    assert runs(platform, MCP, **values) == (dependent and success)
    assert runs(platform, KONG, **values) == (dependent and (platform == "ado" or success))
    if platform == "ado":
        assert runs(platform, LOCATE, **values) == managed
    else:
        assert runs(platform, "Azure Login", **values) == ((not managed or action != "plan") and success)


@pytest.mark.parametrize("platform", PATHS)
def test_step_order_keeps_the_mcp_right_after_the_classic_pool(platform):
    key = "displayName" if platform == "ado" else "name"
    names = [item.get(key) for item in steps(platform)]
    expected = [PLAN, ONLINE] + ([LOCATE] if platform == "ado" else []) + [PUBLISH, CLASSIC, MCP, KONG]
    if platform == "gha":
        expected = ["Checkout", PLAN, "Azure Login"] + expected[1:]
    assert names == expected
    if platform == "gha":
        assert step("gha", ONLINE)["id"] == "managed_apim"


# --- Inputs and stage selection -----------------------------------------------------------

def test_manual_inputs_default_to_offline_and_no_approvals():
    github = load_pipeline(GHA_GATEWAY)
    assert set(github["on"]) == {"workflow_dispatch"}
    gha = github["on"]["workflow_dispatch"]["inputs"]
    assert set(gha) == {"environment", "action", "approved_plan", "approved_preview",
                        "approve_initial_public_bootstrap"}
    assert gha["environment"]["options"] == ["dev", "stage", "prod"]
    assert gha["environment"]["default"] == "dev"
    assert gha["action"]["options"] == ["plan", "what-if", "apply"]
    assert gha["action"]["default"] == "plan"
    assert gha["approved_plan"]["default"] == gha["approved_preview"]["default"] == ""
    assert gha["approve_initial_public_bootstrap"]["type"] == "boolean"
    assert gha["approve_initial_public_bootstrap"]["default"] == "false"
    for name in ("action", "approved_plan", "approved_preview", "approve_initial_public_bootstrap"):
        assert "APIM_GATEWAY_MANAGED_PROVISIONING" in gha[name]["description"]
    for path in (ADO_PIPELINE, ADO_GATEWAY):
        ado = {p["name"]: p for p in load_pipeline(path)["parameters"]}
        assert ado["deploymentTarget"]["values"] == ["all", "dev", "stage", "prod"]
        assert ado["deploymentTarget"]["default"] == "all"
        assert ado["action"]["values"] == ["plan", "what-if", "apply"]
        assert ado["action"]["default"] == "plan"
        assert ado["approvedPlan"]["default"] == ado["approvedPreview"]["default"] == ""
        assert ado["approveInitialPublicBootstrap"]["type"] == "boolean"
        assert ado["approveInitialPublicBootstrap"]["default"] == "false"
        assert "runLegacyKong" not in ado and "configFile" not in ado
    job = {p["name"]: p for p in load_pipeline(ADO_GATEWAY)["parameters"]}
    assert "default" not in job["serviceConnection"]
    assert job["gatewayEnvironment"]["default"] == ""
    assert load_pipeline(ADO_PIPELINE)["trigger"] == "none"


STAGES = {"Dev": ("dev", "dev"), "Stage": ("stage", "test"), "Prod": ("prod", "prod")}


def stage_runs(stage, target, reason, stage_result):
    condition = stage.get("condition")
    if condition is None:
        return True  # First stage, default succeeded().
    return bool(evaluate(condition, {"parameters.deploymentTarget": target, "variables.Build.Reason": reason,
                                     "dependencies.Stage.result": stage_result}))


@pytest.mark.parametrize("reason", ["Manual", "IndividualCI"])
@pytest.mark.parametrize("stage_result", ["Succeeded", "Skipped", "Failed"])
def test_ado_default_target_keeps_main_promotion(reason, stage_result):
    pipeline = load_pipeline(ADO_PIPELINE)
    assert pipeline["variables"] == [{"template": "../variables/variables.yaml"}]
    stages = {stage["stage"]: stage for stage in pipeline["stages"]}
    assert list(stages) == ["Dev", "Stage", "Prod"]
    assert "dependsOn" not in stages["Dev"]
    assert stages["Stage"]["dependsOn"] == "Dev"
    assert stages["Prod"]["dependsOn"] == ["Dev", "Stage"]
    manual = reason == "Manual"
    assert stage_runs(stages["Dev"], "all", reason, stage_result)
    assert stage_runs(stages["Stage"], "all", reason, stage_result) == manual
    assert stage_runs(stages["Prod"], "all", reason, stage_result) == (manual and stage_result in ("Succeeded", "Skipped"))


@pytest.mark.parametrize("target", ["dev", "stage", "prod"])
@pytest.mark.parametrize("reason", ["Manual", "IndividualCI"])
@pytest.mark.parametrize("stage_result", ["Succeeded", "Skipped", "Failed"])
def test_ado_single_target_selects_exactly_one_stage(target, reason, stage_result):
    pipeline = load_pipeline(ADO_PIPELINE)
    selected = [stage["stage"] for stage in pipeline["stages"] if stage_runs(stage, target, reason, stage_result)]
    assert selected == [name for name, (environment, _) in STAGES.items() if environment == target]


@pytest.mark.parametrize("name", STAGES)
def test_ado_stages_forward_their_environment_and_the_runtime_parameters(name):
    environment, internal = STAGES[name]
    stage = next(stage for stage in load_pipeline(ADO_PIPELINE)["stages"] if stage["stage"] == name)
    prefix = {"dev": "dev", "test": "test", "prod": "prod"}[internal]
    assert stage["variables"] == {"dev_test_prod": internal, "dev_test_prod_sub_id": f"$({prefix}_sub_id)"}
    job = stage["jobs"][0]
    assert job["environment"] == name
    deploy = job["strategy"]["runOnce"]["deploy"]["steps"]
    assert deploy[0] == {"checkout": "self", "submodules": "true"}
    assert deploy[1]["template"] == "./jobs/job-2-ai-gateway.yaml"
    parameters = deploy[1]["parameters"]
    assert parameters["serviceConnection"] == "${{ variables." + prefix + "_service_connection }}"
    assert parameters["gatewayEnvironment"] == environment
    for parameter in RUNTIME_PARAMETERS:
        assert parameters[parameter] == "${{ parameters." + parameter + " }}"
    assert step("ado", ONLINE)["inputs"]["azureSubscription"] == "${{ parameters.serviceConnection }}"


def test_github_serializes_only_managed_runs_and_scopes_runner_context_to_steps():
    pipeline = load_pipeline(GHA_GATEWAY)
    assert pipeline["concurrency"] == {
        "group": "${{ vars.APIM_GATEWAY_MANAGED_PROVISIONING == 'true' && format('apim-{0}', inputs.environment) || github.run_id }}",
        "cancel-in-progress": "false",
    }
    job = pipeline["jobs"]["deploy"]
    assert job["environment"] == (
        "${{ fromJSON(vars.AIFACTORY_GITHUB_ENVIRONMENTS || "
        "'{\"dev\":\"dev\",\"stage\":\"stage\",\"prod\":\"prod\"}')[inputs.environment] }}"
    )
    # Managed-only context (tenant, inputs, runner paths) stays on the runner steps, not the shared job env.
    assert not {"AZURE_TENANT_ID", "GATEWAY_ACTION", "GATEWAY_ENVIRONMENT"} & set(job["env"])
    for name in (PLAN, ONLINE):
        env = step("gha", name)["env"]
        for target in SUBSCRIPTIONS:
            # Same secret as every other AI Factory workflow (03a uploads TENANT_ID as a secret).
            context = {"inputs.environment": target, "secrets.TENANT_ID": TENANT}
            assert evaluate(env["GATEWAY_ENVIRONMENT"], context) == target
            assert evaluate(env["GATEWAY_DEPLOYMENT_TARGET"], context) == target
            assert evaluate(env["AZURE_TENANT_ID"], context) == TENANT
        assert env["GATEWAY_REPOSITORY_ROOT"] == "${{ github.workspace }}"
        assert env["GATEWAY_ACTION"] == "${{ inputs.action }}"
        assert env["GATEWAY_CONFIG_FILE"] == "${{ env.APIM_GATEWAY_CONFIG_FILE }}"
        assert env["APIM_GATEWAY_TAGS_JSON"] == "${{ env.TAGS }}"
    online = step("gha", ONLINE)["env"]
    for name, value in {"APPROVED_PLAN": "approved_plan", "APPROVED_PREVIEW": "approved_preview",
                        "APPROVE_INITIAL_PUBLIC_BOOTSTRAP": "approve_initial_public_bootstrap"}.items():
        assert online["GATEWAY_" + name] == "${{ inputs." + value + " }}"
    gha_env = job["env"]
    for suffix in LEGACY_BINDINGS:
        key = "APIM_GATEWAY_" + suffix
        assert key in gha_env and "vars." + key in gha_env[key]
    assert step("gha", "Checkout")["uses"] == "actions/checkout@v4"
    assert step("gha", "Azure Login")["with"] == {"creds": "${{ secrets.AZURE_CREDENTIALS }}"}


def test_ado_legacy_variables_are_explicitly_exported_to_both_runner_tasks():
    for name in (PLAN, ONLINE):
        env = step("ado", name)["env"]
        for suffix, camel in LEGACY_BINDINGS.items():
            assert env["APIM_GATEWAY_" + suffix] == "$(apimGateway" + camel + ")"
        assert env["APIM_GATEWAY_TAGS_JSON"] == "$(tags)"
        assert env["AZURE_TENANT_ID"] == "$(tenantId)"
        assert env["AZURE_SUBSCRIPTION_ID"] == "$(dev_test_prod_sub_id)"
        assert env["AZURE_LOCATION"] == "$(admin_location)"
        assert env["ENABLE_APIM"] == "$(ENABLE_APIM)"
        assert env["GATEWAY_ENVIRONMENT"] == "${{ parameters.gatewayEnvironment }}"
        assert env["GATEWAY_DEPLOYMENT_TARGET"] == "${{ parameters.deploymentTarget }}"
        assert env["GATEWAY_ACTION"] == "${{ parameters.action }}"
        assert env["GATEWAY_CONFIG_FILE"] == "$(apimGatewayConfigFile)"
    env = step("ado", ONLINE)["env"]
    assert env["GATEWAY_APPROVED_PLAN"] == "${{ parameters.approvedPlan }}"
    assert env["GATEWAY_APPROVED_PREVIEW"] == "${{ parameters.approvedPreview }}"
    assert env["GATEWAY_APPROVE_INITIAL_PUBLIC_BOOTSTRAP"] == "${{ parameters.approveInitialPublicBootstrap }}"


# --- Runner boundary ----------------------------------------------------------------------

@pytest.mark.parametrize("platform", PATHS)
def test_runner_boundary_has_no_inline_input_evaluation_or_imperative_sku_patch(platform):
    for name in (PLAN, ONLINE):
        body = script(step(platform, name))
        assert "${{" not in body
        assert not re.search(r"\$\((?:apimGateway|tenantId|dev_test_prod|admin_)", body)
        assert "az " not in body and "--method patch" not in body
        assert "eval " not in body and "set -x" not in body and "printenv" not in body
    online = script(step(platform, ONLINE))
    assert 'summary="$(python3 "$runner" "${args[@]}")"' in online
    assert '--approved-plan "$GATEWAY_APPROVED_PLAN"' in online
    assert '--approved-preview "$GATEWAY_APPROVED_PREVIEW"' in online
    assert '--action "$GATEWAY_ACTION"' in online
    assert "args+=(--approve-initial-public-bootstrap)" in online
    if platform == "ado":
        assert step("ado", PLAN)["task"] == "Bash@3"
        assert step("ado", ONLINE)["task"] == "AzureCLI@2"
        assert step("ado", ONLINE)["inputs"]["visibleAzLogin"] == "false"


@pytest.mark.parametrize("platform", PATHS)
def test_classic_pool_step_still_deploys_main_bicep_with_mains_parameters(platform):
    classic = [item for item in deployments(load_pipeline(PATHS[platform])) if item.name == CLASSIC]
    assert len(classic) == 1
    assert classic[0].module == "main.bicep"
    assert set(classic[0].parameters) == {
        "apimServiceName", "apimResourceGroupName", "apimSubscriptionId", "apiId", "apiPath", "backendPoolName",
        "aggregateTokensPerMinute", "callerTokensPerMinute", "retryCount", "assignOpenAIUserRole",
        "apimManagedIdentityPrincipalId", "azureOpenAIBackends",
    }
    body = script(classic[0].step)
    assert "--method patch" in body, "main's classic SKU alignment stays in the classic path"
    assert "apim-gateway-deployment.py" not in body


def test_artifacts_are_runner_outputs_only_and_survive_failure():
    gha = load_pipeline(GHA_GATEWAY)["jobs"]["deploy"]
    assert all("runner." not in value for value in gha["env"].values()), "Runner context is step-scoped"
    out = step("gha", PLAN)["env"]["GATEWAY_OUTPUT_DIR"]
    assert out.startswith("${{ runner.temp }}/apim-gateway-")
    assert step("gha", ONLINE)["env"]["GATEWAY_OUTPUT_DIR"] == out
    publish = step("gha", PUBLISH)
    assert publish["uses"] == "actions/upload-artifact@v4"
    assert publish["with"]["path"] == out
    assert publish["with"]["if-no-files-found"] == "ignore"
    ado_out = "$(Build.ArtifactStagingDirectory)/apim-gateway-$(System.JobAttempt)"
    for name in (PLAN, ONLINE, LOCATE):
        assert step("ado", name)["env"]["GATEWAY_OUTPUT_DIR"] == ado_out
    publish = step("ado", PUBLISH)
    assert publish["task"] == "PublishPipelineArtifact@1"
    assert publish["inputs"]["targetPath"] == ado_out
    assert publish["inputs"]["artifact"] == "apim-gateway-${{ parameters.gatewayEnvironment }}-$(System.JobAttempt)"
    assert "apimGatewayArtifactsReady" in publish["condition"]
    locate = script(step("ado", LOCATE))
    assert ' -f "$GATEWAY_OUTPUT_DIR/plan.json"' in locate
    assert ' -f "$GATEWAY_OUTPUT_DIR/receipt.json"' in locate


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("layout", ["root", "submodule"])
@pytest.mark.parametrize("target", SUBSCRIPTIONS)
@pytest.mark.parametrize("action", ["plan", "what-if", "apply"])
def test_preflight_uses_exact_target_and_offline_argv(platform, layout, target, action, local_area, monkeypatch):
    root, runner = prepare_consumer(local_area, monkeypatch, target, layout, action)
    config = root / "config $(echo not-evaluated); approved.json"
    config.write_text(json.dumps(consumer_config(target)), encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG_FILE", config.name)
    invoke = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", invoke)
    assert run_preflight(platform) == 0
    invoke.assert_called_once_with(
        [sys.executable, str(runner), "--environment", target, "--action", "plan",
         "--output-dir", str(local_area / "artifacts"), "--config", str(config.resolve())], check=False)


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("action", ["plan", "what-if"])
def test_preflight_allows_offline_and_preview_runs_across_all_stages(platform, action, local_area, monkeypatch):
    prepare_consumer(local_area, monkeypatch, action=action, deployment_target="all")
    monkeypatch.setattr(subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0)))
    assert run_preflight(platform) == 0


@pytest.mark.parametrize("platform", PATHS)
def test_preflight_refuses_apply_across_all_stages(platform, local_area, monkeypatch):
    prepare_consumer(local_area, monkeypatch, action="apply", deployment_target="all")
    invoke = Mock(side_effect=AssertionError("Apply across all stages must not start the runner"))
    monkeypatch.setattr(subprocess, "run", invoke)
    assert run_preflight(platform) == "Managed APIM apply needs one deploymentTarget (dev, stage or prod), not all."
    invoke.assert_not_called()


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("value", ["", "test", "all"])
def test_preflight_requires_the_stage_environment(platform, value, local_area, monkeypatch):
    prepare_consumer(local_area, monkeypatch)
    monkeypatch.setenv("GATEWAY_ENVIRONMENT", value)
    invoke = Mock(side_effect=AssertionError("An unknown environment must not start the runner"))
    monkeypatch.setattr(subprocess, "run", invoke)
    assert run_preflight(platform) == "Invalid target environment."
    invoke.assert_not_called()


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("key", ["AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"])
@pytest.mark.parametrize("value", ["", "<todo>", "$(missingVariable)", "not-a-guid"])
def test_missing_expected_identity_fails_before_runner_or_cloud_reads(platform, key, value, local_area, monkeypatch):
    prepare_consumer(local_area, monkeypatch)
    monkeypatch.setenv(key, value)
    invoke = Mock(side_effect=AssertionError("Runner must not start before identity validation"))
    monkeypatch.setattr(subprocess, "run", invoke)
    assert run_preflight(platform) == "Exact pipeline tenant and subscription are required."
    invoke.assert_not_called()


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("path", ["../outside.json", "config/../../outside.json", "/outside.json",
                                 "config\\..\\outside.json", "missing.json", "line\nbreak.json", ".",
                                 "$(apimGatewayConfigFile)"])
def test_consumer_config_path_fails_closed(platform, path, local_area, monkeypatch):
    prepare_consumer(local_area, monkeypatch)
    monkeypatch.setenv("GATEWAY_CONFIG_FILE", path)
    invoke = Mock(side_effect=AssertionError("Invalid config path must not start runner"))
    monkeypatch.setattr(subprocess, "run", invoke)
    assert run_preflight(platform) != 0
    invoke.assert_not_called()


@pytest.mark.parametrize("platform", PATHS)
def test_resolved_symlink_must_stay_inside_consumer_repository(platform, local_area, monkeypatch):
    root, _ = prepare_consumer(local_area, monkeypatch)
    outside = local_area / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = root / "link.json"
    try:
        link.symlink_to(outside)
    except OSError:
        # Windows hosts without symlink privileges still exercise the post-resolution boundary.
        original = Path.resolve
        monkeypatch.setattr(Path, "resolve", lambda self, *a, **kw: outside if self == link else original(self, *a, **kw))
    monkeypatch.setenv("GATEWAY_CONFIG_FILE", "link.json")
    invoke = Mock(side_effect=AssertionError("Escaping symlinks must not start runner"))
    monkeypatch.setattr(subprocess, "run", invoke)
    assert run_preflight(platform) == "Config file must remain inside the consumer repository."
    invoke.assert_not_called()


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("mode", ["json", "legacy", "managed"])
@pytest.mark.parametrize("target", SUBSCRIPTIONS)
def test_offline_workflow_reaches_real_runner_and_writes_plan_receipt(platform, mode, target, local_area, monkeypatch, runner_module):
    root, _ = prepare_consumer(local_area, monkeypatch, target=target)
    config = consumer_config(target)
    if mode == "managed":
        network = f"/subscriptions/{SUBSCRIPTIONS[target]}/resourceGroups/network-rg/providers/Microsoft.Network"
        config.update(serviceMode="managed", publisherName="AI Factory", publisherEmail="owner@example.org",
                      ownershipId="gateway-" + target, network={
                          "integrationSubnetId": network + "/virtualNetworks/hub/subnets/apim",
                          "networkSecurityGroupId": network + "/networkSecurityGroups/apim-nsg",
                          "privateEndpointSubnetId": network + "/virtualNetworks/hub/subnets/endpoints",
                          "privateEndpointName": "pe-apim",
                      })
    if mode != "legacy":
        file = root / "apim.json"
        file.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setenv("GATEWAY_CONFIG_FILE", file.name)
    else:
        values = {
            "SUBSCRIPTION_ID": "", "RESOURCE_GROUP": config["resourceGroup"], "SERVICE_NAME": config["serviceName"],
            "SKU": "StandardV2", "SKU_CAPACITY": "1", "API_ID": "chat-api", "API_PATH": "openai",
            "BACKEND_POOL_NAME": "chat-pool", "AGGREGATE_TPM": "100000", "CALLER_TPM": "10000",
            "RETRY_COUNT": "2", "ASSIGN_OPENAI_USER_ROLE": "false", "MANAGED_IDENTITY_PRINCIPAL_ID": "",
            "BACKENDS_JSON": json.dumps(config["api"]["azureOpenAIBackends"]), "TAGS_JSON": "{}",
        }
        for key, value in values.items():
            monkeypatch.setenv("APIM_GATEWAY_" + key, value)
    no_azure = Mock()
    no_azure.read.side_effect = no_azure.invoke.side_effect = AssertionError("Azure is forbidden for offline plan")

    def offline_only(args, **kwargs):
        assert args[0] == sys.executable and kwargs == {"check": False}
        return SimpleNamespace(returncode=runner_module.main(args[2:], cli=no_azure, environ=dict(os.environ)))

    monkeypatch.setattr(subprocess, "run", offline_only)
    assert run_preflight(platform) == 0
    plan = json.loads((local_area / "artifacts" / "plan.json").read_text(encoding="utf-8"))
    receipt = json.loads((local_area / "artifacts" / "receipt.json").read_text(encoding="utf-8"))
    assert plan["target"]["environment"] == target
    assert plan["target"]["subscriptionId"] == SUBSCRIPTIONS[target]
    assert plan["target"]["tenantId"] == TENANT
    assert plan["config"]["serviceMode"] == ("managed" if mode == "managed" else "existing")
    assert plan["offline"] is True and plan["armPreviewExecuted"] is False
    assert receipt["status"] == "offline-plan"
    no_azure.read.assert_not_called()
    no_azure.invoke.assert_not_called()


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("mismatch", ["environment", "subscriptionId", "tenantId", "missing-api"])
def test_explicit_config_still_rejects_missing_fields_and_cross_target_before_azure(platform, mismatch, local_area, monkeypatch, runner_module):
    root, _ = prepare_consumer(local_area, monkeypatch, target="stage", action="apply")
    config = consumer_config("stage")
    if mismatch == "missing-api":
        del config["api"]
    else:
        config[mismatch] = {"environment": "dev", "subscriptionId": SUBSCRIPTIONS["dev"],
                            "tenantId": SUBSCRIPTIONS["prod"]}[mismatch]
    file = root / "apim.json"
    file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG_FILE", file.name)
    no_azure = Mock()
    no_azure.read.side_effect = no_azure.invoke.side_effect = AssertionError("Invalid targets must not reach Azure")
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: SimpleNamespace(
        returncode=runner_module.main(args[2:], cli=no_azure, environ=dict(os.environ))))
    assert run_preflight(platform) == 1
    assert not (local_area / "artifacts").exists()
    no_azure.read.assert_not_called()
    no_azure.invoke.assert_not_called()


@pytest.mark.parametrize("platform", PATHS)
@pytest.mark.parametrize("action,bootstrap,configured", [
    ("what-if", "false", "false"), ("what-if", "true", "false"),
    ("apply", "false", "true"), ("apply", "true", "false"), ("apply", "True", "true"),
])
def test_online_shell_preserves_argv_separates_bootstrap_approval_and_reports_configuration(
        platform, action, bootstrap, configured, local_area, monkeypatch):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe") if os.name == "nt" else shutil.which("bash")
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash is unavailable for the offline argv test")
    root, runner = prepare_consumer(local_area, monkeypatch, action=action)
    config = "reviewed $(echo injected); file.json"
    digest = "$(echo injected); ' --action plan"
    preview_digest = "$(echo preview-injected); ' --approve-initial-public-bootstrap"
    argv, output = local_area / "argv.bin", local_area / "github-output.txt"
    env = dict(os.environ, GATEWAY_REPOSITORY_ROOT=root.as_posix(), GATEWAY_CONFIG_FILE=config,
               GATEWAY_APPROVED_PLAN=digest, GATEWAY_APPROVED_PREVIEW=preview_digest,
               GATEWAY_APPROVE_INITIAL_PUBLIC_BOOTSTRAP=bootstrap, GITHUB_OUTPUT=output.as_posix(),
               ARGV_FILE=argv.as_posix(), CONFIGURED=configured)
    # The function replaces Python entirely: only shell argv serialization and the summary hand-off run.
    stub = ('python3() { if [[ "$1" == "-c" ]]; then shift; command python -c "$@"; return; fi; '
            'printf "%s\\0" "$@" > "$ARGV_FILE"; '
            'printf \'{"gatewayConfigured":%s,"status":"stub"}\\n\' "$CONFIGURED"; }\n')
    result = subprocess.run([str(bash), "--noprofile", "--norc", "-s"], input=stub + script(step(platform, ONLINE)),
                            text=True, capture_output=True, env=env, check=False)
    assert result.returncode == 0, result.stderr
    actual = argv.read_bytes().decode("utf-8").rstrip("\0").split("\0")
    expected = [runner.as_posix(), "--environment", "dev", "--action", action, "--output-dir",
                str(local_area / "artifacts"), "--config", root.as_posix() + "/" + config]
    if action == "apply":
        expected += ["--approved-plan", digest, "--approved-preview", preview_digest]
        if bootstrap.lower() == "true":
            expected += ["--approve-initial-public-bootstrap"]
    assert actual == expected
    assert '"status":"stub"' in result.stdout
    if platform == "ado":
        assert f"##vso[task.setvariable variable=apimGatewayManagedConfigured]{configured}" in result.stdout
    else:
        assert output.read_text(encoding="utf-8").splitlines() == [f"configured={configured}"]
