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
SEARCH_FALLBACK_REGIONS = ["francecentral", "denmarkeast", "italynorth", "norwayeast", "germanywestcentral"]


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
        "aiSearchFallbackLocationArrayDev": "[]",
        "aiSearchFallbackLocationArrayStageProd": "[]",
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
        return {name: value.replace("%5D", "]").replace("%3B", ";").replace("%AZP25", "%")
                for name, value in re.findall(r"##vso\[task.setvariable variable=(\w+)\]([^\r\n]*)", stdout)}
    return dict(
        line.split("=", 1) for line in github_env.read_text(encoding="utf-8").splitlines()
    ) if github_env.exists() else {}


@pytest.fixture
def runtime(runner, workspace, monkeypatch, capsys):
    class Runtime:
        def __init__(self):
            self.calls, self.parameters, self.paths, self.sleeps = [], [], [], []
            self.group_errors = {}
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
            if command[1:4] == ["rest", "--method", "get"]:
                return subprocess.CompletedProcess(command, 1, "", "(ResourceNotFound) Not found")
            if command[1:3] == ["bicep", "build"]:
                if self.build_outcome:
                    return subprocess.CompletedProcess(command, *self.build_outcome)
                template = parameter_definitions(Path(command[command.index("--file") + 1]))
                return subprocess.CompletedProcess(command, 0, json.dumps(template), "")
            if command[1:4] == ["deployment", "group", "show"]:
                assert command[command.index("--subscription") + 1] == "unit-subscription"
                assert command[command.index("--resource-group") + 1] == "rg"
                assert command[command.index("--query") + 1] == "properties.error"
                return subprocess.CompletedProcess(command, *self.group_errors.get(
                    command[command.index("--name") + 1], (1, "", "UnknownFailure")))
            assert command[1:4] == ["deployment", "sub", "create"]
            parameter_arg = command[command.index("--parameters") + 1]
            assert parameter_arg.startswith("@") and command.count("--parameters") == 1
            path = Path(parameter_arg[1:])
            parameters = json.loads(path.read_text(encoding="utf-8"))["parameters"]
            if parameters.get("capacityIdentityOnly", {}).get("value"):
                return subprocess.CompletedProcess(command, 0, json.dumps({"properties": {"outputs": {
                    "aiSearchResourceId": {"value": "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/search"},
                }}}), "")
            self.paths.append(path)
            self.parameters.append(json.loads(path.read_text(encoding="utf-8"))["parameters"])
            assert PRIVATE_VALUE not in " ".join(command)
            return subprocess.CompletedProcess(command, *self.outcome)

        def attempt(self, service="ai-search", provider="ado", attempt=1, regional=False):
            args = argparse.Namespace(
                service=service, provider=provider, attempt=attempt,
                search_region_fallback=regional,
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


def primary_attempts(runtime, provider="ado"):
    for attempt in range(1, 4):
        result = runtime.attempt(provider=provider, attempt=attempt)
        if result[0] or result[1].get("AIF_AISEARCH_CAPACITY_NEXT") in ("0", "primary-capacity-exhausted"):
            return result
    return result


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_primary_exhaustion_is_pending_not_provisioned_then_denmark_italy(runtime, provider, target, suffix):
    runtime.configure("ai-search", target)
    runtime.env[("aiSearchFallbackLocationArray" + suffix).upper()] = '["denmarkeast","italynorth"]'
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    for attempt in (1, 2, 3):
        status, values, _ = runtime.attempt(provider=provider, attempt=attempt)
        assert status == 0
        assert values["AIF_AISEARCH_CAPACITY_NEXT"] == (str(attempt + 1) if attempt < 3 else "primary-capacity-exhausted")
        assert "aiSearchLocation" not in values and "skuAISearch" + suffix not in values
    assert len(runtime.parameters) == 3
    status, values, _ = runtime.attempt(provider=provider, regional=True)
    assert status == 19 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert [(p["aiSearchLocation"]["value"], p["skuAISearch" + suffix]["value"]) for p in runtime.parameters] == [
        (region, sku) for region in ("swedencentral", "denmarkeast", "italynorth")
        for sku in SERVICES["ai-search"]["order"]
    ]
    assert runtime.sleeps == [240] * 8


def test_manual_regional_invocation_requires_validated_primary_failure(runtime):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast"
    with pytest.raises(ValueError, match="not armed"):
        runtime.attempt(regional=True)
    assert runtime.parameters == []


def search_deployment_wrapper(name="search-nested", group="rg", code="ResourceDeploymentFailure"):
    return {"code": code, "target": (
        f"/subscriptions/unit-subscription/resourceGroups/{group}/providers/Microsoft.Resources/deployments/{name}"
    ), "message": "The resource write operation reached terminal provisioning state Failed."}


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_primary_and_regional_capacity_can_resolve_exact_search_rg_wrapper_errors(runtime, provider, target, suffix):
    runtime.configure("ai-search", target)
    runtime.env[("aiSearchFallbackLocationArray" + suffix).upper()] = "denmarkeast,italynorth"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    runtime.outcome = (19, "", json.dumps({"error": {"code": "DeploymentFailed",
                                                  "details": [search_deployment_wrapper()]}}))
    runtime.group_errors["search-nested"] = (0, json.dumps(search_deployment_wrapper("search-inner")), "")
    runtime.group_errors["search-inner"] = (0, json.dumps({"code": "InsufficientResourcesAvailable"}), "")
    status, values, _ = runtime.attempt(provider=provider)
    assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    status, values, _ = runtime.attempt(provider=provider, regional=True)
    assert status == 19 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert [p["aiSearchLocation"]["value"] for p in runtime.parameters] == [
        "swedencentral", "denmarkeast", "italynorth",
    ]
    reads = [call[call.index("--name") + 1] for call in runtime.calls
             if call[1:4] == ["deployment", "group", "show"]]
    assert reads == ["search-nested", "search-inner"] * 3


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_nullable_azure_cli_error_children_allow_primary_to_regional_handoff(runtime, provider, target, suffix):
    runtime.configure("ai-search", target)
    runtime.env[("aiSearchFallbackLocationArray" + suffix).upper()] = "denmarkeast,italynorth"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    wrapper = {**search_deployment_wrapper(), "details": None, "additionalInfo": None,
               "error": None, "innererror": None, "innerError": None}
    payload = {"code": "DeploymentFailed", "additionalInfo": None,
               "target": "/subscriptions/unit-subscription/providers/Microsoft.Resources/deployments/search-primary",
               "details": [wrapper]}
    leaf = {"code": "InsufficientResourcesAvailable", "details": None, "target": None,
            "additionalInfo": None, "error": None, "innererror": None, "innerError": None}
    runtime.outcome = (19, "", "ERROR: " + json.dumps(payload))
    runtime.group_errors["search-nested"] = (0, json.dumps({"code": "DeploymentFailed", "details": [leaf]}), "")
    status, values, _ = runtime.attempt(provider=provider)
    assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    assert "aiSearchLocation" not in values and "skuAISearch" + suffix not in values
    assert [parameters["aiSearchLocation"]["value"] for parameters in runtime.parameters] == ["swedencentral"]
    runtime.outcome = (0, "{}", "")
    status, values, _ = runtime.attempt(provider=provider, regional=True)
    assert status == 0 and values["aiSearchLocation"] == "denmarkeast"
    assert [parameters["aiSearchLocation"]["value"] for parameters in runtime.parameters] == ["swedencentral", "denmarkeast"]
    assert sum(call[1:4] == ["deployment", "group", "show"] for call in runtime.calls) == 1


@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("subscription", ["unit-subscription", "other-subscription"])
def test_reported_subscription_deployment_envelope_preserves_capacity_evidence(runtime, complete, subscription):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    nested = search_deployment_wrapper()
    if complete:
        nested["details"] = [{"code": "DeploymentFailed", "details": [
            {"code": "InsufficientResourcesAvailable"}]}]
    else:
        runtime.group_errors["search-nested"] = (0, json.dumps({"code": "InsufficientResourcesAvailable"}), "")
    payload = {"status": "Failed", "error": {
        "code": "DeploymentFailed",
        "target": f"/subscriptions/{subscription}/providers/Microsoft.Resources/deployments/primary-search",
        "details": [nested],
    }}
    runtime.outcome = (19, "", "ERROR: " + json.dumps(payload))
    status, values, _ = runtime.attempt()
    if subscription == "unit-subscription":
        assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    else:
        assert status == 19 and values == {"AIF_AISEARCH_CAPACITY_NEXT": "failed"}
    reads = [call for call in runtime.calls if call[1:4] == ["deployment", "group", "show"]]
    assert len(reads) == int(subscription == "unit-subscription" and not complete)


@pytest.mark.parametrize("payload", [
    {"error": search_deployment_wrapper(group="other-rg")},
    {"error": search_deployment_wrapper(code="DeploymentFailed")},
    {"error": {"code": "ResourceDeploymentFailure"}},
    {"error": {"code": "DeploymentFailed", "details": [search_deployment_wrapper(), {"code": "UnknownFailure"}]}},
    {"error": {"code": "DeploymentFailed", "details": [search_deployment_wrapper(), {"code": "AuthorizationFailed"}]}},
    {"error": {"code": "DeploymentFailed", "details": [search_deployment_wrapper(), {"code": "QuotaExceeded"}]}},
    {"error": {"code": "ResourceDeploymentFailure", "target": (
        "/subscriptions/other-sub/resourceGroups/rg/providers/Microsoft.Resources/deployments/search-nested")}},
    {"error": {"code": "ResourceDeploymentFailure", "target": (
        "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Resources/deployments/../escape")}},
    {"error": search_deployment_wrapper("..")},
])
def test_untrusted_or_mixed_deployment_wrappers_never_trigger_readback_or_fallback(runtime, payload):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast"
    runtime.outcome = (19, "", json.dumps(payload))
    status, values, _ = runtime.attempt()
    assert status == 19 and values == {"AIF_AISEARCH_CAPACITY_NEXT": "failed"}
    assert not any(call[1:4] == ["deployment", "group", "show"] for call in runtime.calls)
    assert len(runtime.parameters) == 1 and runtime.sleeps == []


@pytest.mark.parametrize("outcome", [
    (1, "", "AuthorizationFailed"),
    (0, '{"code":"InsufficientResourcesAvailable"}', "AuthorizationFailed"),
    (0, '{"code":"InsufficientResourcesAvailable"', ""),
    (0, "null", ""),
    (0, '[]', ""),
    (0, '{"code":"UnknownFailure","code":"InsufficientResourcesAvailable"}', ""),
    (0, '{"code":"AuthorizationFailed"}', ""),
    (0, '{"code":"UnknownFailure"}', ""),
    (0, '{"code":"DeploymentFailed"}', ""),
    (0, '{"code":"DeploymentFailed","details":[{"code":"InsufficientResourcesAvailable"},{"code":"QuotaExceeded"}]}', ""),
    (0, '{"code":"InsufficientResourcesAvailable","target":"Microsoft.Network/privateEndpoints/pe"}', ""),
    (0, '{"code":"InsufficientResourcesAvailable","target":"Microsoft.CognitiveServices/accounts/other"}', ""),
    (0, '{"code":"InsufficientResourcesAvailable","target":"/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/other"}', ""),
    (0, json.dumps({**search_deployment_wrapper("search-inner"), "message": "AuthorizationFailed"}), ""),
    (0, json.dumps({**search_deployment_wrapper("search-inner"), "message": "Private endpoint allocation failed."}), ""),
    (0, '{"code":"DeploymentFailed","details":null,"target":null}', ""),
    (0, '{"code":"DeploymentFailed","details":[{"code":"InsufficientResourcesAvailable","details":null},{"code":"InvalidTemplate","details":null}]}', ""),
    (0, '{"code":"InsufficientResourcesAvailable","details":"malformed"}', ""),
    (0, '{"code":"InsufficientResourcesAvailable","details":[null]}', ""),
    (0, '{"code":"InsufficientResourcesAvailable","innerError":false}', ""),
])
@pytest.mark.parametrize("regional", [False, True])
def test_readback_denials_malformed_mixed_unknown_and_nonsearch_errors_are_terminal(runtime, outcome, regional):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast,italynorth"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    if regional:
        runtime.outcome = (19, "", "InsufficientResourcesAvailable")
        runtime.attempt()
    runtime.outcome = (19, "", json.dumps({"error": search_deployment_wrapper()}))
    runtime.group_errors["search-nested"] = outcome
    status, values, _ = runtime.attempt(regional=regional)
    assert status == 19 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert "aiSearchLocation" not in values and "skuAISearchDev" not in values
    assert len(runtime.parameters) == (2 if regional else 1)
    assert runtime.sleeps == ([240] if regional else [])
    assert sum(call[1:4] == ["deployment", "group", "show"] for call in runtime.calls) == 1


@pytest.mark.parametrize("levels,expected,reads", [(1, True, 1), (5, True, 5), (6, False, 5)])
def test_nested_error_readback_has_a_bounded_depth(runtime, runner, levels, expected, reads):
    for index in range(levels):
        error = search_deployment_wrapper(f"child-{index + 1}") if index + 1 < levels else {
            "code": "InsufficientResourcesAvailable"}
        runtime.group_errors[f"child-{index}"] = (0, json.dumps(error), "")
    resource = "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/search"
    assert runner.search_capacity_failure_with_readback(
        "offline-az", json.dumps({"error": search_deployment_wrapper("child-0")}), resource) is expected
    assert sum(call[1:4] == ["deployment", "group", "show"] for call in runtime.calls) == reads


def test_nested_error_readback_refuses_cycles(runtime, runner):
    wrapper = search_deployment_wrapper()
    runtime.group_errors["search-nested"] = (0, json.dumps(wrapper), "")
    assert not runner.search_capacity_failure_with_readback(
        "offline-az", json.dumps({"error": wrapper}),
        "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/search")
    assert sum(call[1:4] == ["deployment", "group", "show"] for call in runtime.calls) == 1


@pytest.mark.parametrize("count,expected,reads", [(10, True, 10), (11, False, 10)])
def test_nested_error_readback_has_a_total_read_budget(runtime, runner, count, expected, reads):
    for index in range(count):
        runtime.group_errors[f"child-{index}"] = (0, '{"code":"InsufficientResourcesAvailable"}', "")
    document = {"code": "DeploymentFailed", "details": [search_deployment_wrapper(f"child-{index}")
                                                      for index in range(count)]}
    assert runner.search_capacity_failure_with_readback(
        "offline-az", json.dumps(document),
        "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/search") is expected
    assert sum(call[1:4] == ["deployment", "group", "show"] for call in runtime.calls) == reads


@pytest.mark.parametrize("has_target", [False, True])
def test_wrapper_capacity_message_is_not_a_substitute_for_the_actual_error(runtime, has_target):
    wrapper = search_deployment_wrapper()
    wrapper["message"] = "InsufficientResourcesAvailable"
    if not has_target:
        wrapper.pop("target")
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast"
    runtime.outcome = (19, "", json.dumps({"error": wrapper}))
    runtime.group_errors["search-nested"] = (0, '{"code":"AuthorizationFailed"}', "")
    status, values, _ = runtime.attempt()
    assert status == 19 and values == {"AIF_AISEARCH_CAPACITY_NEXT": "failed"}
    assert sum(call[1:4] == ["deployment", "group", "show"] for call in runtime.calls) == int(has_target)


def test_resolved_capacity_on_an_existing_search_never_arms_regional_fallback(runtime, runner, monkeypatch):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    monkeypatch.setattr(runner, "read_search", lambda *args: {
        "location": "westeurope", "properties": {"provisioningState": "Succeeded"},
    })
    runtime.outcome = (19, "", json.dumps({"error": search_deployment_wrapper()}))
    runtime.group_errors["search-nested"] = (0, '{"code":"InsufficientResourcesAvailable"}', "")
    status, values, _ = runtime.attempt()
    assert status == 19 and values == {"AIF_AISEARCH_CAPACITY_NEXT": "failed"}
    assert len(runtime.parameters) == 1 and runtime.parameters[0]["aiSearchLocation"]["value"] == "westeurope"


@pytest.mark.parametrize("change", ["identity", "primary", "environment", "regions", "sku", "run", "missing", "malformed"])
def test_regional_pending_context_rejects_stale_or_changed_inputs(runtime, runner, monkeypatch, change):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast,italynorth"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    runtime.env["GITHUB_RUN_ID"] = "original-run"
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, values, _ = runtime.attempt()
    assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    if change == "identity":
        monkeypatch.setattr(runner, "search_identity", lambda *args: "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/changed")
    elif change == "primary":
        runtime.env["AISEARCHLOCATION"] = "northeurope"
    elif change == "environment":
        runtime.env["DEV_TEST_PROD"] = "prod"
        runtime.env["AISEARCHFALLBACKLOCATIONARRAYSTAGEPROD"] = "denmarkeast,italynorth"
    elif change == "regions":
        runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "italynorth,denmarkeast"
    elif change == "sku":
        runtime.env["SKUAISEARCHDEV"] = "basic"
    elif change == "run":
        runtime.env["GITHUB_RUN_ID"] = "new-run"
    elif change == "missing":
        runtime.env.pop("AIF_AISEARCH_PRIMARY_CONTEXT")
    else:
        runtime.env["AIF_AISEARCH_PRIMARY_CONTEXT"] = "{"
    with pytest.raises(ValueError):
        runtime.attempt(regional=True)
    assert len(runtime.parameters) == 1 and runtime.sleeps == []


@pytest.mark.parametrize("after_delay", [False, True])
@pytest.mark.parametrize("state", ["Succeeded", "Failed", "Creating", "Canceled"])
def test_pending_regional_refuses_any_existing_or_partially_bound_service(
        runtime, runner, monkeypatch, after_delay, state):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    runtime.attempt()
    bound = {"location": "swedencentral", "properties": {"provisioningState": state}}
    reads = iter([None, bound] if after_delay else [bound])
    monkeypatch.setattr(runner, "read_search", lambda *args: next(reads))
    with pytest.raises(ValueError, match="bound"):
        runtime.attempt(regional=True)
    assert len(runtime.parameters) == 1
    assert runtime.sleeps == ([240] if after_delay else [])


@pytest.mark.parametrize("retry", ["true", "false"])
def test_regional_primary_duplicate_is_excluded_without_reordering(runtime, retry):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast,swedencentral,italynorth"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = retry
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, values, _ = primary_attempts(runtime)
    assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    count = len(runtime.parameters)
    status, _, _ = runtime.attempt(regional=True)
    assert status == 19
    skus = SERVICES["ai-search"]["order"] if retry == "true" else ["standard"]
    assert [(p["aiSearchLocation"]["value"], p["skuAISearchDev"]["value"]) for p in runtime.parameters[count:]] == [
        (region, sku) for region in ("denmarkeast", "italynorth") for sku in skus
    ]


def test_primary_only_fallback_array_does_not_arm_a_regional_task(runtime):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = '["Sweden Central"]'
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, values, _ = runtime.attempt()
    assert status == 19 and values == {"AIF_AISEARCH_CAPACITY_NEXT": "failed"}


@pytest.mark.parametrize("regions", ["[]", "denmarkeast"])
@pytest.mark.parametrize("after_delay", [False, True])
def test_existing_primary_binding_must_not_disappear_or_change_between_tasks(
        runtime, runner, monkeypatch, regions, after_delay):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = regions
    bound = {"location": "westeurope", "properties": {"provisioningState": "Succeeded"}}
    monkeypatch.setattr(runner, "read_search", lambda *args: bound)
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, values, _ = runtime.attempt()
    assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "2"
    reads = iter([bound, None] if after_delay else [None])
    monkeypatch.setattr(runner, "read_search", lambda *args: next(reads))
    with pytest.raises(ValueError, match="binding changed|Previously bound"):
        runtime.attempt(attempt=2)
    assert len(runtime.parameters) == 1
    assert runtime.parameters[0]["aiSearchLocation"]["value"] == "westeurope"


@pytest.mark.parametrize("exists", ["true", "false"])
def test_original_aisearch_exists_flag_is_preserved_for_network_dns_and_cmk(runtime, exists):
    runtime.env["AISEARCHEXISTS"] = exists
    status, _, _ = runtime.attempt()
    assert status == 0
    assert runtime.parameters[-1]["aiSearchExists"]["value"] is (exists == "true")


@pytest.mark.parametrize("regions", ["[]", "denmarkeast"])
@pytest.mark.parametrize("state", ["Failed", "Canceled"])
def test_partial_primary_binding_allows_only_same_region_sku_updates(runtime, runner, monkeypatch, regions, state):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = regions
    bound = {"location": "swedencentral", "properties": {"provisioningState": state}}
    reads = iter([None, bound])
    monkeypatch.setattr(runner, "read_search", lambda *args: next(reads, bound))
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, values, _ = primary_attempts(runtime)
    assert status == 19 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert len(runtime.parameters) == 3 and runtime.sleeps == [240, 240]
    assert [p["skuAISearchDev"]["value"] for p in runtime.parameters] == SERVICES["ai-search"]["order"]
    assert all(p["aiSearchLocation"]["value"] == "swedencentral" for p in runtime.parameters)
    with pytest.raises(ValueError, match="not armed"):
        runtime.attempt(regional=True)


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


@pytest.mark.parametrize("value,expected", [
    ("", []), ("[]", []), ([], []),
    (" West Europe , North Europe ", ["westeurope", "northeurope"]),
    ('["East US 2","Sweden Central"]', ["eastus2", "swedencentral"]),
    (["West Europe"], ["westeurope"]),
    (SEARCH_FALLBACK_REGIONS[:4], SEARCH_FALLBACK_REGIONS[:4]),
    (SEARCH_FALLBACK_REGIONS, SEARCH_FALLBACK_REGIONS),
    (json.dumps(SEARCH_FALLBACK_REGIONS), SEARCH_FALLBACK_REGIONS),
    (",".join(SEARCH_FALLBACK_REGIONS), SEARCH_FALLBACK_REGIONS),
])
def test_search_region_normalization(runner, value, expected):
    assert runner.normalize_search_regions(value) == expected


@pytest.mark.parametrize("value", [
    None, {}, 1, True, "null", "false", '"eastus"', "[eastus]", '["eastus",1]',
    ["eastus", ""], "eastus,", "eastus,,westus", "eastus,EAST US",
    "$(region)", "${{ vars.REGION }}", "east-us", "eastus\nwestus",
    SEARCH_FALLBACK_REGIONS + ["eastus"],
    json.dumps(SEARCH_FALLBACK_REGIONS + ["eastus"]),
    ",".join(SEARCH_FALLBACK_REGIONS + ["eastus"]),
])
def test_search_region_normalization_rejects_unsafe_inputs(runner, value):
    with pytest.raises(ValueError):
        runner.normalize_search_regions(value)


@pytest.mark.parametrize("suffix", ["Dev", "StageProd"])
def test_sixth_search_fallback_is_rejected_before_azure(runtime, suffix):
    runtime.configure("ai-search", "dev" if suffix == "Dev" else "prod")
    runtime.env[("aiSearchFallbackLocationArray" + suffix).upper()] = json.dumps(
        SEARCH_FALLBACK_REGIONS + ["eastus"])
    with pytest.raises(ValueError, match="at most five"):
        runtime.attempt()
    assert runtime.calls == [] and runtime.sleeps == []


def test_search_region_candidates_are_region_major_and_independent_of_sku_switch(runner):
    assert runner.search_candidate_order("East US 2", '["eastus2","West Europe"]',
                                         "standard", "basic,standard,standard2", "true") == [
        ("westeurope", "standard"), ("westeurope", "basic"), ("westeurope", "standard2"),
    ]
    assert runner.search_candidate_order("eastus2", "westeurope", "standard", "unused", "false") == [
        ("westeurope", "standard"),
    ]
    assert runner.search_candidate_order("France Central", SEARCH_FALLBACK_REGIONS,
                                         "standard", "basic,standard,standard2", "true") == [
        (region, sku) for region in SEARCH_FALLBACK_REGIONS[1:]
        for sku in ["standard", "basic", "standard2"]
    ]


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_search_regional_driver_exhausts_primary_then_publishes_effective_location(
        runtime, runner, monkeypatch, provider, target, suffix):
    runtime.configure("ai-search", target)
    runtime.env[("aiSearchFallbackLocationArray" + suffix).upper()] = '["West Europe"]'
    monkeypatch.setattr(runner, "search_identity", lambda *args: "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/search")
    monkeypatch.setattr(runner, "read_search", lambda *args: None)
    original = runtime.azure
    def azure(command, **kwargs):
        if command[1:4] == ["deployment", "sub", "create"]:
            runtime.outcome = (9, "", '{"error":{"code":"InsufficientResourcesAvailable"}}') if len(runtime.parameters) < 3 else (0, "", "")
        return original(command, **kwargs)
    monkeypatch.setattr(runner.subprocess, "run", azure)
    primary_status, pending, _ = primary_attempts(runtime, provider)
    assert primary_status == 0 and pending["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    status, values, _ = runtime.attempt(provider=provider, regional=True)
    assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "0"
    assert values["aiSearchLocation"] == "westeurope"
    assert values["skuAISearch" + suffix] == "standard"
    assert [p["aiSearchLocation"]["value"] for p in runtime.parameters] == [
        "swedencentral", "swedencentral", "swedencentral", "westeurope",
    ]
    assert all(p["location"]["value"] == "swedencentral" for p in runtime.parameters)
    assert runtime.sleeps == [240, 240, 240]


@pytest.mark.parametrize("existing", [
    {"location": "West Europe", "properties": {"provisioningState": "succeeded"}},
    {"location": "West Europe", "properties": {"provisioningState": "failed"}},
])
def test_existing_search_is_never_relocated(runtime, runner, monkeypatch, existing):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "northeurope"
    monkeypatch.setattr(runner, "search_identity", lambda *args: "search-id")
    monkeypatch.setattr(runner, "read_search", lambda *args: existing)
    runtime.outcome = (9, "", "InsufficientResourcesAvailable")
    status, values, captured = primary_attempts(runtime)
    assert status == 9 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert len(runtime.parameters) == 3
    assert all(p["aiSearchLocation"]["value"] == "westeurope" for p in runtime.parameters)
    assert values["AIF_AISEARCH_CAPACITY_NEXT"] != "primary-capacity-exhausted"


def test_search_partial_creation_stops_before_relocation(runtime, runner, monkeypatch):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "westeurope"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    monkeypatch.setattr(runner, "search_identity", lambda *args: "search-id")
    reads = iter([None, {"location": "swedencentral", "properties": {"provisioningState": "failed"}}])
    monkeypatch.setattr(runner, "read_search", lambda *args: next(reads))
    runtime.outcome = (9, "", "InsufficientResourcesAvailable")
    status, values, captured = runtime.attempt()
    assert status == 9 and len(runtime.parameters) == 1 and runtime.sleeps == []
    assert values["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert "bound" in captured.err.lower()


@pytest.mark.parametrize("error,attempts", [
    ("InsufficientResourcesAvailable", 18),
    ("AuthorizationFailed\nInsufficientResourcesAvailable", 1),
    ('{"error":{"code":"UnexpectedError","details":[{"code":"InsufficientResourcesAvailable"}]}}', 1),
    ('{"error":{"details":[{"code":"InsufficientResourcesAvailable"},{"code":"QuotaExceeded"}]}}', 1),
    ('{"error":{"code":"InsufficientResourcesAvailable","target":"Microsoft.Network/privateEndpoints/pe"}}', 1),
])
@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_regional_search_exhaustion_and_terminal_failures_never_arm_legacy_steps(
        runtime, runner, monkeypatch, error, attempts, provider, target, suffix):
    runtime.configure("ai-search", target)
    runtime.env[("aiSearchFallbackLocationArray" + suffix).upper()] = json.dumps(SEARCH_FALLBACK_REGIONS)
    monkeypatch.setattr(runner, "search_identity", lambda *args: "search-id")
    monkeypatch.setattr(runner, "read_search", lambda *args: None)
    runtime.outcome = (19, "", error)
    status, values, captured = primary_attempts(runtime, provider)
    if status == 0:
        status, values, captured = runtime.attempt(provider=provider, regional=True)
    assert status == 19 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert len(runtime.parameters) == attempts and runtime.sleeps == [240] * (attempts - 1)
    expected = [(region, sku) for region in ["swedencentral", *SEARCH_FALLBACK_REGIONS]
                for sku in SERVICES["ai-search"]["order"]]
    assert [(p["aiSearchLocation"]["value"], p["skuAISearch" + suffix]["value"])
            for p in runtime.parameters] == expected[:attempts]
    assert all(p["location"]["value"] == "swedencentral" for p in runtime.parameters)
    if attempts == 18:
        assert "attempt 15/15" in captured.out
        assert "candidates exhausted" in captured.err


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
@pytest.mark.parametrize("regions", [None, "", " ", "[]"])
def test_missing_or_empty_search_regions_retain_legacy_sku_steps(runtime, provider, target, suffix, regions):
    runtime.configure("ai-search", target)
    key = ("aiSearchFallbackLocationArray" + suffix).upper()
    if regions is None:
        runtime.env.pop(key)
    else:
        runtime.env[key] = regions
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, values, _ = runtime.attempt(provider=provider)
    assert status == 0 and values == {"AIF_AISEARCH_CAPACITY_NEXT": "2"}
    assert len(runtime.parameters) == 1 and runtime.sleeps == []
    assert runtime.parameters[0]["aiSearchLocation"]["value"] == "swedencentral"


def test_region_only_search_ignores_malformed_sku_arrays(runtime, runner, monkeypatch):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = json.dumps(SEARCH_FALLBACK_REGIONS)
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    runtime.env["SKUARRAYAISEARCHDEV"] = "malformed,,,"
    monkeypatch.setattr(runner, "search_identity", lambda *args: "search-id")
    monkeypatch.setattr(runner, "read_search", lambda *args: None)
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, _, _ = primary_attempts(runtime)
    assert status == 0
    status, _, _ = runtime.attempt(regional=True)
    assert status == 19
    assert [(p["aiSearchLocation"]["value"], p["skuAISearchDev"]["value"]) for p in runtime.parameters] == [
        (region, "standard") for region in ["swedencentral", *SEARCH_FALLBACK_REGIONS]
    ]
    assert runtime.sleeps == [240] * 5


def test_delayed_search_name_binding_is_rechecked_after_retry_delay(runtime, runner, monkeypatch):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "westeurope"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = "false"
    monkeypatch.setattr(runner, "search_identity", lambda *args: "search-id")
    reads = iter([None, None, None, {
        "location": "swedencentral", "properties": {"provisioningState": "failed"},
    }])
    monkeypatch.setattr(runner, "read_search", lambda *args: next(reads))
    runtime.outcome = (19, "", "InsufficientResourcesAvailable")
    status, values, _ = runtime.attempt()
    assert status == 0 and values["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    with pytest.raises(ValueError, match="bound after retry delay"):
        runtime.attempt(regional=True)
    assert len(runtime.parameters) == 1 and runtime.sleeps == [240]


def test_private_endpoint_capacity_is_not_search_region_exhaustion(runner):
    error = json.dumps({"error": {"code": "DeploymentFailed", "details": [{
        "code": "InsufficientResourcesAvailable",
        "target": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/privateEndpoints/pe",
    }]}})
    assert not runner.is_search_capacity_failure(error, "search-id")
    assert runner.is_search_capacity_failure('{"error":{"code":"InsufficientResourcesAvailable"}}', "search-id")
    assert not runner.is_search_capacity_failure('{"error":{"details":[{"code":"InsufficientResourcesAvailable"},{"code":"QuotaExceeded"}]}}', "search-id")


def test_empty_regions_rerun_keeps_existing_actual_location(runtime, runner, monkeypatch):
    monkeypatch.setattr(runner, "read_search", lambda *args: {
        "location": "West Europe", "properties": {"provisioningState": "succeeded"},
    })
    _, values, _ = runtime.attempt()
    assert runtime.parameters[-1]["aiSearchLocation"]["value"] == "westeurope"
    assert values["aiSearchLocation"] == "westeurope"


@pytest.fixture
def exact_search_read(runtime, runner, monkeypatch):
    original = runtime.azure

    def configure(outcome):
        def azure(command, **kwargs):
            if command[1:4] == ["rest", "--method", "get"]:
                runtime.calls.append(command)
                assert command[command.index("--url") + 1] == (
                    "https://management.azure.com/subscriptions/unit-subscription/resourceGroups/rg/"
                    "providers/Microsoft.Search/searchServices/search?api-version=2025-05-01"
                )
                return subprocess.CompletedProcess(command, *outcome)
            return original(command, **kwargs)

        monkeypatch.setattr(runner.subprocess, "run", azure)

    return configure


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
@pytest.mark.parametrize("regions", ["", "[]", "northeurope"])
@pytest.mark.parametrize("retry", ["false", "true"])
def test_existing_region_pinning_keeps_explicit_scalar_sku_update(
        runtime, exact_search_read, provider, target, suffix, regions, retry):
    runtime.configure("ai-search", target)
    runtime.env[("skuAISearch" + suffix).upper()] = "standard2"
    runtime.env["AISEARCHRETRYCAPCITYARRAY"] = retry
    runtime.env[("skuArrayAISearch" + suffix).upper()] = (
        "basic,standard,standard2" if retry == "true" else "unused,,"
    )
    runtime.env[("aiSearchFallbackLocationArray" + suffix).upper()] = regions
    exact_search_read((0, json.dumps({
        "location": "West Europe", "sku": {"name": "standard"},
        "properties": {"provisioningState": "Succeeded"},
    }), ""))

    status, values, _ = runtime.attempt(provider=provider)

    assert status == 0 and len(runtime.parameters) == 1 and runtime.sleeps == []
    assert runtime.parameters[0]["skuAISearch" + suffix] == {"value": "standard2"}
    assert runtime.parameters[0]["aiSearchLocation"] == {"value": "westeurope"}
    assert runtime.parameters[0]["location"] == {"value": "swedencentral"}
    assert values["skuAISearch" + suffix] == "standard2"
    assert values["aiSearchLocation"] == "westeurope"
    assert values["AIF_AISEARCH_CAPACITY_NEXT"] == "0"
    assert not any("list" in command for command in runtime.calls)


@pytest.mark.parametrize("regions", ["[]", "northeurope"])
@pytest.mark.parametrize("code,status", [("ResourceNotFound", 404), ("AuthorizationFailed", 403)])
def test_exact_search_get_is_required_before_any_search_creation(
        runtime, exact_search_read, regions, code, status):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = regions
    exact_search_read((1, "", json.dumps({"error": {"code": code}, "status": status})))

    if status == 404:
        result, _, _ = runtime.attempt()
        assert result == 0 and len(runtime.parameters) == 1
    else:
        with pytest.raises(ValueError, match="Cannot read the named Search service"):
            runtime.attempt()
        assert runtime.parameters == [] and runtime.sleeps == []
    assert sum(command[1:4] == ["rest", "--method", "get"] for command in runtime.calls) == 1
    assert not any("list" in command for command in runtime.calls)


@pytest.mark.parametrize("error", [
    "AuthorizationFailed", "NotFound", "timeout", "(ResourceNotFound) AuthorizationFailed",
    '{"error":{"code":"UnexpectedError","details":[{"code":"ResourceNotFound"}]}}',
    '{"error":{"code":"ResourceNotFound"',
    '{"error":{"code":"ResourceNotFound"}} trailing text',
    '{"error":{"code":"ResourceNotFound"},"statusCode":403}',
    '{"error":{"code":"ResourceNotFound"},"statusCode":500}',
    '{"statusCode":404}', "HTTP 404 Not Found",
    "(ResourceNotFound) Missing.\nCode: AuthorizationFailed",
    "(ResourceNotFound) Missing.\nHTTP 500 Internal Server Error",
    "(ResourceNotFound) Missing. (UnexpectedError) Something else failed.",
    "(ResourceNotFound) Missing.\nUnexpected failure",
    "unrelated output\n(ResourceNotFound) Missing.",
    '{"error":{"code":"UnknownFailure","code":"ResourceNotFound"}}',
    '{"error":{"code":"ResourceNotFound"},"unexpected":NaN}',
    "(ResourceNotFound) Missing.\nHTTP nonsense",
    '{"metadata":{"code":"ResourceNotFound"}}',
    '{"error":[{"code":"ResourceNotFound"}]}',
    '{"error":{"code":"ResourceNotFound","message":[]}}',
    '{"error":{"code":"ResourceNotFound","details":"UnknownFailure"}}',
    '{"error":{"code":"ResourceNotFound","details":[{"message":"Unknown failure"}]}}',
])
def test_search_read_denial_is_not_absence(runtime, runner, monkeypatch, error):
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, "", error))
    with pytest.raises(ValueError, match="Cannot read"):
        runner.read_search("offline-az", "search-id")


@pytest.mark.parametrize("error", [
    '{"error":{"code":"ResourceNotFound"}}',
    'ERROR: {"error":{"code":"ResourceNotFound"},"statusCode":404}',
    "(ResourceNotFound) Missing.",
    "ERROR: (ResourceNotFound) Missing.\nCode: ResourceNotFound",
    # az rest wraps the ARM body in the HTTP reason (aif-138 first project deploy, 2026-10-30).
    'ERROR: Not Found({"error":{"code":"ResourceNotFound","message":"The Resource '
    "'Microsoft.Search/searchServices/aisearchprj001' under resource group 'rg' was not found. For more details "
    'please go to https://aka.ms/ARMResourceNotFoundFix"}})',
])
def test_search_read_accepts_only_complete_explicit_not_found(runner, monkeypatch, error):
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, "", error))
    assert runner.read_search("offline-az", "search-id") is None


@pytest.mark.parametrize("error", [
    '{"error":{"code":"InsufficientResourcesAvailable"',
    '{"error":{"code":"InsufficientResourcesAvailable"}}\nCode: UnknownFailure',
    '{"error":{"code":"InsufficientResourcesAvailable"}}\n(UnexpectedError) Failed',
    "InsufficientResourcesAvailable\nUnknownFailure",
    "InsufficientResourcesAvailable\nCode: UnknownFailure",
    '{"error":{"code":"UnknownFailure","code":"InsufficientResourcesAvailable"}}',
    '{"error":{"code":"InsufficientResourcesAvailable"},"unexpected":NaN}',
    '{"error":{"code":"InsufficientResourcesAvailable","details":[{"message":"Unknown failure"}]}}',
])
def test_malformed_or_mixed_primary_errors_do_not_arm_fallback(runtime, error):
    runtime.env["AISEARCHFALLBACKLOCATIONARRAYDEV"] = "denmarkeast"
    runtime.outcome = (19, "", error)
    status, values, _ = runtime.attempt()
    assert status == 19 and values == {"AIF_AISEARCH_CAPACITY_NEXT": "failed"}
    assert len(runtime.parameters) == 1 and runtime.sleeps == []


def test_private_foundry_search_dependency_is_not_disabled(runtime):
    runtime.env["ENABLEAISEARCH"] = "false"
    runtime.env["ENABLEAIFOUNDRY"] = "true"
    runtime.env["ENABLEPUBLICGENAIACCESS"] = "false"
    status, _, _ = runtime.attempt()
    assert status == 0 and len(runtime.parameters) == 1


def test_public_private_foundry_flags_reach_same_dependency_and_deployment(runtime):
    for canonical, public, value in [
        ("ENABLEAISEARCH", "ENABLE_AI_SEARCH", "false"),
        ("ENABLEAIFOUNDRY", "ENABLE_AI_FOUNDRY", "true"),
        ("ENABLEPUBLICGENAIACCESS", "ENABLE_PUBLIC_GENAI_ACCESS", "false"),
    ]:
        runtime.env.pop(canonical, None)
        runtime.env[public] = value
    status, _, _ = runtime.attempt()
    assert status == 0
    params = runtime.parameters[-1]
    assert params["enableAISearch"]["value"] is False
    assert params["enableAIFoundry"]["value"] is True
    assert params["enablePublicGenAIAccess"]["value"] is False


def expanded_steps(provider, service, include_search_routing=False):
    if provider == "github":
        return [
            step for step in objects(load_pipeline(GHA))
            if isinstance(step.get("run"), str)
            and (re.search(r"--service\s+" + re.escape(service) + r"\s", step["run"])
                 or (include_search_routing and service == "ai-search"
                     and "--publish-search-region-gate" in step["run"]))
            and "deploy-capacity-resource.py" in step.get("run", "")
            and (include_search_routing or "region-fallback" not in step.get("name", ""))
        ]
    includes = [
        step for step in load_pipeline(ADO_JOB)["steps"]
        if step.get("template") == ADO_ATTEMPTS.name and step["parameters"]["service"] == service
    ]
    assert len(includes) == 1
    parameters = includes[0]["parameters"]
    result = []
    templates = []
    for step in load_pipeline(ADO_ATTEMPTS)["steps"]:
        if "${{ if eq(parameters.service, 'ai-search') }}" in step:
            if service == "ai-search":
                templates.extend(step["${{ if eq(parameters.service, 'ai-search') }}"])
        else:
            templates.append(step)
    for step in templates:
        expanded = json.dumps(step)
        # Replace only CI template syntax, never Bash substitutions or $variables.
        expanded = re.sub(
            r"\$\{\{\s*parameters\.(\w+)\s*\}\}",
            lambda match: parameters[match[1]], expanded,
        )
        item = json.loads(expanded)
        if not include_search_routing and any(
                marker in item.get("displayName", "") for marker in ("region-fallback", "region-gate")):
            continue
        result.append(item)
    return result


def allowed(step, provider, env, phase="infra", success=True):
    context = {"success": success, "inputs.phase": phase, "parameters.phase": phase}
    context.update({f"env.{key}": value for key, value in env.items()})
    context.update({f"variables.{key}": value for key, value in env.items()})
    for spec in SERVICES.values():
        context.setdefault("env." + spec["state"], "")
        context.setdefault("variables." + spec["state"], "")
    context.setdefault("env.AIF_AISEARCH_REGION_FALLBACK_ENABLED", "false")
    context.setdefault("variables.AIF_AISEARCH_REGION_FALLBACK_ENABLED", "false")
    expression = step["if"] if provider == "github" else step["condition"]
    expression = re.sub(r"\$\{\{\s*parameters\.phase\s*\}\}", phase, expression)
    # GHA adds an implicit success() unless a status-check function is supplied.
    return success and bool(evaluate(expression, context))


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("state", ["", "0", "2", "3", "failed", "primary-capacity-exhausted"])
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
        if args[:3] == ["rest", "--method", "get"]:
            print("(ResourceNotFound) Not found", file=sys.stderr)
            sys.exit(1)
        record = {"argv": args}
        if args[:3] == ["deployment", "group", "show"]:
            assert args[args.index("--subscription") + 1] == "unit-subscription"
            assert args[args.index("--resource-group") + 1] == "rg"
            assert args[args.index("--query") + 1] == "properties.error"
            name = args[args.index("--name") + 1]
            record["error_read"] = name
            with (root / "az.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(record) + "\\n")
            errors = json.loads(os.environ.get("CAPACITY_TEST_GROUP_ERRORS", "{}"))
            if name not in errors:
                sys.exit(1)
            print(json.dumps(errors[name]))
            sys.exit(0)
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
        parameters = json.loads(path.read_text(encoding="utf-8"))["parameters"]
        if parameters.get("capacityIdentityOnly", {}).get("value"):
            print(json.dumps({"properties": {"outputs": {"aiSearchResourceId": {
                "value": "/subscriptions/unit-subscription/resourceGroups/rg/providers/Microsoft.Search/searchServices/search"
            }}}}))
            sys.exit(0)
        record["path"] = str(path)
        record["parameters"] = json.loads(path.read_text(encoding="utf-8"))["parameters"]
        with (root / "az.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(record) + "\\n")
        status = int(os.environ["CAPACITY_TEST_STATUS"])
        if os.environ.get("CAPACITY_TEST_SUCCEED_AT"):
            creates = [json.loads(line) for line in (root / "az.jsonl").read_text(encoding="utf-8").splitlines()
                       if "parameters" in json.loads(line)]
            status = 0 if len(creates) == int(os.environ["CAPACITY_TEST_SUCCEED_AT"]) else 29
            if len(creates) == int(os.environ.get("CAPACITY_TEST_TERMINAL_AT", "0")):
                print(os.environ.get("CAPACITY_TEST_TERMINAL_ERROR", "AuthorizationFailed"), file=sys.stderr)
                sys.exit(29)
        if status:
            print(os.environ.get("CAPACITY_TEST_ERROR", ""), file=sys.stderr)
        sys.exit(status)
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
            self.executed, self.skipped, self.preparations = [], [], []

        def execute(self, service, provider, target="dev", succeed_at=3, error="SkuNotAvailable",
                    overrides=None, remove=(), allow_msys_conversion=False):
            env = environment(service, target)
            env.update(overrides or {})
            for key in remove:
                env.pop(key)
            steps = expanded_steps(provider, service, include_search_routing=True)
            success = True
            for step in steps:
                name = step.get("name", step.get("displayName"))
                if not allowed(step, provider, env, success=success):
                    self.skipped.append(name)
                    continue
                self.executed.append(name)
                script = step["run"] if provider == "github" else step["inputs"].get("inlineScript", step["inputs"].get("script"))
                prepare = "--publish-search-region-gate" in script
                attempt_match = re.search(r"--attempt\s+(\d)", script)
                attempt = int(attempt_match[1]) if attempt_match else 0
                script = re.sub(r"\$\{\{\s*env\.(\w+)\s*\}\}", lambda m: env[m[1]], script)
                script = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)", lambda m: env[m[1]], script)
                assert "${{" not in script
                child_env = os.environ.copy()
                child_env.update({key.upper() if provider == "ado" else key: value for key, value in env.items()})
                child_env.update({
                    "CAPACITY_TEST_ROOT": str(workspace), "CAPACITY_TEST_STATUS": "0" if attempt == succeed_at else "29",
                    "CAPACITY_TEST_ERROR": error if env.get("CAPACITY_TEST_SUCCEED_AT") or attempt != succeed_at else "",
                    "GITHUB_ENV": str(workspace / "github-env"), "PYTHONIOENCODING": "utf-8",
                    "MSYS_NO_PATHCONV": "1",
                })
                if allow_msys_conversion:
                    for key in ("MSYS_NO_PATHCONV", "MSYS2_ENV_CONV_EXCL", "MSYS2_ARG_CONV_EXCL"):
                        child_env.pop(key, None)
                for key, value in step.get("env", {}).items():
                    if key.startswith("${{"):
                        if f"'{service}'" in key:
                            child_env.update({
                                name: re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_.]*)\)", lambda m: env[m[1]], raw)
                                for name, raw in value.items()
                            })
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
                values = publications(provider, result.stdout, github_env)
                if prepare:
                    self.preparations.append(result)
                else:
                    self.results.append(result)
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
@pytest.mark.parametrize("target,suffix,other", [
    ("dev", "Dev", "StageProd"), ("test", "StageProd", "Dev"), ("prod", "StageProd", "Dev"),
])
@pytest.mark.parametrize("value,enabled", [
    ("", False), ("[]", False), (" [ ] ", False), (None, False),
    ("francecentral,Denmark East", True),
    (json.dumps(SEARCH_FALLBACK_REGIONS), True),
])
def test_actual_ci_region_task_skip_and_enable_routing(
        script_harness, provider, target, suffix, other, value, enabled):
    key = "aiSearchFallbackLocationArray" + suffix
    overrides = {
        "aiSearchFallbackLocationArray" + other: json.dumps(SEARCH_FALLBACK_REGIONS),
        "aisearchRetryCapcityArray": "false",
    }
    if value is not None:
        overrides[key] = value
    final = script_harness.execute("ai-search", provider, target, succeed_at=1,
                                   overrides=overrides, remove=(key,) if value is None else ())
    assert len(script_harness.preparations) == 1
    assert script_harness.preparations[0].returncode == 0
    assert final["AIF_AISEARCH_REGION_FALLBACK_ENABLED"] == str(enabled).lower()
    assert not any("region-fallback" in name for name in script_harness.executed)
    assert any("region-fallback" in name for name in script_harness.skipped)
    assert any(name.endswith("attempt-1") for name in script_harness.executed)
    assert len(script_harness.results) == 1 and script_harness.results[0].returncode == 0
    assert len([record for record in script_harness.records() if "parameters" in record]) == 1


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("value", ["", "[]"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_actual_ci_empty_regions_skip_task_but_keep_all_sku_retries(
        script_harness, provider, value, target, suffix):
    final = script_harness.execute("ai-search", provider, target, succeed_at=3, overrides={
        "aiSearchFallbackLocationArray" + suffix: value,
    })
    assert final["AIF_AISEARCH_REGION_FALLBACK_ENABLED"] == "false"
    assert not any("region-fallback" in name for name in script_harness.executed)
    assert any("region-fallback" in name for name in script_harness.skipped)
    assert len(script_harness.results) == 3
    assert final["skuAISearch" + suffix] == "standard2"
    assert script_harness.sleep_values() == [240, 240]


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
@pytest.mark.parametrize("retry,primary_count", [("true", 3), ("false", 1)])
def test_extracted_primary_denmark_italy_are_separate_ordered_phases(
        script_harness, provider, target, suffix, retry, primary_count):
    final = script_harness.execute("ai-search", provider, target, overrides={
        "aiSearchFallbackLocationArray" + suffix: '["denmarkeast","swedencentral","italynorth"]',
        "aisearchRetryCapcityArray": retry,
        "CAPACITY_TEST_SUCCEED_AT": str(primary_count * 2 + 1),
    })
    assert len(script_harness.results) == primary_count + 1
    assert all(result.returncode == 0 for result in script_harness.results), [r.stderr for r in script_harness.results]
    assert script_harness.executed[-1].endswith("region-fallback")
    assert all("aiSearchLocation" not in values and "skuAISearch" + suffix not in values
               for values in script_harness.published[:-1])
    assert script_harness.published[-2]["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    assert final["aiSearchLocation"] == "italynorth" and final["skuAISearch" + suffix] == "standard"
    creates = [record["parameters"] for record in script_harness.records() if "parameters" in record]
    assert [p["aiSearchLocation"]["value"] for p in creates] == [
        *(["swedencentral"] * primary_count), *(["denmarkeast"] * primary_count), "italynorth",
    ]
    assert script_harness.sleep_values() == [240] * (primary_count * 2)
    assert all(p["env"]["value"] == target and p["location"]["value"] == "swedencentral" for p in creates)


@pytest.mark.parametrize("provider", ["ado", "github"])
def test_json_primary_context_survives_windows_bash_environment_conversion(script_harness, provider):
    if os.name != "nt":
        pytest.skip("Windows Git Bash required for environment-conversion regression")
    final = script_harness.execute(
        "ai-search", provider, allow_msys_conversion=True,
        overrides={"aiSearchFallbackLocationArrayDev": '["denmarkeast","italynorth"]',
                   "aisearchRetryCapcityArray": "false", "CAPACITY_TEST_SUCCEED_AT": "2"},
    )
    assert all(result.returncode == 0 for result in script_harness.results), [
        result.stderr for result in script_harness.results]
    context = json.loads(script_harness.published[0]["AIF_AISEARCH_PRIMARY_CONTEXT"])
    assert context["resourceId"] == "/subscriptions/unit-subscription/resourcegroups/rg/providers/microsoft.search/searchservices/search"
    assert final["aiSearchLocation"] == "denmarkeast"
    assert script_harness.executed[-1].endswith("region-fallback")


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("succeed_at", [1, 2, 3])
def test_extracted_primary_success_at_any_sku_skips_configured_fallback(script_harness, provider, succeed_at):
    final = script_harness.execute("ai-search", provider, succeed_at=succeed_at, overrides={
        "aiSearchFallbackLocationArrayDev": '["denmarkeast","italynorth"]',
    })
    assert len(script_harness.results) == succeed_at
    assert all(result.returncode == 0 for result in script_harness.results)
    assert any(name.endswith("region-fallback") for name in script_harness.skipped)
    assert not any(name.endswith("region-fallback") for name in script_harness.executed)
    assert final["AIF_AISEARCH_CAPACITY_NEXT"] == "0" and final["aiSearchLocation"] == "swedencentral"


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_extracted_cli_resolves_wrapper_only_errors_before_primary_to_fallback_transition(
        script_harness, provider, target, suffix):
    error = json.dumps({"error": {"code": "DeploymentFailed", "details": [search_deployment_wrapper()]}})
    final = script_harness.execute("ai-search", provider, target, error=error, overrides={
        "aiSearchFallbackLocationArray" + suffix: "denmarkeast,italynorth",
        "aisearchRetryCapcityArray": "false",
        "CAPACITY_TEST_SUCCEED_AT": "3",
        "CAPACITY_TEST_GROUP_ERRORS": '{"search-nested":{"code":"InsufficientResourcesAvailable"}}',
    })
    assert len(script_harness.results) == 2
    assert all(result.returncode == 0 for result in script_harness.results), [r.stderr for r in script_harness.results]
    assert script_harness.published[0]["AIF_AISEARCH_CAPACITY_NEXT"] == "primary-capacity-exhausted"
    assert "aiSearchLocation" not in script_harness.published[0]
    assert final["aiSearchLocation"] == "italynorth" and final["AIF_AISEARCH_CAPACITY_NEXT"] == "0"
    records = script_harness.records()
    assert [record["error_read"] for record in records if "error_read" in record] == ["search-nested"] * 2
    assert [record["parameters"]["aiSearchLocation"]["value"] for record in records if "parameters" in record] == [
        "swedencentral", "denmarkeast", "italynorth",
    ]
    assert script_harness.sleep_values() == [240, 240]


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("terminal_at", [1, 4])
@pytest.mark.parametrize("error", [
    "AuthorizationFailed", "InsufficientResourcesAvailable\nAuthorizationFailed",
    '{"error":{"code":"UnexpectedError","details":[{"code":"InsufficientResourcesAvailable"}]}}',
    '{"error":{"code":"InsufficientResourcesAvailable","target":"Microsoft.Network/privateEndpoints/pe"}}',
])
def test_extracted_primary_or_fallback_terminal_errors_stop_retries_and_downstream(
        script_harness, provider, terminal_at, error):
    final = script_harness.execute("ai-search", provider, overrides={
        "aiSearchFallbackLocationArrayDev": '["denmarkeast","italynorth"]',
        "CAPACITY_TEST_SUCCEED_AT": "99",
        "CAPACITY_TEST_TERMINAL_AT": str(terminal_at),
        "CAPACITY_TEST_TERMINAL_ERROR": error,
    })
    assert len(script_harness.results) == (1 if terminal_at == 1 else 4)
    assert script_harness.results[-1].returncode == 29
    assert final["AIF_AISEARCH_CAPACITY_NEXT"] == "failed"
    assert "aiSearchLocation" not in final
    creates = [record for record in script_harness.records() if "parameters" in record]
    assert len(creates) == terminal_at and script_harness.sleep_values() == [240] * (terminal_at - 1)
    pipeline = load_pipeline(GHA if provider == "github" else ADO_JOB)
    downstream = next(step for step in objects(pipeline)
                      if step.get("name", step.get("displayName")) == "64-databases")
    assert not allowed(downstream, provider, final, success=False)
    assert all("aiSearchLocation" not in values and "skuAISearchDev" not in values
               for values in script_harness.published)


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("gate", ["false", "true"])
@pytest.mark.parametrize("state", ["", "0", "2", "3", "failed", "primary-capacity-exhausted"])
def test_parsed_regional_condition_requires_both_nonempty_gate_and_primary_exhaustion(provider, gate, state):
    env = environment("ai-search")
    env.update({"AIF_AISEARCH_REGION_FALLBACK_ENABLED": gate, "AIF_AISEARCH_CAPACITY_NEXT": state})
    regional = expanded_steps(provider, "ai-search", include_search_routing=True)[-1]
    assert "region-fallback" in regional.get("name", regional.get("displayName"))
    assert allowed(regional, provider, env) is (gate == "true" and state == "primary-capacity-exhausted")
    assert "continueOnError" not in regional and "continue-on-error" not in regional


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("value", [
    json.dumps(SEARCH_FALLBACK_REGIONS + ["eastus"]), '["francecentral",1]', "$(region)",
])
def test_actual_ci_invalid_region_gate_blocks_all_provisioning(script_harness, provider, value):
    script_harness.execute("ai-search", provider, overrides={"aiSearchFallbackLocationArrayDev": value})
    assert len(script_harness.preparations) == 1 and script_harness.preparations[0].returncode == 2
    assert script_harness.results == [] and script_harness.records() == []
    assert "configuration error" in script_harness.preparations[0].stderr


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("cap_host,debug", [("false", "false"), ("true", "true")])
def test_region_tasks_keep_main_private_foundry_dependency_and_debug_exception(provider, cap_host, debug):
    env = environment("ai-search")
    env.update({
        "enableAISearch": "false", "enableAIFoundry": "true", "enablePublicGenAIAccess": "false",
        "enableAFoundryCaphost": cap_host, "debug_disable_63_cognitive_services": debug,
        "AIF_AISEARCH_REGION_FALLBACK_ENABLED": "true",
    })
    steps = expanded_steps(provider, "ai-search", include_search_routing=True)
    assert [allowed(step, provider, env) for step in steps] == [True, True, False, False, False]
    env["AIF_AISEARCH_CAPACITY_NEXT"] = "primary-capacity-exhausted"
    assert [allowed(step, provider, env) for step in steps] == [True, True, False, False, True]


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("blocked", ["disabled", "deleted", "phase", "debug", "failed"])
def test_search_regional_tasks_preserve_all_original_ci_gates(provider, blocked):
    env = environment("ai-search")
    env["AIF_AISEARCH_REGION_FALLBACK_ENABLED"] = "true"
    env["AIF_AISEARCH_CAPACITY_NEXT"] = "2"
    if blocked == "disabled":
        env["enableAISearch"] = "false"
    elif blocked == "deleted":
        env["deleteAllServicesForProject"] = "true"
    elif blocked == "debug":
        env["debug_disable_63_cognitive_services"] = "true"
    steps = expanded_steps(provider, "ai-search", include_search_routing=True)
    assert len(steps) == 5
    assert not any(allowed(step, provider, env, phase="apps" if blocked == "phase" else "infra",
                           success=blocked != "failed") for step in steps)


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
@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
def test_extracted_ci_search_primary_steps_then_fallback_complete_all_18_attempts(
        script_harness, provider, target, suffix):
    final = script_harness.execute("ai-search", provider, target, overrides={
        "aiSearchFallbackLocationArray" + suffix: json.dumps(SEARCH_FALLBACK_REGIONS),
        "CAPACITY_TEST_SUCCEED_AT": "18",
    })
    assert len(script_harness.results) == 4
    assert all(result.returncode == 0 for result in script_harness.results), [r.stderr for r in script_harness.results]
    assert [values["AIF_AISEARCH_CAPACITY_NEXT"] for values in script_harness.published] == [
        "2", "3", "primary-capacity-exhausted", "0",
    ]
    assert all("aiSearchLocation" not in values and "skuAISearch" + suffix not in values
               for values in script_harness.published[:3])
    assert final["AIF_AISEARCH_CAPACITY_NEXT"] == "0"
    assert final["aiSearchLocation"] == "germanywestcentral"
    assert final["skuAISearch" + suffix] == "standard2"
    creates = [record for record in script_harness.records() if "parameters" in record]
    assert [(record["parameters"]["aiSearchLocation"]["value"],
             record["parameters"]["skuAISearch" + suffix]["value"]) for record in creates] == [
        (region, sku) for region in ["swedencentral", *SEARCH_FALLBACK_REGIONS]
        for sku in SERVICES["ai-search"]["order"]
    ]
    assert all(record["argv"][record["argv"].index("--location") + 1] == "swedencentral" for record in creates)
    assert all(record["parameters"]["location"]["value"] == "swedencentral" for record in creates)
    assert "attempt 15/15" in script_harness.results[-1].stdout
    assert script_harness.sleep_values() == [240] * 17


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


@pytest.mark.parametrize("regions", [[], ["West Europe"]])
def test_actual_json_exporter_maps_public_capacity_aliases_and_preserves_tags(workspace, regions):
    public_retry = {
        "ai-search": "AISEARCH_RETRY_CAPCITY_ARRAY",
        "postgresql": "POSTGRESQL_RETRY_CAPACITY_ARRAY",
        "container-apps": "CONTAINER_APPS_RETRY_CAPACITY_ARRAY",
    }
    values = {"tagsProject": TAGS}
    expected = {"tagsProject": TAGS}
    for suffix, public in [("Dev", "DEV"), ("StageProd", "STAGEPROD")]:
        values["AI_SEARCH_FALLBACK_LOCATION_ARRAY_" + public] = regions
        expected["aiSearchFallbackLocationArray" + suffix] = regions
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
        assert (json.loads(exported[name]) if isinstance(value, (dict, list)) else exported[name]) == value
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


def test_compiled_search_identity_uses_explicit_subscription_and_resource_group(compiled):
    expression = compiled["03b-ai-search.bicep"]["outputs"]["aiSearchResourceId"]["value"]
    assert expression.startswith("[resourceId(")
    assert re.search(
        r"\.outputs\.context\.value\.subscriptionId, reference\(.*?"
        r"\.outputs\.context\.value\.targetResourceGroup, 'Microsoft.Search/searchServices', ",
        expression,
    )


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


def test_an_empty_search_location_falls_back_to_the_factory_location(runner):
    # The workflows always set aiSearchLocation (empty when unset): empty means "the factory location".
    environment = {"AISEARCHLOCATION": "", "AI_SEARCH_LOCATION": "", "ADMIN_LOCATION": "swedencentral"}
    assert runner.env_location(environment, "aiSearchLocation", "AI_SEARCH_LOCATION", "admin_location") == "swedencentral"
    assert runner.env_location({"AISEARCHLOCATION": "francecentral", "ADMIN_LOCATION": "swedencentral"},
                               "aiSearchLocation", "admin_location") == "francecentral"
    assert runner.env_location({"AISEARCHLOCATION": " "}, "aiSearchLocation") is None


def test_the_region_gate_publishes_with_an_empty_search_location(runner, monkeypatch):
    for name in list(os.environ):
        if name.upper() in ("AISEARCHLOCATION", "AI_SEARCH_LOCATION", "ADMIN_LOCATION", "LOCATION"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("dev_test_prod", "dev")
    monkeypatch.setenv("aiSearchLocation", "")
    monkeypatch.setenv("admin_location", "swedencentral")
    published = []
    monkeypatch.setattr(runner, "publish", lambda provider, name, value: published.append(name))
    monkeypatch.setattr(sys, "argv", ["deploy-capacity-resource.py", "--publish-search-region-gate", "--provider", "github"])
    assert runner.main() == 0
    assert "AIF_AISEARCH_REGION_FALLBACK_ENABLED" in published
