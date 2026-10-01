"""Offline execution of capacity attempts and their committed CI invocations."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap

import pytest
import yaml

from domain.pipeline_contracts import deployments, evaluate, load_pipeline, objects


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"
RUNNER = BICEP / "scripts" / "deploy-capacity-resource.py"
SETTINGS = BICEP / "copy_to_local_settings"
ADO = SETTINGS / "azure-devops" / "esml-yaml-pipelines"
ADO_JOB = ADO / "esml-infra-project" / "jobs" / "job-2-genai-services.yaml"
ADO_ATTEMPTS = ADO_JOB.with_name("job-capacity-resource.yaml")
GHA = SETTINGS / "github-actions" / "infra-project-phase.yml"
SERVICES = {
    "ai-search": {
        "sku": "skuAISearch", "array": "skuArrayAISearch",
        "retry": "aisearchRetryCapcityArray", "state": "AIF_AISEARCH_CAPACITY_NEXT",
        "template": "03b-ai-search.bicep", "flag": "enableAISearch",
        "debug": "debug_disable_63_cognitive_services",
        "selected": "standard", "order": ["standard", "basic", "standard2"],
        "array_value": "basic,standard,standard2", "public": "AISEARCH",
    },
    "postgresql": {
        "sku": "skuPostgreSQL", "array": "skuArrayPostgreSQL",
        "retry": "postgreSQLRetryCapacityArray", "state": "AIF_POSTGRESQL_CAPACITY_NEXT",
        "template": "04b-postgresql.bicep", "flag": "enablePostgreSQL",
        "debug": "debug_disable_64_databases",
        "selected": "Standard_B2s", "order": ["Standard_B2s", "Standard_B1ms", "Standard_B2ms"],
        "array_value": "Standard_B1ms,Standard_B2s,Standard_B2ms", "public": "POSTGRESQL",
    },
    "container-apps": {
        "sku": "skuContainerApps", "array": "skuArrayContainerApps",
        "retry": "containerAppsRetryCapacityArray", "state": "AIF_CONTAINERAPPS_CAPACITY_NEXT",
        "template": "05b-container-apps.bicep", "flag": "enableContainerApps",
        "debug": "debug_disable_65_compute_services",
        "selected": "D4", "order": ["D4", "Consumption", "D8"],
        "array_value": "Consumption,D4,D8", "public": "CONTAINER_APPS",
    },
}
TAGS = {"owner": "unit 'quoted' $HOME ;", "nested": {"region": ["one", "two"]}}
PRIVATE_VALUE = "offline-private-value-must-not-appear-in-argv-or-logs"


@pytest.fixture
def workspace():
    # Keep all generated files inside this worktree, including runner temp files.
    with tempfile.TemporaryDirectory(prefix=".capacity-tests-", dir=ROOT) as directory:
        yield Path(directory)


@pytest.fixture(scope="module")
def runner():
    name = "_capacity_deployment_test_runner"
    spec = importlib.util.spec_from_file_location(name, RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


def parameter_definitions(path):
    """Expose actual Bicep parameter names/types without pretending to compile ARM."""
    declarations = {}
    for match in re.finditer(
        r"^param\s+(\w+)\s+(string|bool|int|object|array)\b([^\n]*)",
        path.read_text(encoding="utf-8"), re.M,
    ):
        name, kind, tail = match.groups()
        declaration = {"type": kind}
        if tail.lstrip().startswith("="):
            declaration["defaultValue"] = None
        declarations[name] = declaration
    assert declarations and "env" in declarations
    return {"parameters": declarations}


def environment(service, target="dev"):
    spec = SERVICES[service]
    suffix = "Dev" if target == "dev" else "StageProd"
    return {
        "dev_test_prod": target, "dev_test_prod_sub_id": "unit-subscription",
        "admin_location": "swedencentral", "project_number_000": "001",
        "admin_locationSuffix": "sc", "admin_prjResourceSuffix": "p",
        "admin_commonResourceSuffix": "c", "admin_aifactorySuffixRG": "-unit",
        "admin_aifactoryPrefixRG": "unit-", "deployment_random_value": "abc123",
        "vnetNameBase": "unit-vnet", "genaiSubnetId": "unit-subnet",
        "vnetResourceGroup_resolved": "unit-network-rg",
        "vnetNameFull_resolved": "unit-vnet-full", "vnetResourceGroupBase": "unit-common",
        "admin_bicep_kv_fw": "unit-keyvault", "admin_bicep_kv_fw_rg": "unit-kv-rg",
        "admin_bicep_input_keyvault_subscription": "unit-kv-sub",
        "project_service_principal_OID_seeding_kv_name": PRIVATE_VALUE,
        "technical_admins_ad_object_id": "unit-object-id",
        "technical_admins_email": "unit@example.invalid", "tagsProject": json.dumps(TAGS),
        "project_IP_whitelist": "192.0.2.1/32", "use_ad_groups": "true",
        "enablePublicGenAIAccess": "false", "enablePublicAccessWithPerimeter": "false",
        "enableAIFoundry": "false", "enableAFoundryCaphost": "false",
        "deleteAllServicesForProject": "false",
        spec["flag"]: "true", spec["debug"]: "false",
        spec["sku"] + suffix: spec["selected"],
        spec["array"] + suffix: spec["array_value"], spec["retry"]: "true",
    }


def dynamic_parameters(path):
    document = {
        "parameters": {
            "genaiSubnetId": {"value": "unit-subnet"},
            "aksSubnetId": {"value": "unit-aks"},
            "acaSubnetId": {"value": "unit-aca"},
            "unrelatedNetworkParameter": {"value": PRIVATE_VALUE},
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8-sig")


def publications(provider, stdout, github_env):
    if provider == "ado":
        return dict(re.findall(r"##vso\[task.setvariable variable=(\w+)\]([^\r\n]*)", stdout))
    return dict(
        line.split("=", 1) for line in github_env.read_text(encoding="utf-8").splitlines()
    ) if github_env.exists() else {}


@pytest.fixture
def runtime(runner, workspace, monkeypatch, capsys):
    class Runtime:
        def __init__(self):
            self.calls, self.parameters, self.paths, self.sleeps = [], [], [], []
            self.env = environment("ai-search")
            self.github_env = workspace / "github-env"
            self.env["GITHUB_ENV"] = str(self.github_env)
            self.env = {key.upper(): value for key, value in self.env.items()}
            self.dynamic = workspace / "dynamic.json"
            dynamic_parameters(self.dynamic)
            self.outcome = (0, "", "")
            self.build_outcome = None
            monkeypatch.setattr(runner.os, "environ", self.env)
            monkeypatch.setattr(runner.shutil, "which", lambda name: "offline-az")
            monkeypatch.setattr(runner.time, "sleep", self.sleeps.append)
            monkeypatch.setattr(runner.tempfile, "tempdir", str(workspace))
            monkeypatch.setattr(runner.subprocess, "run", self.azure)

        def azure(self, command, **kwargs):
            assert kwargs == {"capture_output": True, "text": True, "check": False}
            self.calls.append(command)
            if command[1:3] == ["bicep", "build"]:
                if self.build_outcome:
                    return subprocess.CompletedProcess(command, *self.build_outcome)
                template = parameter_definitions(Path(command[command.index("--file") + 1]))
                return subprocess.CompletedProcess(command, 0, json.dumps(template), "")
            assert command[1:4] == ["deployment", "sub", "create"]
            parameter_arg = command[command.index("--parameters") + 1]
            assert parameter_arg.startswith("@") and command.count("--parameters") == 1
            path = Path(parameter_arg[1:])
            self.paths.append(path)
            self.parameters.append(json.loads(path.read_text(encoding="utf-8"))["parameters"])
            assert PRIVATE_VALUE not in " ".join(command)
            return subprocess.CompletedProcess(command, *self.outcome)

        def attempt(self, service="ai-search", provider="ado", attempt=1):
            args = argparse.Namespace(
                service=service, provider=provider, attempt=attempt,
                template_file=str(BICEP / "esml-genai-1" / SERVICES[service]["template"]),
                parameters_file=str(self.dynamic), subscription="unit-subscription",
                location="swedencentral", deployment_name="unit-deployment",
            )
            if self.github_env.exists():
                self.github_env.unlink()
            result = runner.run_attempt(args)
            captured = capsys.readouterr()
            values = publications(provider, captured.out, self.github_env)
            self.env.update({key.upper(): value for key, value in values.items()})
            assert PRIVATE_VALUE not in captured.out + captured.err
            assert all(not path.parent.exists() for path in self.paths)
            return result, values, captured

        def configure(self, service, target="dev"):
            self.env.clear()
            self.env.update({key.upper(): value for key, value in environment(service, target).items()})
            self.env["GITHUB_ENV"] = str(self.github_env)

    return Runtime()


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target", ["dev", "test", "prod"])
@pytest.mark.parametrize("succeed_at", [1, 2, 3])
def test_runner_selected_first_success_arms_only_next_attempt(runtime, service, provider, target, succeed_at):
    runtime.configure(service, target)
    spec = SERVICES[service]
    suffix = "Dev" if target == "dev" else "StageProd"
    for attempt in range(1, succeed_at + 1):
        runtime.outcome = (0, "", "") if attempt == succeed_at else (9, "", "SkuNotAvailable")
        status, values, _ = runtime.attempt(service, provider, attempt)
        assert status == 0
        assert values[spec["state"]] == ("0" if attempt == succeed_at else str(attempt + 1))
        assert runtime.parameters[-1][spec["sku"] + suffix]["value"] == spec["order"][attempt - 1]
        if attempt < succeed_at:
            assert set(values) == {spec["state"]}
        else:
            assert values[spec["sku"] + suffix] == spec["order"][attempt - 1]
            if service == "postgresql":
                assert values["skuTierPostgreSQL" + suffix] == "Burstable"
    assert len(runtime.parameters) == succeed_at
    assert runtime.sleeps == [240] * (succeed_at - 1)
    if succeed_at < 3:
        with pytest.raises(ValueError, match="not armed"):
            runtime.attempt(service, provider, succeed_at + 1)
        assert len(runtime.parameters) == succeed_at


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("provider", ["ado", "github"])
def test_runner_exhaustion_fails_without_a_fourth_attempt(runtime, service, provider):
    runtime.configure(service)
    runtime.outcome = (17, "AllocationFailed", "")
    for attempt in (1, 2, 3):
        status, values, _ = runtime.attempt(service, provider, attempt)
        assert status == (17 if attempt == 3 else 0)
        assert values == {SERVICES[service]["state"]: "failed" if attempt == 3 else str(attempt + 1)}
    assert len(runtime.parameters) == 3
    assert runtime.sleeps == [240, 240]


@pytest.mark.parametrize("error", ["AuthorizationFailed", "AuthorizationFailed\nSkuNotAvailable", "UnknownFailure"])
@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("service", SERVICES)
def test_terminal_errors_never_arm_or_sleep(runtime, service, provider, error):
    runtime.configure(service)
    runtime.outcome = (23, "SkuNotAvailable" if "SkuNotAvailable" in error else "", error)
    status, values, _ = runtime.attempt(service, provider)
    assert status == 23 and values == {SERVICES[service]["state"]: "failed"}
    assert len(runtime.parameters) == 1 and runtime.sleeps == []


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("provider", ["ado", "github"])
def test_arm_validation_wrapper_does_not_hide_capacity_retry(runtime, service, provider):
    runtime.configure(service)
    runtime.outcome = (9, "", "ERROR: " + json.dumps({
        "code": "InvalidTemplateDeployment", "message": "Validation failed.",
        "details": [{"code": "SkuNotAvailable", "message": "Requested SKU unavailable."}],
    }))
    for attempt in (1, 2, 3):
        status, values, _ = runtime.attempt(service, provider, attempt)
        assert status == (9 if attempt == 3 else 0)
        assert values[SERVICES[service]["state"]] == ("failed" if attempt == 3 else str(attempt + 1))
    assert runtime.sleeps == [240, 240]


@pytest.mark.parametrize("errors", [
    [{"code": "SkuNotAvailable"}, {"code": "UnknownFailure"}],
    [{"code": "SkuNotAvailable"}, {"code": "AuthorizationFailed"}],
    [{"code": "DeploymentFailed", "details": [{"code": "SkuNotAvailable"}, {"code": "UnknownFailure"}]}],
])
def test_mixed_structured_failures_are_terminal(runner, errors):
    assert not runner.is_capacity_failure(json.dumps(errors))
    assert not runner.is_capacity_failure("\n".join(json.dumps(error) for error in errors))


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("invalid", ["", ",", "a,,b", "a,a", "a,A", "a,b,c,d", "a,b", "a;echo,b"])
def test_invalid_candidate_arrays_make_no_azure_calls(runtime, service, invalid):
    runtime.configure(service)
    runtime.env[(SERVICES[service]["array"] + "Dev").upper()] = invalid
    with pytest.raises(ValueError, match="Capacity array|Selected SKU"):
        runtime.attempt(service)
    assert runtime.calls == [] and runtime.sleeps == [] and runtime.paths == []


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("length", [1, 2])
def test_shorter_arrays_stop_at_their_actual_length(runtime, service, length):
    runtime.configure(service)
    spec = SERVICES[service]
    runtime.env[(spec["array"] + "Dev").upper()] = ",".join(spec["order"][:length])
    runtime.outcome = (31, "", "InsufficientCapacity")
    for attempt in range(1, length + 1):
        status, values, _ = runtime.attempt(service, attempt=attempt)
        assert status == (31 if attempt == length else 0)
        assert values[spec["state"]] == ("failed" if attempt == length else str(attempt + 1))
    with pytest.raises(ValueError, match="exceeds"):
        runtime.attempt(service, attempt=length + 1)
    assert len(runtime.parameters) == length and runtime.sleeps == [240] * (length - 1)


@pytest.mark.parametrize("service", SERVICES)
def test_disabled_retry_ignores_array_and_makes_one_attempt(runtime, service):
    runtime.configure(service)
    spec = SERVICES[service]
    runtime.env[spec["retry"].upper()] = "false"
    runtime.env[(spec["array"] + "Dev").upper()] = "invalid,,four,values"
    runtime.outcome = (19, "", "SkuNotAvailable")
    status, values, _ = runtime.attempt(service)
    assert status == 19 and values == {spec["state"]: "failed"}
    assert len(runtime.parameters) == 1 and runtime.sleeps == []


SEARCH_ARRAY_DEFAULT = ["basic", "standard", "standard2"]
SEARCH_ARRAY_CUSTOM = ["standard3", "basic", "standard"]
SEARCH_ARRAY_OTHER = ["basic", "standard", "storage_optimized_l1"]
SEARCH_ARRAY_ALIASES = [
    pytest.param(SEARCH_ARRAY_DEFAULT, SEARCH_ARRAY_CUSTOM, SEARCH_ARRAY_CUSTOM, id="legacy-custom"),
    pytest.param(SEARCH_ARRAY_CUSTOM, SEARCH_ARRAY_DEFAULT, SEARCH_ARRAY_CUSTOM, id="primary-custom"),
    pytest.param(SEARCH_ARRAY_CUSTOM, SEARCH_ARRAY_CUSTOM, SEARCH_ARRAY_CUSTOM, id="equal-custom"),
    pytest.param(None, SEARCH_ARRAY_CUSTOM, SEARCH_ARRAY_CUSTOM, id="only-legacy"),
    pytest.param(SEARCH_ARRAY_CUSTOM, None, SEARCH_ARRAY_CUSTOM, id="only-primary"),
    pytest.param(SEARCH_ARRAY_CUSTOM, "", SEARCH_ARRAY_CUSTOM, id="empty-legacy-binding"),
    pytest.param(None, None, SEARCH_ARRAY_DEFAULT, id="missing-both"),
]


@pytest.mark.parametrize("primary,legacy,expected", SEARCH_ARRAY_ALIASES)
@pytest.mark.parametrize("format", ["csv", "json"])
@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target", ["dev", "test", "prod"])
def test_search_array_alias_candidates_reach_actual_runtime(
    runtime, primary, legacy, expected, format, provider, target,
):
    runtime.configure("ai-search", target)
    suffix = "Dev" if target == "dev" else "StageProd"
    primary_key = ("skuArrayAISearch" + suffix).upper()
    runtime.env.pop(primary_key)
    public_suffix = "DEV" if target == "dev" else "STAGE_PROD"
    legacy_key = (("skuAISearch" + suffix + "Array").upper() if provider == "ado"
                  else "SKU_AI_SEARCH_" + public_suffix + "_ARRAY")

    def serialize(values):
        if values == "":
            return ""
        return json.dumps(values) if format == "json" else ",".join(values)

    if primary is not None:
        runtime.env[primary_key] = serialize(primary)
    if legacy is not None:
        runtime.env[legacy_key] = serialize(legacy)
    ordered = ["standard"] + [value for value in expected if value != "standard"]
    runtime.outcome = (11, "", "SkuNotAvailable")
    for attempt in range(1, len(ordered) + 1):
        runtime.attempt(provider=provider, attempt=attempt)
    assert [params["skuAISearch" + suffix]["value"] for params in runtime.parameters] == ordered
    assert runtime.sleeps == [240] * (len(ordered) - 1)


@pytest.mark.parametrize("target", ["dev", "test", "prod"])
@pytest.mark.parametrize("provider", ["ado", "github"])
def test_search_array_alias_conflict_fails_before_any_azure(runtime, target, provider):
    runtime.configure("ai-search", target)
    suffix = "Dev" if target == "dev" else "StageProd"
    runtime.env[("skuArrayAISearch" + suffix).upper()] = json.dumps(SEARCH_ARRAY_CUSTOM)
    runtime.env[("skuAISearch" + suffix + "Array").upper()] = ",".join(SEARCH_ARRAY_OTHER)
    with pytest.raises(ValueError, match="Conflicting AI Search capacity arrays"):
        runtime.attempt(provider=provider)
    assert runtime.calls == [] and runtime.sleeps == []


@pytest.mark.parametrize("configured", [
    "", '["basic",', '["basic", 1]', '["basic", null]', '["basic", {}]',
    '{"sku":"basic"}', '"basic"', "1", "null", "true", "[]",
    '["basic","BASIC"]', '["basic","standard","standard2","standard3"]',
])
@pytest.mark.parametrize("spelling", ["skuArrayAISearchDev", "skuAISearchDevArray"])
def test_search_array_alias_malformed_values_fail_before_any_azure(runtime, configured, spelling):
    runtime.env[spelling.upper()] = configured
    if spelling == "skuAISearchDevArray" and configured == "":
        # Only the historical alias's empty pipeline binding means unset.
        assert runtime.attempt()[0] == 0
        return
    with pytest.raises(ValueError, match="Capacity array"):
        runtime.attempt()
    assert runtime.calls == [] and runtime.sleeps == []


def test_search_array_alias_case_whitespace_and_order_use_primary(runner):
    primary = '[" STANDARD3 ", " BASIC ", " Standard "]'
    legacy = "standard3,basic,standard"
    resolved = runner.resolve_search_array(primary, legacy)
    assert resolved == "STANDARD3,BASIC,Standard"
    assert runner.candidate_order(" standard ", resolved, " TRUE ") == [
        "standard", "STANDARD3", "BASIC",
    ]
    with pytest.raises(ValueError, match="Conflicting"):
        runner.resolve_search_array(primary, "basic,standard3,standard")
    with pytest.raises(ValueError, match="not in"):
        runner.candidate_order("standard", runner.resolve_search_array(None, '["basic"]'), "true")
    with pytest.raises(ValueError, match="must not repeat"):
        runner.candidate_order("basic", '["basic", " BASIC "]', "true")


@pytest.mark.parametrize("configured", [[], {}, 1, None])
def test_search_array_alias_parser_accepts_only_process_environment_strings(runner, configured):
    with pytest.raises(ValueError, match="CSV or JSON array string"):
        runner.candidate_order("basic", configured, "true")


@pytest.mark.parametrize("disable_search", [False, True])
def test_search_array_alias_disabled_modes_ignore_both_malformed_arrays(runtime, disable_search):
    runtime.env["SKUARRAYAISEARCHDEV"] = ""
    runtime.env["SKUAISEARCHDEVARRAY"] = "$(unresolved_array)"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "invalid" if disable_search else "false"
    runtime.env["ENABLEAISEARCH"] = "false" if disable_search else "true"
    status, values, _ = runtime.attempt()
    assert status == 0
    assert len(runtime.parameters) == (0 if disable_search else 1)
    if disable_search:
        assert runtime.calls == [] and values == {}
    else:
        assert runtime.parameters[0]["skuAISearchDev"] == {"value": "standard"}
    assert runtime.sleeps == []


@pytest.mark.parametrize("arguments,expected,status", [
    ([], "basic,standard,standard2", 0),
    (["--legacy", '["standard3","basic","standard"]'], "standard3,basic,standard", 0),
    (["--primary", "basic,standard,standard2", "--legacy", "standard3,basic,standard"],
     "standard3,basic,standard", 0),
    (["--primary", "standard3,basic,standard", "--legacy", "basic,standard,storage_optimized_l1"],
     "Conflicting AI Search capacity arrays", 2),
    (["--primary", ""], "one to three nonempty SKU names", 2),
])
def test_search_array_alias_cli_is_offline_and_needs_no_deployment_arguments(arguments, expected, status):
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--resolve-search-array", *arguments],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=15,
    )
    assert result.returncode == status, result.stdout + result.stderr
    assert expected in (result.stdout if status == 0 else result.stderr)


@pytest.mark.parametrize("sku,tier", [
    ("Standard_B2s", "Burstable"), ("Standard_D4s_v3", "GeneralPurpose"),
    ("Standard_E4ds_v5", "MemoryOptimized"), ("standard_B2S", "Burstable"),
])
def test_postgresql_case_and_derived_tiers_reach_deployment(runtime, sku, tier):
    runtime.configure("postgresql")
    runtime.env["SKUPOSTGRESQLDEV"] = sku
    runtime.env["SKUARRAYPOSTGRESQLDEV"] = sku.lower() + ",Standard_B1ms"
    status, values, _ = runtime.attempt("postgresql")
    assert status == 0
    assert runtime.parameters[0]["skuPostgreSQLDev"] == {"value": sku}
    assert runtime.parameters[0]["skuTierPostgreSQLDev"] == {"value": tier}
    assert values["skuPostgreSQLDev"] == sku and values["skuTierPostgreSQLDev"] == tier


def test_postgresql_retry_rederives_tier_for_a_different_family(runtime):
    runtime.configure("postgresql")
    runtime.env["SKUARRAYPOSTGRESQLDEV"] = "Standard_B2s,Standard_D4s_v3,Standard_E4ds_v5"
    runtime.env["SKUTIERPOSTGRESQLDEV"] = "Burstable"
    runtime.outcome = (7, "", "SkuNotAvailable")
    runtime.attempt("postgresql")
    runtime.attempt("postgresql", attempt=2)
    runtime.outcome = (0, "", "")
    _, values, _ = runtime.attempt("postgresql", attempt=3)
    assert [params["skuTierPostgreSQLDev"]["value"] for params in runtime.parameters] == [
        "Burstable", "GeneralPurpose", "MemoryOptimized",
    ]
    assert values["skuTierPostgreSQLDev"] == "MemoryOptimized"


def test_postgresql_selected_tier_mismatch_is_rejected_before_azure(runtime):
    runtime.configure("postgresql")
    runtime.env["SKUTIERPOSTGRESQLDEV"] = "GeneralPurpose"
    with pytest.raises(ValueError, match="requires tier Burstable"):
        runtime.attempt("postgresql")
    assert runtime.calls == [] and runtime.sleeps == []


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("service", SERVICES)
def test_parameters_are_filtered_typed_aliased_and_never_logged(runtime, provider, service):
    runtime.configure(service, "test")
    if provider == "github":
        runtime.env.update({key: value for key, value in environment(service, "test").items()})
    runtime.attempt(service, provider)
    params = runtime.parameters[0]
    assert "unrelatedNetworkParameter" not in params
    assert params["tagsProject"] == {"value": TAGS}
    assert params["projectNumber"] == {"value": "001"}
    assert params["env"] == {"value": "test"}
    assert params["location"] == {"value": "swedencentral"}
    assert params["vnetResourceGroup_param"] == {"value": "unit-network-rg"}
    assert params["vnetNameFull_param"] == {"value": "unit-vnet-full"}
    if service != "postgresql":
        assert params["IPwhiteList"] == {"value": "192.0.2.1/32"}
    else:
        assert "IPwhiteList" not in params
    assert params["genaiSubnetId"] == {"value": "unit-subnet"}
    if service == "postgresql":
        assert params["inputKeyvault"] == {"value": "unit-keyvault"}
        assert params["technicalAdminsObjectID"] == {"value": "unit-object-id"}
        assert params["projectServicePrincipleOID_SeedingKeyvaultName"] == {"value": PRIVATE_VALUE}
        assert params["useAdGroups"] == {"value": True}


def test_missing_required_parameter_has_explicit_error_and_no_deployment(runtime):
    runtime.env.pop("PROJECT_NUMBER_000")
    with pytest.raises(ValueError, match="Required deployment parameter projectNumber is missing"):
        runtime.attempt()
    assert len(runtime.calls) == 1 and runtime.parameters == [] and runtime.sleeps == []


@pytest.mark.parametrize("kind,value,expected", [
    ("bool", "false", False), ("int", "3", 3), ("object", '{"a":[1]}', {"a": [1]}),
    ("array", '[1,"x"]', [1, "x"]), ("securestring", PRIVATE_VALUE, PRIVATE_VALUE),
])
def test_parameter_types_are_converted_without_shell_interpolation(runner, kind, value, expected):
    assert runner.parameter_value("unit", value, {"type": kind}) == expected


@pytest.mark.parametrize("kind,value", [
    ("secureObject", "{}"), ("float", "1.2"), ("bool", "yes"),
    ("object", "[]"), ("array", "{}"),
])
def test_unsupported_or_malformed_parameter_types_fail_explicitly(runner, kind, value):
    with pytest.raises(ValueError):
        runner.parameter_value("unit", value, {"type": kind})


def test_build_failure_never_sleeps_deploys_or_publishes(runtime):
    runtime.build_outcome = (13, "", "offline compilation failed")
    status, values, captured = runtime.attempt()
    assert status == 13 and values == {}
    assert "offline compilation failed" in captured.err
    assert len(runtime.calls) == 1 and runtime.parameters == [] and runtime.sleeps == []


@pytest.mark.parametrize("selected", ["", "   ", "basic;echo"])
def test_empty_or_unsafe_selected_sku_is_rejected_before_azure(runtime, selected):
    runtime.env[(SERVICES["ai-search"]["sku"] + "Dev").upper()] = selected
    with pytest.raises(ValueError, match="Selected capacity SKU"):
        runtime.attempt()
    assert runtime.calls == [] and runtime.sleeps == []


def test_cli_parser_rejects_a_fourth_attempt(runtime, runner, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [str(RUNNER), "--attempt", "4"])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert re.search(r"invalid choice: '?4'?", capsys.readouterr().err)
    assert runtime.calls == []


def expanded_steps(provider, service):
    if provider == "github":
        return [
            step for step in objects(load_pipeline(GHA))
            if isinstance(step.get("run"), str)
            and re.search(r"--service\s+" + re.escape(service) + r"\s", step["run"])
            and "deploy-capacity-resource.py" in step.get("run", "")
        ]
    includes = [
        step for step in load_pipeline(ADO_JOB)["steps"]
        if step.get("template") == ADO_ATTEMPTS.name and step["parameters"]["service"] == service
    ]
    assert len(includes) == 1
    parameters = includes[0]["parameters"]
    result = []
    for step in load_pipeline(ADO_ATTEMPTS)["steps"]:
        expanded = json.dumps(step)
        # Replace only CI template syntax, never Bash substitutions or $variables.
        expanded = re.sub(
            r"\$\{\{\s*parameters\.(\w+)\s*\}\}",
            lambda match: parameters[match[1]], expanded,
        )
        result.append(json.loads(expanded))
    return result


def allowed(step, provider, env, phase="infra", success=True):
    context = {"success": success, "inputs.phase": phase, "parameters.phase": phase}
    context.update({f"env.{key}": value for key, value in env.items()})
    context.update({f"variables.{key}": value for key, value in env.items()})
    for spec in SERVICES.values():
        context.setdefault("env." + spec["state"], "")
        context.setdefault("variables." + spec["state"], "")
    expression = step["if"] if provider == "github" else step["condition"]
    expression = re.sub(r"\$\{\{\s*parameters\.phase\s*\}\}", phase, expression)
    # GHA adds an implicit success() unless a status-check function is supplied.
    return success and bool(evaluate(expression, context))


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("state", ["", "0", "2", "3", "failed"])
def test_actual_conditions_arm_only_the_exact_next_step(service, provider, state):
    env = environment(service)
    env[SERVICES[service]["state"]] = state
    steps = expanded_steps(provider, service)
    assert len(steps) == 3
    assert [allowed(step, provider, env) for step in steps] == [True, state == "2", state == "3"]


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("blocked", ["disabled", "deleted", "phase", "debug", "failed", "skipped"])
def test_all_attempt_conditions_preserve_service_and_ci_gates(service, provider, blocked):
    env = environment(service)
    env[SERVICES[service]["state"]] = "2"
    if blocked == "disabled":
        env[SERVICES[service]["flag"]] = "false"
    elif blocked == "deleted":
        env["deleteAllServicesForProject"] = "true"
    elif blocked == "debug":
        env[SERVICES[service]["debug"]] = "true"
    elif blocked == "skipped":
        env[SERVICES[service]["state"]] = ""
    steps = expanded_steps(provider, service)
    actual = [
        allowed(step, provider, env, phase="apps" if blocked == "phase" else "infra",
                success=blocked != "failed")
        for step in steps
    ]
    assert actual == ([True, False, False] if blocked == "skipped" else [False, False, False])


@pytest.fixture
def script_harness(workspace):
    bash = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if os.name == "nt" else Path(shutil.which("bash") or "")
    )
    if not bash.is_file():
        pytest.skip("Pinned Git Bash (Windows) or Bash (Unix) is required")
    checkout = workspace / "work" / "azure-enterprise-scale-ml"
    mirrored_bicep = checkout / "environment_setup" / "aifactory" / "bicep"
    (mirrored_bicep / "scripts").mkdir(parents=True)
    shutil.copyfile(RUNNER, mirrored_bicep / "scripts" / RUNNER.name)
    (mirrored_bicep / "esml-genai-1").mkdir()
    definitions = {}
    for service, spec in SERVICES.items():
        source = BICEP / "esml-genai-1" / spec["template"]
        shutil.copyfile(source, mirrored_bicep / "esml-genai-1" / source.name)
        definitions[source.name] = parameter_definitions(source)
    (workspace / "templates.json").write_text(json.dumps(definitions), encoding="utf-8")
    dynamic_parameters(workspace / "work" / "aifactory" / "parameters" / "dynamicNetworkParams.json")
    log = workspace / "az.jsonl"
    sleeps = workspace / "sleep.jsonl"
    mock = workspace / "mock_az.py"
    mock.write_text(textwrap.dedent("""
        import json, os, pathlib, sys
        root = pathlib.Path(os.environ["CAPACITY_TEST_ROOT"])
        args = sys.argv[1:]
        record = {"argv": args}
        if args[:2] == ["bicep", "build"]:
            name = pathlib.Path(args[args.index("--file") + 1]).name
            result = json.loads((root / "templates.json").read_text(encoding="utf-8"))[name]
            with (root / "az.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(record) + "\\n")
            print(json.dumps(result))
            sys.exit(0)
        assert args[:3] == ["deployment", "sub", "create"], args
        parameter = args[args.index("--parameters") + 1]
        assert parameter.startswith("@") and args.count("--parameters") == 1
        path = pathlib.Path(parameter[1:])
        record["path"] = str(path)
        record["parameters"] = json.loads(path.read_text(encoding="utf-8"))["parameters"]
        with (root / "az.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(record) + "\\n")
        print(os.environ.get("CAPACITY_TEST_ERROR", ""), file=sys.stderr)
        sys.exit(int(os.environ["CAPACITY_TEST_STATUS"]))
    """), encoding="utf-8")
    az = workspace / ("az.cmd" if os.name == "nt" else "az")
    if os.name == "nt":
        az.write_text(f'@echo off\n"{sys.executable}" "{mock}" %*\n', encoding="utf-8")
    else:
        az.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(mock))} \"$@\"\n",
                      encoding="utf-8")
        az.chmod(0o755)
    wrapper = workspace / "python_wrapper.py"
    wrapper.write_text(textwrap.dedent("""
        import json, os, pathlib, runpy, shutil, sys, tempfile, time
        root = pathlib.Path(os.environ["CAPACITY_TEST_ROOT"])
        original_which = shutil.which
        shutil.which = lambda name: str(root / ("az.cmd" if os.name == "nt" else "az")) if name == "az" else original_which(name)
        def sleep(seconds):
            with (root / "sleep.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(seconds) + "\\n")
        time.sleep = sleep
        tempfile.tempdir = str(root)
        sys.argv = sys.argv[1:]
        runpy.run_path(sys.argv[0], run_name="__main__")
    """), encoding="utf-8")

    class Harness:
        def __init__(self):
            self.results, self.published = [], []

        def execute(self, service, provider, target="dev", succeed_at=3, error="SkuNotAvailable",
                    overrides=None, remove=()):
            env = environment(service, target)
            env.update(overrides or {})
            for key in remove:
                env.pop(key)
            steps = expanded_steps(provider, service)
            success = True
            for attempt, step in enumerate(steps, 1):
                if not allowed(step, provider, env, success=success):
                    continue
                script = step["run"] if provider == "github" else step["inputs"]["inlineScript"]
                script = re.sub(r"\$\{\{\s*env\.(\w+)\s*\}\}", lambda m: env[m[1]], script)
                script = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)", lambda m: env[m[1]], script)
                assert "${{" not in script
                child_env = os.environ.copy()
                child_env.update({key.upper() if provider == "ado" else key: value for key, value in env.items()})
                child_env.update({
                    "CAPACITY_TEST_ROOT": str(workspace), "CAPACITY_TEST_STATUS": "0" if attempt == succeed_at else "29",
                    "CAPACITY_TEST_ERROR": "" if attempt == succeed_at else error,
                    "GITHUB_ENV": str(workspace / "github-env"), "PYTHONIOENCODING": "utf-8",
                    "MSYS_NO_PATHCONV": "1",
                })
                for key, value in step.get("env", {}).items():
                    if key.startswith("${{"):
                        if service == "postgresql":
                            child_env.update(value)
                    else:
                        child_env[key] = re.sub(
                            r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)", lambda m: env[m[1]], value,
                        )
                github_env = workspace / "github-env"
                if github_env.exists():
                    github_env.unlink()
                prefix = (
                    f"python() {{ {shlex.quote(sys.executable.replace(chr(92), '/'))} "
                    f"{shlex.quote(str(wrapper).replace(chr(92), '/'))} \"$@\"; }}\n"
                )
                result = subprocess.run(
                    [str(bash), "--noprofile", "--norc", "-c", prefix + script],
                    cwd=workspace / "work" if provider == "github" else mirrored_bicep,
                    env=child_env, capture_output=True, text=True, timeout=30, check=False,
                )
                self.results.append(result)
                values = publications(provider, result.stdout, github_env)
                self.published.append(values)
                env.update(values)
                success = result.returncode == 0
            return env

        def records(self):
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

        def sleep_values(self):
            return [json.loads(line) for line in sleeps.read_text(encoding="utf-8").splitlines()] if sleeps.exists() else []

    return Harness()


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("target", ["dev", "test", "prod"])
@pytest.mark.parametrize("succeed_at", [1, 2, 3])
def test_extracted_ci_scripts_execute_real_cli_offline(script_harness, provider, service, target, succeed_at):
    final = script_harness.execute(service, provider, target, succeed_at)
    spec = SERVICES[service]
    suffix = "Dev" if target == "dev" else "StageProd"
    assert len(script_harness.results) == succeed_at
    assert all(result.returncode == 0 for result in script_harness.results), [
        result.stderr for result in script_harness.results
    ]
    records = script_harness.records()
    creates = [record for record in records if "parameters" in record]
    assert len(records) == 2 * succeed_at and len(creates) == succeed_at
    assert [record["parameters"][spec["sku"] + suffix]["value"] for record in creates] == spec["order"][:succeed_at]
    assert [values[spec["state"]] for values in script_harness.published] == [
        str(attempt + 1) if attempt < succeed_at else "0" for attempt in range(1, succeed_at + 1)
    ]
    assert final[spec["sku"] + suffix] == spec["order"][succeed_at - 1]
    assert script_harness.sleep_values() == [240] * (succeed_at - 1)
    for record in creates:
        params = record["parameters"]
        assert "unrelatedNetworkParameter" not in params
        assert params["tagsProject"] == {"value": TAGS}
        assert params["projectNumber"] == {"value": "001"}
        assert params["env"] == {"value": target}
        assert not Path(record["path"]).parent.exists()
        assert PRIVATE_VALUE not in " ".join(record["argv"])
        if service == "postgresql":
            assert params["postgreSQLVersion"] == {"value": "17"}
            assert params["projectServicePrincipleOID_SeedingKeyvaultName"] == {"value": PRIVATE_VALUE}
    assert all(PRIVATE_VALUE not in result.stdout + result.stderr for result in script_harness.results)


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("error,attempts", [
    ("SkuNotAvailable", 3), ("AuthorizationFailed", 1), ("AuthorizationFailed\nSkuNotAvailable", 1),
])
def test_extracted_ci_scripts_fail_terminally_and_clean_parameters(script_harness, provider, service, error, attempts):
    script_harness.execute(service, provider, succeed_at=4, error=error)
    assert len(script_harness.results) == attempts
    assert script_harness.results[-1].returncode == 29, script_harness.results[-1].stderr
    assert script_harness.published[-1] == {SERVICES[service]["state"]: "failed"}
    creates = [record for record in script_harness.records() if "parameters" in record]
    assert len(creates) == attempts and all(not Path(record["path"]).parent.exists() for record in creates)
    assert script_harness.sleep_values() == [240] * (attempts - 1)


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("service", SERVICES)
def test_extracted_cli_rejects_invalid_array_before_azure(script_harness, provider, service):
    spec = SERVICES[service]
    script_harness.execute(service, provider, overrides={spec["array"] + "Dev": ""})
    assert len(script_harness.results) == 1
    assert script_harness.results[0].returncode == 2
    assert "configuration error" in script_harness.results[0].stderr
    assert script_harness.records() == [] and script_harness.sleep_values() == []


@pytest.mark.parametrize("provider", ["ado", "github"])
def test_extracted_cli_reports_missing_required_parameter(script_harness, workspace, provider):
    path = workspace / "work" / "aifactory" / "parameters" / "dynamicNetworkParams.json"
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    document["parameters"].pop("genaiSubnetId")
    path.write_text(json.dumps(document), encoding="utf-8")
    script_harness.execute("ai-search", provider, remove=("genaiSubnetId",))
    result = script_harness.results[0]
    assert len(script_harness.results) == 1 and result.returncode == 2
    assert "Required deployment parameter genaiSubnetId is missing" in result.stderr
    records = script_harness.records()
    assert len(records) == 1 and records[0]["argv"][:2] == ["bicep", "build"]
    assert script_harness.sleep_values() == []


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("limit", [0, 1, 2])
def test_extracted_scripts_stop_when_retry_is_disabled_or_candidates_end(script_harness, provider, service, limit):
    spec = SERVICES[service]
    overrides = (
        {spec["retry"]: "false", spec["array"] + "Dev": "invalid,,four,values"}
        if limit == 0 else {spec["array"] + "Dev": ",".join(spec["order"][:limit])}
    )
    script_harness.execute(service, provider, succeed_at=4, overrides=overrides)
    attempts = max(limit, 1)
    assert len(script_harness.results) == attempts
    assert script_harness.results[-1].returncode == 29
    assert script_harness.published[-1] == {spec["state"]: "failed"}
    creates = [record for record in script_harness.records() if "parameters" in record]
    assert [record["parameters"][spec["sku"] + "Dev"]["value"] for record in creates] == spec["order"][:attempts]
    assert script_harness.sleep_values() == [240] * (attempts - 1)


@pytest.mark.parametrize("service", SERVICES)
def test_defaults_arrays_and_retry_flags_match_all_three_configs(service):
    spec = SERVICES[service]
    json_values = json.loads((BICEP.parent / "variables.json").read_text(encoding="utf-8"))["dev"]
    ado_values = load_pipeline(ADO / "variables" / "variables.yaml")["variables"]
    github_values = dict(re.findall(
        r'^([A-Z][A-Z0-9_]*)="([^"]*)"\s*(?:#.*)?$',
        (SETTINGS / "github-actions" / ".env.template").read_text(encoding="utf-8"), re.M,
    ))
    bindings = load_pipeline(GHA)["jobs"]["deploy-project"]["env"]
    for suffix, public_suffix in [("Dev", "DEV"), ("StageProd", "STAGEPROD")]:
        key = spec["array"] + suffix
        public = f"SKU_ARRAY_{spec['public']}_{public_suffix}"
        assert json_values[key] == ado_values[key] == github_values[public] == spec["array_value"]
        assert evaluate(bindings[key], {f"vars.{public}": ""}) == spec["array_value"]
        assert evaluate(bindings[key], {f"vars.{public}": "custom"}) == "custom"
    public_retry = {
        "ai-search": "AISEARCH_RETRY_CAPCITY_ARRAY",
        "postgresql": "POSTGRESQL_RETRY_CAPACITY_ARRAY",
        "container-apps": "CONTAINER_APPS_RETRY_CAPACITY_ARRAY",
    }[service]
    assert str(json_values[spec["retry"]]).lower() == ado_values[spec["retry"]] == github_values[public_retry] == "true"
    assert evaluate(bindings[spec["retry"]], {f"vars.{public_retry}": ""}) == "true"
    assert evaluate(bindings[spec["retry"]], {f"vars.{public_retry}": "false"}) == "false"


def test_actual_json_exporter_maps_public_capacity_aliases_and_preserves_tags(workspace):
    public_retry = {
        "ai-search": "AISEARCH_RETRY_CAPCITY_ARRAY",
        "postgresql": "POSTGRESQL_RETRY_CAPACITY_ARRAY",
        "container-apps": "CONTAINER_APPS_RETRY_CAPACITY_ARRAY",
    }
    values = {"tagsProject": TAGS}
    expected = {"tagsProject": TAGS}
    for service, spec in SERVICES.items():
        for suffix, public_suffix in [("Dev", "DEV"), ("StageProd", "STAGEPROD")]:
            values[f"SKU_ARRAY_{spec['public']}_{public_suffix}"] = spec["array_value"]
            expected[spec["array"] + suffix] = spec["array_value"]
        values[public_retry[service]] = True
        expected[spec["retry"]] = "true"
    config = workspace / "capacity.json"
    config.write_text(json.dumps({"dev": values}), encoding="utf-8")
    output = workspace / "exported-env"
    env = os.environ.copy()
    env["GITHUB_ENV"] = str(output)
    result = subprocess.run(
        [sys.executable, str(BICEP / "scripts" / "apply-json-config-overrides.py"),
         "--file", str(config), "--environment", "test", "--format", "github",
         "--github-workflow", str(GHA)],
        env=env, cwd=ROOT, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    exported = {}
    for index in range(0, len(lines), 3):
        name, delimiter = lines[index].split("<<", 1)
        assert lines[index + 2] == delimiter
        exported[name] = lines[index + 1]
    for name, value in expected.items():
        assert (json.loads(exported[name]) if name == "tagsProject" else exported[name]) == value
    assert PRIVATE_VALUE not in result.stdout + result.stderr


def arm_value(expression, parameters, variables=None):
    """Evaluate only the compiled boolean/profile ARM subset used below."""
    if not isinstance(expression, str) or not expression.startswith("["):
        return expression
    tokens = re.findall(r"'(?:[^']|'')*'|[A-Za-z_]\w*|\d+|[,()]", expression[1:-1])
    position = 0

    def parse():
        nonlocal position
        token = tokens[position]
        position += 1
        if token.startswith("'"):
            return token[1:-1].replace("''", "'")
        if token.isdigit():
            return int(token)
        assert tokens[position] == "("
        position += 1
        args = []
        while tokens[position] != ")":
            args.append(parse())
            if tokens[position] != ",":
                break
            position += 1
        assert tokens[position] == ")"
        position += 1
        functions = {
            "parameters": lambda key: parameters[key],
            "variables": lambda key: arm_value(variables[key], parameters, variables),
            "if": lambda condition, yes, no: yes if condition else no,
            "equals": lambda left, right: left == right, "not": lambda value: not value,
            "and": lambda *values: all(values), "or": lambda *values: any(values),
            "true": lambda: True, "false": lambda: False,
            "empty": lambda value: not value, "toLower": lambda value: value.lower(),
            "null": lambda: None, "createArray": lambda *values: list(values),
            "createObject": lambda *values: dict(zip(values[::2], values[1::2])),
            "flatten": lambda values: [item for value in values for item in value],
        }
        assert token in functions, f"Unreviewed compiled ARM function: {token}"
        return functions[token](*args)

    result = parse()
    assert position == len(tokens)
    return result


@pytest.fixture(scope="module")
def compiled():
    executable = shutil.which("bicep")
    if executable is None:
        pytest.skip("Optional installed Bicep CLI is unavailable; runtime tests use actual source declarations")
    result = {}
    for name in [spec["template"] for spec in SERVICES.values()] + [
        "03-cognitive-services.bicep", "04-databases.bicep", "05-compute-services.bicep",
    ]:
        build = subprocess.run(
            [executable, "build", str(BICEP / "esml-genai-1" / name), "--stdout", "--no-restore"],
            capture_output=True, text=True, timeout=90, check=False,
        )
        assert build.returncode == 0, build.stderr
        result[name] = json.loads(build.stdout)
    return result


def test_source_parameter_mock_matches_real_compilation(compiled):
    for spec in SERVICES.values():
        actual = compiled[spec["template"]]["parameters"]
        exposed = parameter_definitions(BICEP / "esml-genai-1" / spec["template"])["parameters"]
        assert set(actual) == set(exposed)
        for name in actual:
            assert actual[name]["type"].lower() == exposed[name]["type"].lower()
            assert ("defaultValue" in actual[name]) == ("defaultValue" in exposed[name])


@pytest.mark.parametrize("profile", ["Consumption", "D4", "D8"])
def test_compiled_container_apps_profiles_are_deployable_and_select_matching_app_profile(compiled, profile):
    template = compiled["05b-container-apps.bicep"]
    assert template["parameters"]["skuContainerAppsDev"]["allowedValues"] == ["Consumption", "D4", "D8"]
    assert template["parameters"]["skuContainerAppsStageProd"]["allowedValues"] == ["Consumption", "D4", "D8"]
    resources = [node for node in objects(template) if node.get("type") == "Microsoft.App/managedEnvironments"]
    assert len(resources) == 1
    profiles = arm_value(
        resources[0]["properties"]["workloadProfiles"],
        {"workloadProfileType": profile, "wlMinCountDedicated": 1, "wlMaxCount": 5},
    )
    assert profiles == (
        [{"name": "Consumption", "workloadProfileType": "Consumption"}]
        + ([] if profile == "Consumption" else [{
            "name": "aifactory-dedicated", "workloadProfileType": profile, "minimumCount": 1, "maximumCount": 5,
        }])
    )
    service_templates = [
        node for node in objects(template)
        if "appWorkloadProfileName" in node.get("variables", {})
    ]
    assert len(service_templates) == 1
    chosen = arm_value(
        service_templates[0]["variables"]["appWorkloadProfileName"],
        {"workloadProfileType": profile, "acaAppWorkloadProfileName": "consumption"},
    )
    assert chosen == ("Consumption" if profile == "Consumption" else "aifactory-dedicated")
    apps = [node for node in objects(template) if node.get("type") == "Microsoft.App/containerApps"]
    assert len(apps) == 2
    assert all(arm_value(app["properties"]["workloadProfileName"], {"appWorkloadProfileName": chosen}) == chosen for app in apps)


@pytest.mark.parametrize("existed", [False, True])
def test_container_apps_retries_preserve_preexisting_apps(compiled, existed):
    template = compiled["05b-container-apps.bicep"]
    assert template["parameters"]["updateExistingContainerApps"]["defaultValue"] is False
    shared = next(
        node for node in objects(template)
        if "deployEnvironment" in node.get("variables", {}) and "deployApi" in node["variables"]
    )
    parameters = {
        "containerAppsEnvExists": existed, "containerAppAExists": existed,
        "containerAppWExists": existed, "updateExistingContainerApps": False,
    }
    for name in ("deployEnvironment", "deployApi", "deployWeb"):
        assert arm_value(shared["variables"][name], parameters) is not existed


@pytest.mark.parametrize("service,old,disable,resource_type", [
    ("ai-search", "03-cognitive-services.bicep", "deployAISearch", "Microsoft.Search/searchServices"),
    ("postgresql", "04-databases.bicep", "enablePostgreSQL", "Microsoft.DBforPostgreSQL/flexibleServers"),
    ("container-apps", "05-compute-services.bicep", "enableContainerApps", "Microsoft.App/managedEnvironments"),
])
def test_compiled_batch_conditions_and_actual_pipeline_arguments_prevent_duplicate_deployment(
    compiled, service, old, disable, resource_type,
):
    standalone = compiled[SERVICES[service]["template"]]
    assert len([node for node in objects(standalone) if node.get("type") == resource_type]) == 1
    other_resources = {
        "Microsoft.Search/searchServices", "Microsoft.DBforPostgreSQL/flexibleServers",
        "Microsoft.App/managedEnvironments",
    } - {resource_type}
    assert not any(node.get("type") in other_resources for node in objects(standalone))
    old_template = compiled[old]
    resources = old_template["resources"]
    resources = list(resources.values()) if isinstance(resources, dict) else resources
    gates = [
        resource for resource in resources
        if any(node.get("type") == resource_type for node in objects(resource))
    ]
    assert len(gates) == 1
    parameters = {
        name: declaration.get("defaultValue")
        for name, declaration in old_template["parameters"].items()
    }
    parameters.update({
        "enableAISearch": True, "enableAIFoundry": True, "enablePublicGenAIAccess": False,
        "enablePostgreSQL": True, "postgreSQLExists": False, "enableContainerApps": True,
        "containerAppsEnvExists": False,
    })
    parameters[disable] = False
    assert arm_value(gates[0]["condition"], parameters, old_template.get("variables", {})) is False
    for pipeline in (ADO_JOB, GHA):
        found = [deployment for deployment in deployments(load_pipeline(pipeline)) if deployment.module == old]
        assert len(found) == 1
        assert found[0].parameters[disable] == "false"
