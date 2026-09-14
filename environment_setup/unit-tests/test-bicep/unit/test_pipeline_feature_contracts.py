"""Parsed, offline configuration -> orchestrator -> deployment flag contracts."""
from __future__ import annotations

import copy
import importlib.util
import re
from functools import lru_cache

import pytest

from base.config import REPO_ROOT, env_defaults, yaml_defaults
from domain.pipeline_contracts import (
    ADO_COMMON, ADO_GATEWAY, ADO_PROJECT, ADO_SERVICES, COMMON_FLAGS,
    COMMON_MODULE_FLAGS, CONFIG_ONLY_EXCEPTIONS, DEFAULT_EXCEPTIONS, FEATURES,
    GATEWAY_FLAGS, GHA_COMMON, GHA_GATEWAY, GHA_PHASE, GHA_PROJECT, MODULE_FLAGS,
    PARAMETER_ALIASES,
    deployments, evaluate, forwarding_errors, inventory_errors, load_pipeline,
    objects,
)


@lru_cache(maxsize=None)
def document(path):
    return load_pipeline(path)


def step_named(pipeline, name):
    matches = [item for item in objects(pipeline)
               if item.get("name", item.get("displayName")) == name]
    assert len(matches) == 1, f"Expected one step {name}, found {len(matches)}"
    return matches[0]


def task_reference(value, step):
    alias = re.fullmatch(r"\$\{([A-Z_]+):-false\}", value)
    if alias:
        assert alias[1] in step.get("env", {}), f"Unbound task environment: {value}"
        return step["env"][alias[1]]
    return value


def flag_bindings(public):
    path = GHA_GATEWAY if public in GATEWAY_FLAGS else GHA_COMMON if public in COMMON_FLAGS else GHA_PHASE
    return [job["env"] for job in document(path)["jobs"].values() if "env" in job]


def assert_flag_mapping(public, value, bindings=None):
    runtime = FEATURES[public]
    for binding in flag_bindings(public) if bindings is None else bindings:
        assert runtime in binding, f"{public}: missing runtime mapping {runtime}"
        # Reverse every other switch so accidental cross-wiring cannot pass.
        context = {"vars." + name: ("false" if value == "true" else "true") for name in FEATURES}
        context["vars." + public] = value
        actual = evaluate(binding[runtime], context)
        assert actual == value, f"{public} -> {runtime}: {value!r} became {actual!r}"
        assert isinstance(actual, str), f"{runtime}: CLI flag must remain a boolean string"


def test_every_exposed_enable_flag_has_an_explicit_contract():
    assert not inventory_errors(env_defaults(), yaml_defaults())
    assert all(reason.strip() for reason in CONFIG_ONLY_EXCEPTIONS.values())
    assert all(reason.strip() for _, _, reason in DEFAULT_EXCEPTIONS.values())
    for public in CONFIG_ONLY_EXCEPTIONS:
        assert env_defaults()[public] == "false"
        assert yaml_defaults()[FEATURES[public]] == "false"
        for path in (GHA_COMMON, GHA_PHASE):
            assert all(FEATURES[public] not in job.get("env", {})
                       for job in document(path)["jobs"].values()), f"{public}: remove stale no-binding exception"


@pytest.mark.parametrize("public", sorted(set(FEATURES) - set(CONFIG_ONLY_EXCEPTIONS)))
@pytest.mark.parametrize("value", ["false", "true"])
def test_github_string_flags_map_without_truthiness_or_cross_wiring(public, value):
    assert_flag_mapping(public, value)


@pytest.mark.parametrize("platform,path,required", [
    ("gha", GHA_PHASE, MODULE_FLAGS), ("ado", ADO_SERVICES, MODULE_FLAGS),
    ("gha", GHA_COMMON, COMMON_MODULE_FLAGS), ("ado", ADO_COMMON, COMMON_MODULE_FLAGS),
])
def test_every_service_and_dependency_parameter_is_forwarded(platform, path, required):
    assert not forwarding_errors(document(path), platform, required)


@pytest.mark.parametrize("value", ["false", "true"])
def test_common_job_bindings_include_shared_security_and_network_flags(value):
    public_by_runtime = {runtime: public for public, runtime in FEATURES.items()}
    runtime_flags = set(" ".join(COMMON_MODULE_FLAGS.values()).split())
    for job in document(GHA_COMMON)["jobs"].values():
        for runtime in runtime_flags:
            assert_flag_mapping(public_by_runtime[runtime], value, [job["env"]])


@pytest.mark.parametrize("platform,path", [("gha", GHA_PHASE), ("ado", ADO_SERVICES)])
def test_secondary_debug_rbac_and_dashboard_references_do_not_cross_wire_features(platform, path):
    for deployment in deployments(document(path)):
        for parameter, actual in deployment.parameters.items():
            normalized = parameter.removeprefix("DEBUG_")
            runtime = PARAMETER_ALIASES.get(normalized, normalized)
            if runtime not in FEATURES.values():
                continue
            if deployment.module in ("08-rbac-security.bicep", "08b-rbac-common-rg.bicep") and parameter == "enableAzureMachineLearning":
                # RBAC intentionally requires both the enable flag and resource existence.
                assert actual == "$AML_RBAC"
                continue
            actual = task_reference(actual, deployment.step)
            expected = f"$({runtime})" if platform == "ado" else "${{ env." + runtime + " }}"
            assert actual == expected, f"{platform}/{deployment.name}/{parameter}: {actual!r} != {expected!r}"


@pytest.mark.parametrize("platform,path", [("gha", GHA_PHASE), ("ado", ADO_SERVICES)])
@pytest.mark.parametrize("enabled,exists", [("false", "false"), ("false", "true"), ("true", "false"), ("true", "true")])
@pytest.mark.parametrize("step_name", ["100-rbac-security", "101-rbac-common-rg"])
def test_aml_rbac_derived_flag_requires_enabled_and_existing_resource(platform, path, enabled, exists, step_name):
    step = step_named(document(path), step_name)
    script = step["run"] if platform == "gha" else step["inputs"]["inlineScript"]
    match = re.search(
        r'(?m)^\s*AML_RBAC="([^"]+)"\s*\n\s*if \[ "([^"]+)" = "([^"]+)" \] && '
        r'\[ "([^"]+)" = "([^"]+)" \]; then AML_RBAC="([^"]+)"; fi\s*$',
        script,
    )
    assert match, "Derived RBAC expression changed; review the actual dependency gate"
    flag = "$(enableAzureMachineLearning)" if platform == "ado" else "${{ env.enableAzureMachineLearning }}"
    resource = "$(amlExists)" if platform == "ado" else "${{ env.amlExists }}"
    assert match[1] == "false" and match[3] == match[5] == match[6] == "true"
    assert task_reference(match[2], step) == flag
    assert task_reference(match[4], step) == resource
    sources = {match[2]: enabled, match[4]: exists}
    derived = match[6] if sources[match[2]] == match[3] and sources[match[4]] == match[5] else match[1]
    assert derived == ("true" if enabled == "true" and exists == "true" else "false")


@pytest.mark.parametrize("platform,path", [("gha", GHA_PHASE), ("ado", ADO_SERVICES)])
def test_bing_debug_parameter_uses_the_public_bing_switch(platform, path):
    required = {"01-foundation.bicep": "DEBUG_enableBingSearch"}
    deployment = next(item for item in deployments(document(path)) if item.module in required)
    expected = "$(enableBing)" if platform == "ado" else "${{ env.enableBing }}"
    assert deployment.parameters["DEBUG_enableBingSearch"] == expected


@lru_cache(maxsize=1)
def override_module():
    path = REPO_ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    spec = importlib.util.spec_from_file_location("pipeline_contract_config_overrides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("environment", ["dev", "stage", "prod"])
@pytest.mark.parametrize("value", [True, False, "true", "false"])
@pytest.mark.parametrize("platform", ["github", "azure-devops"])
def test_real_json_exporter_preserves_all_flag_overrides(environment, value, platform, monkeypatch, capsys):
    exporter = override_module()
    expected = str(value).lower()
    opposite = "false" if expected == "true" else "true"
    keys = set(FEATURES.values())
    selected = {key: value for key in keys}
    other = {key: opposite for key in keys}
    payload = {
        "dev": selected if environment == "dev" else other,
        "stage_prod": other if environment == "dev" else selected,
    }
    values, section = exporter.selected_values(payload, environment)
    assert section == ("dev" if environment == "dev" else "stage_prod")
    assert values == dict.fromkeys(keys, expected)
    captured = {}
    monkeypatch.setattr(exporter, "write_github_environment", captured.__setitem__)
    count, skipped = exporter.apply(values, platform, str(GHA_PHASE))
    assert count == len(keys)
    assert not skipped
    if platform == "github":
        assert captured == values
    else:
        lines = capsys.readouterr().out.splitlines()
        assert set(lines) == {f"##vso[task.setvariable variable={key}]{expected}" for key in keys}


@pytest.mark.parametrize("value", [True, False, "true", "false"])
def test_real_github_json_alias_export_reaches_runtime_flags(value, monkeypatch):
    exporter = override_module()
    public_flags = set(FEATURES) - set(CONFIG_ONLY_EXCEPTIONS) - COMMON_FLAGS - GATEWAY_FLAGS
    values, _ = exporter.selected_values({"dev": dict.fromkeys(public_flags, value)}, "dev")
    captured = {}
    monkeypatch.setattr(exporter, "write_github_environment", captured.__setitem__)
    exporter.apply(values, "github", str(GHA_PHASE))
    for public in public_flags:
        assert captured[FEATURES[public]] == str(value).lower()


def ado_context(phase="infra", **values):
    runtime = dict(yaml_defaults())
    runtime.update(values)
    result = {"variables." + key: value for key, value in runtime.items()}
    result["parameters.phase"] = phase
    return result


def gha_context(phase="infra", **values):
    runtime = {target: env_defaults()[public] for public, target in FEATURES.items()}
    runtime.update({
        "deleteAllServicesForProject": "false", "deleteAllForProject": "false",
        "debug_disable_69_aifoundry_2025": "false", "aiFoundryV2Exists": "false",
    })
    runtime.update(values)
    result = {"env." + key: value for key, value in runtime.items()}
    result["inputs.phase"] = phase
    return result


@pytest.mark.parametrize("public", sorted(GATEWAY_FLAGS))
@pytest.mark.parametrize("value", ["false", "true"])
def test_gateway_steps_compare_boolean_strings_not_truthiness(public, value):
    gha = next(item for item in deployments(document(GHA_GATEWAY))
               if public in item.step.get("if", ""))
    ado = next(item for item in deployments(document(ADO_GATEWAY))
               if public in item.step.get("condition", ""))
    assert bool(evaluate(gha.step["if"], {"env." + public: value})) == (value == "true")
    assert bool(evaluate(ado.step["condition"], {"variables." + public: value})) == (value == "true")


@pytest.mark.parametrize("foundry,caphost,debug,expected", [
    ("false", "false", "false", True),
    ("true", "true", "true", True),
    ("false", "true", "true", False),
    ("true", "false", "true", False),
])
@pytest.mark.parametrize("module,debug_flag", [
    ("03-cognitive-services.bicep", "debug_disable_63_cognitive_services"),
    ("04-databases.bicep", "debug_disable_64_databases"),
])
def test_ado_foundry_caphost_requires_search_and_cosmos_even_with_debug_skip(module, debug_flag, foundry, caphost, debug, expected):
    deployment = next(item for item in deployments(document(ADO_SERVICES)) if item.module == module)
    context = ado_context(enableAIFoundry=foundry, enableAFoundryCaphost=caphost,
                          **{debug_flag: debug, "deleteAllServicesForProject": "false"})
    assert bool(evaluate(deployment.step["condition"], context)) == expected
    context["parameters.phase"] = "foundry"
    assert not evaluate(deployment.step["condition"], context)
    context["parameters.phase"] = "infra"
    context["variables.deleteAllServicesForProject"] = "true"
    assert not evaluate(deployment.step["condition"], context)


@pytest.mark.parametrize("platform,path", [("gha", GHA_PHASE), ("ado", ADO_SERVICES)])
@pytest.mark.parametrize("enabled,phase,deleted", [
    ("false", "foundry", "false"), ("true", "infra", "false"),
    ("true", "foundry", "false"), ("true", "foundry", "true"),
])
def test_foundry_account_deployments_obey_enable_phase_and_delete_gates(platform, path, enabled, phase, deleted):
    foundry = [item for item in deployments(document(path)) if item.module == "09-ai-foundry-2025-v4.bicep"]
    assert len(foundry) == 2, "Both create and update paths must be covered"
    context_fn = gha_context if platform == "gha" else ado_context
    context = context_fn(phase, enableAIFoundry=enabled, deleteAllServicesForProject=deleted,
                         aiFoundryV2Exists="false", debug_disable_69_aifoundry_2025="false")
    for deployment in foundry:
        condition = deployment.step["if" if platform == "gha" else "condition"]
        assert bool(evaluate(condition, context)) == (enabled == "true" and phase == "foundry" and deleted == "false")


@pytest.mark.parametrize("target,internal", [("dev", "dev"), ("stage", "test"), ("prod", "prod")])
def test_github_project_only_orchestrator_passes_exact_target_and_phases(target, internal):
    pipeline = document(GHA_PROJECT)
    dispatch = pipeline["on"]["workflow_dispatch"]["inputs"]
    assert dispatch["environment"]["options"] == ["dev", "stage", "prod"]
    phase_job = document(GHA_PHASE)["jobs"]["deploy-project"]
    assert phase_job["environment"] == "${{ inputs.environment }}"
    context = {"inputs.environment": target, "inputs.deployment_id": "offline-reviewed-id",
               "vars.AZURE_ENV_NAME": "wrong-fallback"}
    assert evaluate(phase_job["env"]["dev_test_prod"], context) == internal
    calls = {name: job for name, job in pipeline["jobs"].items() if "uses" in job}
    assert set(calls) == {"deploy_infrastructure", "deploy_foundry"}
    for name, job in calls.items():
        assert job["uses"] == "./.github/workflows/infra-project-phase.yml"
        assert evaluate(job["with"]["environment"], context) == target
        assert job["with"]["phase"] == ("infra" if name == "deploy_infrastructure" else "foundry")
        assert job["with"]["config_file"] == "${{ inputs.config_file }}"
        assert job["with"]["config_secret"] == "${{ inputs.config_secret }}"
        assert job["secrets"] == "inherit"
    assert set(calls["deploy_foundry"]["needs"]) == {"configure", "deploy_infrastructure"}


@pytest.mark.parametrize("target,internal,prefix", [("dev", "dev", "dev"), ("stage", "test", "test"), ("prod", "prod", "prod")])
def test_ado_reviewed_project_only_route_uses_exact_target_and_service_connections(target, internal, prefix):
    pipeline = document(ADO_PROJECT)
    assert pipeline["variables"][0]["template"] == "../variables/variables.yaml"
    stages = pipeline["stages"]
    assert len(stages) == 3
    for stage in stages:
        context = {
            "parameters.deploymentTarget": target,
            "variables.Build.Reason": "Manual",
            "dependencies.Dev_GenAI_Project.result": "Skipped",
            "dependencies.Stage_GenAI_Project.result": "Skipped",
        }
        selected = stage["variables"]["dev_test_prod"] == internal
        assert bool(evaluate(stage["condition"], context)) == selected
        if not selected:
            continue
        assert stage["variables"]["dev_test_prod_sub_id"] == f"$({prefix}_sub_id)"
        assert stage["variables"]["network_env"] == f"$(network_env_{target})"
        service_calls = [item for item in objects(stage)
                         if item.get("template") == "./jobs/job-2-genai-services.yaml"]
        assert {item["parameters"]["phase"] for item in service_calls} == {"infra", "foundry"}
        for call in service_calls:
            assert call["parameters"]["serviceConnection"] == "${{ variables." + prefix + "_service_connection }}"
            assert call["parameters"]["serviceConnectionSeeding"] == "${{ variables." + prefix + "_seeding_kv_service_connection }}"
        assert not any("common" in item.get("template", "") for item in objects(stage))


@pytest.mark.parametrize("networking,byo,network_result,expected", [
    ("true", "false", "Succeeded", True),
    ("false", "false", "Skipped", True),
    ("true", "true", "Skipped", True),
    ("true", "false", "Failed", False),
])
def test_ado_project_services_can_follow_skipped_networking(networking, byo, network_result, expected):
    for stage in document(ADO_PROJECT)["stages"]:
        jobs = {job["deployment"]: job for job in stage["jobs"]}
        context = ado_context(runNetworkingVar=networking, BYO_subnets=byo,
                              deleteAllServicesForProject="false", deleteAllForProject="false")
        context["dependencies.ESGenAI_Networking.result"] = network_result
        assert bool(evaluate(jobs["ESGenAI_Networking"]["condition"], context)) == (networking == "true" and byo == "false")
        assert bool(evaluate(jobs["ESGenAI_Services"]["condition"], context)) == expected


@pytest.mark.parametrize("networking,byo", [("true", "false"), ("false", "false"), ("true", "true")])
@pytest.mark.parametrize("phase", ["infra", "foundry"])
def test_github_project_only_services_are_not_gated_by_optional_networking(networking, byo, phase):
    context = gha_context(phase, runNetworkingVar=networking, BYO_subnets=byo)
    pipeline = document(GHA_PHASE)
    network = step_named(pipeline, "07_Deploy_Subnet_IfNotExists")
    assert bool(evaluate(network["if"], context)) == (phase == "infra" and networking == "true" and byo == "false")
    for deployment in deployments(pipeline):
        if deployment.module in MODULE_FLAGS and deployment.module != "09-ai-foundry-2025-v4.bicep":
            assert bool(evaluate(deployment.step["if"], context)) == (phase == "infra")


@pytest.mark.parametrize("enabled", ["false", "true"])
@pytest.mark.parametrize("phase", ["infra", "foundry"])
def test_disabled_service_deletion_requires_explicit_opt_in_in_both_pipelines(enabled, phase):
    gha = step_named(document(GHA_PHASE), "18_Delete_Service_If_Not_Enabled_And_Exists")
    ado = step_named(document(ADO_SERVICES), "06b_Delete_Service_If_Not_Enabled_And_Exists")
    assert ado["inputs"]["scriptPath"].endswith("/delete-services-if-disabled.sh")
    assert bool(evaluate(gha["if"], gha_context(phase, enableDeleteForDisabledResources=enabled))) == (enabled == "true" and phase == "infra")
    assert bool(evaluate(ado["condition"], ado_context(phase, enableDeleteForDisabledResources=enabled))) == (enabled == "true" and phase == "infra")


@pytest.mark.parametrize("fault", ["drop", "wrong_flag", "wrong_parameter"])
@pytest.mark.parametrize("platform,path", [("gha", GHA_PHASE), ("ado", ADO_SERVICES)])
def test_fault_injection_rejects_broken_deployment_forwarding(fault, platform, path):
    pipeline = copy.deepcopy(document(path))
    step = step_named(pipeline, "64-databases")
    container, key = (step, "run") if platform == "gha" else (step["inputs"], "inlineScript")
    source = "${{ env.enableCosmosDB }}" if platform == "gha" else "$(enableCosmosDB)"
    old = '--parameters enableCosmosDB="' + source + '"'
    assert old in container[key]
    replacement = {
        "drop": "",
        "wrong_flag": old.replace("env.enableCosmosDB", "env.enableRedisCache").replace("$(enableCosmosDB)", "$(enableRedisCache)"),
        "wrong_parameter": old.replace("enableCosmosDB=", "enableCosmosDBTypo="),
    }[fault]
    container[key] = container[key].replace(old, replacement)
    assert any("enableCosmosDB" in error for error in forwarding_errors(pipeline, platform))


@pytest.mark.parametrize("fault", ["drop", "wrong_flag", "boolean_truthiness"])
def test_fault_injection_rejects_broken_github_environment_mapping(fault):
    binding = copy.deepcopy(document(GHA_PHASE)["jobs"]["deploy-project"]["env"])
    if fault == "drop":
        del binding["enableCosmosDB"]
    elif fault == "wrong_flag":
        binding["enableCosmosDB"] = "${{ vars.ENABLE_REDIS_CACHE || 'true' }}"
    else:
        binding["enableCosmosDB"] = "${{ vars.ENABLE_COSMOS_DB && 'true' || 'false' }}"
    with pytest.raises(AssertionError):
        assert_flag_mapping("ENABLE_COSMOS_DB", "false", [binding])


def test_fault_injection_rejects_new_unreviewed_flags_on_either_platform():
    env, ado = dict(env_defaults()), dict(yaml_defaults())
    env["ENABLE_UNREVIEWED_SERVICE"] = "false"
    assert any("ENABLE_UNREVIEWED_SERVICE" in error for error in inventory_errors(env, yaml_defaults()))
    ado["enableUnreviewedService"] = "false"
    assert any("enableUnreviewedService" in error for error in inventory_errors(env_defaults(), ado))


@pytest.mark.parametrize("expression", ["contains(vars.FLAG, 'true')", "vars.FLAG ? 'true' : 'false'", "vars.MISSING"])
def test_expression_interpreter_fails_closed_on_unsupported_or_missing_input(expression):
    with pytest.raises(AssertionError):
        evaluate(expression, {"vars.FLAG": "false"})
