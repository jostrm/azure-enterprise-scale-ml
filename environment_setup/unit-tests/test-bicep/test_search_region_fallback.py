"""Offline release/v1.24 Search provisioning recovery contracts."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from unittest.mock import Mock
import uuid
from collections import defaultdict
from types import SimpleNamespace

import pytest
import yaml

REAL_RUN = subprocess.run
PROCESS_ENV = os.environ.copy()

ROOT = Path(__file__).resolve().parents[3]
BICEP = ROOT / "environment_setup/aifactory/bicep"
DEFAULT_FALLBACK_REGIONS = [
    "francecentral", "denmarkeast", "italynorth", "norwayeast", "germanywestcentral",
]
SERIALIZED_FALLBACK_REGIONS = json.dumps(DEFAULT_FALLBACK_REGIONS, separators=(",", ":"))
SPEC = importlib.util.spec_from_file_location(
    "search_region_fallback", BICEP / "scripts/search-region-fallback.py"
)
fallback = importlib.util.module_from_spec(SPEC)


@pytest.fixture(autouse=True)
def load_driver():
    SPEC.loader.exec_module(fallback)


@pytest.mark.parametrize("value", ["", "[]", []])
def test_empty_region_lists_disable_fallback(value):
    assert fallback.regions(value) == []


def test_regions_are_normalized_and_bounded():
    assert fallback.regions('["West Europe", "NorthEurope"]') == ["westeurope", "northeurope"]
    assert fallback.regions("West Europe, North Europe") == ["westeurope", "northeurope"]
    for value in ('["westeurope", "West Europe"]', "a,b,c,d", '["a", 1]', "$(unresolved)", "[bad]", "a,,b"):
        with pytest.raises(ValueError):
            fallback.regions(value)


@pytest.mark.parametrize("format_value", [lambda value: value, json.dumps, ",".join])
def test_five_fallback_regions_are_accepted_but_six_are_rejected(format_value):
    assert fallback.regions(format_value(DEFAULT_FALLBACK_REGIONS)) == DEFAULT_FALLBACK_REGIONS
    with pytest.raises(ValueError, match="at most 5"):
        fallback.regions(format_value([*DEFAULT_FALLBACK_REGIONS, "swedencentral"]))


def test_sku_input_limit_remains_three():
    assert fallback.skus('["standard", "basic", "standard2"]') == ["standard", "basic", "standard2"]
    with pytest.raises(ValueError, match="at most 3"):
        fallback.skus('["standard", "basic", "standard2", "standard3"]')


def test_candidate_builder_cannot_exceed_five_fallback_regions():
    with pytest.raises(ValueError, match="at most 5"):
        fallback.candidates("westeurope", "standard", ["basic", "standard2"], True,
                            [*DEFAULT_FALLBACK_REGIONS, "swedencentral"])


def test_candidate_order_and_independent_region_opt_in():
    assert fallback.candidates("swedencentral", "standard", ["basic", "standard2"], True,
                               ["swedencentral", "westeurope"]) == [
        (region, sku) for region in ("swedencentral", "westeurope")
        for sku in ("standard", "basic", "standard2")
    ]
    assert fallback.candidates("swedencentral", "standard", ["basic"], False,
                               ["westeurope"]) == [
        ("swedencentral", "standard"), ("westeurope", "standard")
    ]


def test_capacity_requires_exact_all_capacity_leaves():
    capacity = {"code": "InsufficientResourcesAvailable", "message": "capacity unavailable"}
    nested = {"code": "DeploymentFailed", "details": [
        {"code": "ResourceDeploymentFailure", "error": capacity}
    ]}
    assert fallback.is_capacity(nested)
    for other in ("AuthorizationFailed", "InvalidTemplate", "RequestDisallowedByPolicy",
                  "QuotaExceeded", "Unknown", "SkuNotAvailable"):
        assert not fallback.is_capacity({"code": "DeploymentFailed", "details": [capacity, {"code": other}]})
    assert not fallback.is_capacity({"code": "Unknown", "error": capacity})
    assert not fallback.is_capacity({"message": "InsufficientResourcesAvailable"})


def test_existing_service_stays_actual_region_and_sku():
    resource = {"name": "search", "location": "North Europe", "sku": {"name": "basic"},
                "properties": {"provisioningState": "Succeeded"}}
    assert fallback.existing_candidate(resource) == ("northeurope", "basic")
    resource["properties"]["provisioningState"] = "Failed"
    with pytest.raises(RuntimeError, match="Never delete"):
        fallback.existing_candidate(resource)


def test_bicep_isolates_only_search_creation_and_preserves_network_location():
    entry = (BICEP / "esml-genai-1/03b-ai-search.bicep").read_text(encoding="utf-8")
    search = (BICEP / "modules/aiSearch.bicep").read_text(encoding="utf-8")
    cognitive = (BICEP / "esml-genai-1/03-cognitive-services.bicep").read_text(encoding="utf-8")
    assert "serviceOnly: true" in entry
    assert "contextOnly" in entry
    assert "privateEndpointLocation: location" in cognitive
    assert "location: empty(aiSearchLocation) ? location : aiSearchLocation" in cognitive
    assert "location: privateEndpointLocation" in search
    assert "enableSharedPrivateLink && !serviceOnly" in search
    assert "resourceRegion: location" in cognitive
    assert "aiSearchExists || aiSearchProvisioned" in cognitive


@pytest.fixture(scope="module")
def compiled_search_template():
    executable = shutil.which("bicep")
    if executable is None:
        pytest.skip("Installed Bicep CLI required for compiled resource-identity checks")
    result = REAL_RUN(
        [executable, "build", str(BICEP / "esml-genai-1/03b-ai-search.bicep"), "--stdout", "--no-restore"],
        capture_output=True, text=True, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_compiled_search_identity_uses_explicit_subscription_and_resource_group(compiled_search_template):
    expression = compiled_search_template["outputs"]["aiSearchResourceId"]["value"]
    assert expression.startswith(
        "[resourceId(subscription().subscriptionId, variables('targetResourceGroup'), "
        "'Microsoft.Search/searchServices', "
    )
    assert not expression.startswith("[resourceId(variables('targetResourceGroup'),")


def test_compiled_search_user_assigned_identities_use_explicit_subscription_and_rg(compiled_search_template):
    search = next(resource for resource in compiled_search_template["resources"]
                  if "managedIdentities" in resource.get("properties", {}).get("parameters", {}))
    identities = search["properties"]["parameters"]["managedIdentities"]["value"]["userAssignedResourceIds"]
    assert identities.count(
        "resourceId(subscription().subscriptionId, variables('targetResourceGroup'), "
        "'Microsoft.ManagedIdentity/userAssignedIdentities', "
    ) == 2
    assert "resourceId(variables('targetResourceGroup')," not in identities


def test_templates_and_provider_execution_are_connected():
    config = json.loads((ROOT / "environment_setup/aifactory/variables.json").read_text(encoding="utf-8"))
    ado_root = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines"
    gha_root = BICEP / "copy_to_local_settings/github-actions"
    ado = (ado_root / "esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8")
    gha = (gha_root / "infra-project-phase.yml").read_text(encoding="utf-8")
    routing = (gha_root / "03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    for suffix, upper in (("Dev", "DEV"), ("StageProd", "STAGEPROD")):
        key = f"aiSearchFallbackLocationArray{suffix}"
        assert config["dev"][key] == DEFAULT_FALLBACK_REGIONS
        assert f"{key}: '{SERIALIZED_FALLBACK_REGIONS}'" in (ado_root / "variables/variables.yaml").read_text(encoding="utf-8")
        assert f"AI_SEARCH_FALLBACK_LOCATION_ARRAY_{upper}='{SERIALIZED_FALLBACK_REGIONS}'" in (gha_root / ".env.template").read_text(encoding="utf-8")
        assert f'"AI_SEARCH_FALLBACK_LOCATION_ARRAY_{upper}"' in routing
        assert key in ado and key in gha
        assert f"{key}: $[coalesce(variables['{key}'], '[]')]" in ado
        assert f"{key}: ${{{{ vars.AI_SEARCH_FALLBACK_LOCATION_ARRAY_{upper} || '[]' }}}}" in gha
    for workflow, template in ((ado, '--template-file "esml-genai-1/03-cognitive-services.bicep"'),
                               (gha, '03-cognitive-services.bicep"')):
        assert "search-region-fallback.py" in workflow
        assert "aiSearchProvisioned" in workflow
        assert workflow.index("search-region-fallback.py") < workflow.index(template)


def healthy(location="northeurope", sku="standard"):
    return {"location": location, "sku": {"name": sku},
            "properties": {"provisioningState": "Succeeded"}}


def test_recovery_capacity_then_success(monkeypatch):
    monkeypatch.setattr(fallback.time, "sleep", Mock())
    attempt = Mock(side_effect=[
        (False, {"code": "InsufficientResourcesAvailable"}), (True, None)
    ])
    lookup = Mock(side_effect=[None, None, healthy()])
    assert fallback.recover([("westeurope", "standard"), ("northeurope", "standard")],
                            None, attempt, lookup) == ("northeurope", "standard")
    assert attempt.call_count == 2


def test_exhaustion_and_partial_resource_block_downstream(monkeypatch):
    monkeypatch.setattr(fallback.time, "sleep", Mock())
    attempt = Mock(return_value=(False, {"code": "InsufficientResourcesAvailable"}))
    with pytest.raises(RuntimeError, match="exhausted"):
        fallback.recover([("westeurope", "standard")], None, attempt, lambda: None)
    with pytest.raises(RuntimeError, match="Never delete"):
        fallback.recover([("westeurope", "standard"), ("northeurope", "standard")],
                         None, attempt, lambda: healthy("westeurope"))
    assert attempt.call_count == 2


def test_read_error_is_never_absence():
    attempt = Mock(return_value=(False, {"code": "InsufficientResourcesAvailable"}))
    lookup = Mock(side_effect=RuntimeError("AuthorizationFailed"))
    with pytest.raises(RuntimeError, match="AuthorizationFailed"):
        fallback.recover([("westeurope", "standard"), ("northeurope", "standard")],
                         None, attempt, lookup)
    assert attempt.call_count == 1


def test_existing_service_pins_region_but_honors_requested_sku():
    attempt = Mock(return_value=(True, None))
    resource = healthy("northeurope", "basic")
    assert fallback.recover([("westeurope", "standard")], resource, attempt,
                            lambda: healthy("northeurope", "standard")) == ("northeurope", "standard")
    attempt.assert_called_once_with("northeurope", "standard", 0)


def test_existing_service_sku_candidates_never_enable_region_fallback(monkeypatch):
    monkeypatch.setattr(fallback.time, "sleep", Mock())
    attempt = Mock(side_effect=[
        (False, {"code": "InsufficientResourcesAvailable"}), (True, None)
    ])
    resource = healthy("northeurope", "standard")
    sequence = [
        ("westeurope", "standard2"), ("westeurope", "standard"),
        ("eastus2", "standard2"), ("eastus2", "standard"),
    ]
    assert fallback.recover(sequence, resource, attempt, lambda: resource) == ("northeurope", "standard")
    assert [call.args for call in attempt.call_args_list] == [
        ("northeurope", "standard2", 0), ("northeurope", "standard", 1)
    ]


def test_existing_service_capacity_failure_never_advances_region():
    attempt = Mock(return_value=(False, {"code": "InsufficientResourcesAvailable"}))
    resource = healthy("northeurope", "standard")
    with pytest.raises(RuntimeError, match="exhausted"):
        fallback.recover([("westeurope", "standard2"), ("eastus2", "standard2")],
                         resource, attempt, lambda: resource)
    attempt.assert_called_once_with("northeurope", "standard2", 0)


def test_existing_service_disappearing_never_authorizes_recreation():
    attempt = Mock(return_value=(False, {"code": "InsufficientResourcesAvailable"}))
    with pytest.raises(RuntimeError, match="refusing automatic recreation"):
        fallback.recover([("westeurope", "standard2"), ("eastus2", "standard2")],
                         healthy("northeurope", "standard"), attempt, lambda: None)
    attempt.assert_called_once_with("northeurope", "standard2", 0)


def test_all_eighteen_candidates_are_attempted_only_for_capacity(monkeypatch):
    monkeypatch.setattr(fallback.time, "sleep", Mock())
    sequence = fallback.candidates("westeurope", "standard", ["basic", "standard2"], True,
                                   fallback.regions(DEFAULT_FALLBACK_REGIONS))
    expected = [(location, sku) for location in ["westeurope", *DEFAULT_FALLBACK_REGIONS]
                for sku in ("standard", "basic", "standard2")]
    assert sequence == expected
    attempt = Mock(return_value=(False, {"code": "InsufficientResourcesAvailable"}))
    lookup = Mock(return_value=None)
    with pytest.raises(RuntimeError, match="exhausted"):
        fallback.recover(sequence, None, attempt, lookup)
    assert [call.args for call in attempt.call_args_list] == [
        (location, sku, index) for index, (location, sku) in enumerate(expected)
    ]
    assert attempt.call_count == 18
    assert lookup.call_count == 35
    assert [call.args for call in fallback.time.sleep.call_args_list] == [(5,)] * 17


def test_non_capacity_never_retries():
    attempt = Mock(return_value=(False, {"code": "DeploymentFailed", "details": [
        {"code": "InsufficientResourcesAvailable"}, {"code": "AuthorizationFailed"}
    ]}))
    with pytest.raises(RuntimeError, match="fatal"):
        fallback.recover([("westeurope", "standard"), ("northeurope", "standard")],
                         None, attempt, lambda: None)
    assert attempt.call_count == 1


def test_provisioning_publishes_only_internal_values(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    fallback.publish_provisioned("northeurope", "basic", existed=False)
    output = capsys.readouterr().out
    for key, value in (("AIF_AISEARCH_PROVISIONED_LOCATION", "northeurope"),
                       ("AIF_AISEARCH_PROVISIONED_SKU", "basic"), ("aiSearchProvisioned", "true"),
                       ("AIF_AISEARCH_STATE", "provisioned"), ("AIF_AISEARCH_READY", "false"),
                       ("AIF_AISEARCH_NETWORK_SUCCEEDED", "false"), ("aiSearchExists", "false")):
        assert f"variable={key}]{value}" in output
    for key in ("aiSearchLocation", "effectiveAiSearchLocation", "effectiveAiSearchSku",
                "skuAISearchDev", "skuAISearchStageProd"):
        assert f"variable={key}]" not in output


def test_exact_read_failure_never_indicates_absence(monkeypatch):
    monkeypatch.setattr(fallback, "az", Mock(side_effect=RuntimeError("AuthorizationFailed")))
    with pytest.raises(RuntimeError, match="AuthorizationFailed"):
        fallback.read_service("/subscriptions/sub/resourceGroups/project-rg/providers/Microsoft.Search/searchServices/search")


def test_primary_is_omitted_and_maximum_sku_total_is_validated():
    assert fallback.candidates("West Europe", "standard", [], False, ["westeurope", "northeurope"]) == [
        ("westeurope", "standard"), ("northeurope", "standard")
    ]
    with pytest.raises(ValueError, match="at most three"):
        fallback.candidates("westeurope", "standard", ["basic", "standard2", "standard3"], True, [])


def test_report_separates_same_sku_observed_in_different_regions(monkeypatch):
    report_spec = importlib.util.spec_from_file_location("release_region_report", BICEP / "scripts/region_report.py")
    reports = importlib.util.module_from_spec(report_spec)
    report_spec.loader.exec_module(reports)
    subscription = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setenv("AIFACTORY_REPORT_TENANT_ID", "22222222-2222-2222-2222-222222222222")
    monkeypatch.setenv("PF_REPORT_REGION", "westeurope")
    monkeypatch.setenv("PF_REPORT_TARGETS", f"dev|{subscription}")
    monkeypatch.setenv("PF_REPORT_FIELD_COUNT", "7")
    locations = ["westeurope", *DEFAULT_FALLBACK_REGIONS]
    raw = "\0".join(value for location in locations for value in (
        "dev", subscription, "FAIL" if location == "westeurope" else "PASS",
        "SEARCH_QUOTA_AT_LIMIT" if location == "westeurope" else "SEARCH_QUOTA_HEADROOM",
        "", "standard", location,
    )) + "\0"
    result = reports.preflight_reports(raw, True)
    assert {item["region"] for item in result} == set(locations)
    evidence = {item["region"]: next(o for o in item["observations"] if o["check_id"] == "search_sku_quota")
                for item in result}
    assert evidence["westeurope"]["status"] == "failed"
    assert all(evidence[location]["status"] == "passed" for location in DEFAULT_FALLBACK_REGIONS)


def preflight_functions():
    source = (BICEP / "scripts/preflight.sh").read_text(encoding="utf-8")
    functions = "\n".join(re.search(r"^" + name + r"\(\).*?^}", source, re.M | re.S).group()
                          for name in ("yaml_get", "dotenv_get", "getval", "check_search_candidates"))
    return functions + "\n" + re.search(r"^is_true\(\).*$", source, re.M).group()


@pytest.mark.parametrize("environment,expected", [("dev", "northeurope"), ("test", "eastus2"), ("prod", "eastus2")])
def test_preflight_uses_actual_candidate_regions_without_changing_project(environment, expected):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    executable = str(bash) if bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash is not installed")
    variables = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml"
    script = preflight_functions() + f"""
set -u
ENABLE_AI_SEARCH=true
LOCATION=westeurope
AI_SEARCH_TIER=basic
envname={environment}
PYBIN=python
ENV_FILE=''
VARS_YAML={shlex.quote(str(variables))}
SCRIPT_DIR={shlex.quote(str(BICEP / 'scripts'))}
printf 'YAML=%s\\n' "$(yaml_get aiSearchFallbackLocationArrayDev)"
export skuAISearchDev=standard
export skuAISearchStageProd=standard
export aiSearchFallbackLocationArrayDev='["North Europe"]'
export aiSearchFallbackLocationArrayStageProd='["eastus2"]'
export aisearchRetryCapcityArray=false
check_provider_region() {{ printf 'REGION=%s SKU=%s\\n' "$LOCATION" "$AI_SEARCH_TIER"; }}
check_ai_search_quota() {{ [ "$AI_SEARCH_TIER" = standard ] || printf 'ERROR=invalid-SKU\\n'; printf 'QUOTA=%s SKU=%s\\n' "$LOCATION" "$AI_SEARCH_TIER"; }}
add_finding() {{ printf 'ERROR=%s\\n' "$*"; }}
check_search_candidates offline
printf 'PROJECT=%s\\n' "$LOCATION"
"""
    result = subprocess.run([executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "ERROR=" not in result.stdout, result.stdout
    assert f"YAML={SERIALIZED_FALLBACK_REGIONS}" in result.stdout
    assert f"REGION={expected} SKU=standard" in result.stdout
    assert f"QUOTA={expected} SKU=standard" in result.stdout
    assert "PROJECT=westeurope" in result.stdout


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
@pytest.mark.parametrize("override", [None, "", "[]", "six"])
def test_preflight_five_region_defaults_bounds_and_explicit_empty(provider, environment, override):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    executable = str(bash) if bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash is not installed")
    templates = BICEP / "copy_to_local_settings"
    variables = templates / "azure-devops/esml-yaml-pipelines/variables/variables.yaml"
    dotenv = templates / "github-actions/.env.template"
    suffix, upper = ("Dev", "DEV") if environment == "dev" else ("StageProd", "STAGEPROD")
    name = f"aiSearchFallbackLocationArray{suffix}" if provider == "ado" else f"AI_SEARCH_FALLBACK_LOCATION_ARRAY_{upper}"
    value = json.dumps([*DEFAULT_FALLBACK_REGIONS, "swedencentral"]) if override == "six" else override
    script = preflight_functions() + f"""
set -uo pipefail
ENABLE_AI_SEARCH=true
LOCATION=westeurope
AI_SEARCH_TIER=basic
envname={environment}
PYBIN=python
VARS_YAML={shlex.quote(str(variables) if provider == 'ado' else '')}
ENV_FILE={shlex.quote(str(dotenv) if provider == 'github' else '')}
SCRIPT_DIR={shlex.quote(str(BICEP / 'scripts'))}
export skuAISearch{suffix}=standard2
export skuAISearch{suffix}Array='["basic","standard"]'
export aisearchRetryCapcityArray=true
{f'export {name}={shlex.quote(value)}' if value is not None else ''}
check_provider_region() {{ printf 'REGION=%s SKU=%s\\n' "$LOCATION" "$AI_SEARCH_TIER"; }}
check_ai_search_quota() {{ printf 'QUOTA=%s SKU=%s\\n' "$LOCATION" "$AI_SEARCH_TIER"; }}
add_finding() {{ printf 'ERROR=%s\\n' "$*"; }}
check_search_candidates offline
printf 'PROJECT=%s\\n' "$LOCATION"
"""
    result = REAL_RUN([executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    if override == "six":
        assert "SEARCH_CANDIDATES_INVALID" in result.stdout
        assert "five unique fallback regions" in result.stdout
        assert "18 combinations maximum" in result.stdout
        assert "REGION=" not in result.stdout and "QUOTA=" not in result.stdout
    else:
        assert "ERROR=" not in result.stdout, result.stdout
        locations = ["westeurope", *DEFAULT_FALLBACK_REGIONS] if override is None else ["westeurope"]
        expected = [(location, sku) for location in locations for sku in ("standard2", "basic", "standard")]
        assert re.findall(r"REGION=(\w+) SKU=(\w+)", result.stdout) == expected
        assert re.findall(r"QUOTA=(\w+) SKU=(\w+)", result.stdout) == expected
    assert "PROJECT=westeurope" in result.stdout


SEARCH_ID = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/project-rg/providers/Microsoft.Search/searchServices/search"


@pytest.fixture
def main_cli(monkeypatch):
    """Exercise real main(), parameter files, az(), recovery and CI publication offline."""
    work = ROOT / ".test-state" / f"search-main-{uuid.uuid4().hex}"
    work.mkdir(parents=True)
    network = work / "network.json"
    network.write_text('{"parameters":{}}', encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--network-parameters", str(network)])
    env = {
        "admin_location": "westeurope", "project_number_000": "001",
        "enableAISearch": "true", "aisearchRetryCapcityArray": "false",
        "aiSearchFallbackLocationArrayDev": "[]", "aiSearchFallbackLocationArrayStageProd": "[]",
        "skuAISearchDevArray": "[]", "skuAISearchStageProdArray": "[]",
        "skuAISearchDev": "standard2", "skuAISearchStageProd": "standard2",
    }
    monkeypatch.setattr(fallback.os, "environ", env)
    monkeypatch.setattr(fallback.time, "sleep", Mock())
    state = {"resource": healthy("northeurope", "standard"), "reads": [], "attempts": [], "list_calls": 0,
             "read_error": None, "capacity_failure": False}

    def command(arguments, **_kwargs):
        args = arguments[1:]
        result = lambda payload=None, code=0, error="": subprocess.CompletedProcess(
            arguments, code, stdout=json.dumps(payload), stderr=error)
        if args[:3] == ["deployment", "sub", "create"]:
            if "contextOnly=true" in args:
                return result({"properties": {"outputs": {
                    "targetResourceGroup": {"value": "project-rg"}, "aiSearchName": {"value": "search"},
                    "aiSearchResourceId": {"value": SEARCH_ID},
                }}})
            location = next(item.split("=", 1)[1] for item in args if item.startswith("aiSearchLocation="))
            sku = next(item.split("=", 1)[1] for item in args if item.startswith("skuAISearch"))
            state["attempts"].append((location, sku))
            if state["capacity_failure"] or state.get("failures_remaining", 0):
                state["failures_remaining"] = max(0, state.get("failures_remaining", 0) - 1)
                if not state.get("leave_unbound"):
                    state["resource"] = healthy(location, sku)
                    state["resource"]["properties"]["provisioningState"] = "Failed"
                return result(code=1, error="Search capacity allocation failed")
            state["resource"] = healthy(location, sku)
            return result({})
        if args[:3] == ["deployment", "sub", "show"]:
            return result({"code": "InsufficientResourcesAvailable"})
        if args[:2] == ["resource", "list"]:
            state["list_calls"] += 1
            return result([])  # Deliberately stale; must never establish absence.
        if args[:2] == ["resource", "show"]:
            state["reads"].append(args[args.index("--ids") + 1])
            if state["read_error"]:
                return result(code=1, error=state["read_error"])
            if state["resource"] is None:
                return result(code=1, error="ERROR: (ResourceNotFound) Expected Search service does not exist.")
            return result(state["resource"])
        raise AssertionError(f"Unexpected Azure CLI command: {args}")

    monkeypatch.setattr(fallback.subprocess, "run", command)
    yield env, state
    monkeypatch.chdir(ROOT)
    shutil.rmtree(work)


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
@pytest.mark.parametrize("value", [None, "", "[]", "   "])
def test_main_missing_or_empty_region_lists_still_disable_fallback(main_cli, monkeypatch, environment, value, capsys):
    env, state = main_cli
    env["dev_test_prod"] = environment
    key = f"aiSearchFallbackLocationArray{'Dev' if environment == 'dev' else 'StageProd'}"
    if value is None:
        env.pop(key)
    else:
        env[key] = value
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--plan"])
    fallback.main()
    assert json.loads(capsys.readouterr().out) == [["westeurope", "standard2"]]
    assert state["attempts"] == state["reads"] == []


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
@pytest.mark.parametrize("setting,expected", [(None, "normal"), ("", "normal"), ("[]", "normal"),
                                              (" [ ] ", "normal"), (SERIALIZED_FALLBACK_REGIONS, "regional")])
def test_mode_selection_is_local_and_runtime_missing_never_uses_template_defaults(
        main_cli, monkeypatch, capsys, environment, setting, expected):
    env, state = main_cli
    env["dev_test_prod"] = environment
    key = f"aiSearchFallbackLocationArray{'Dev' if environment == 'dev' else 'StageProd'}"
    if setting is None:
        env.pop(key)
    else:
        env[key] = setting
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--select-mode"])
    fallback.main()
    values = ado_values(capsys.readouterr().out)
    assert values["AIF_AISEARCH_MODE"] == expected
    assert values["AIF_AISEARCH_STATE"] == "pending"
    assert values["aiSearchProvisioned"] == values["AIF_AISEARCH_READY"] == "false"
    assert values["AIF_AISEARCH_NETWORK_SUCCEEDED"] == "false"
    assert not set(values) & {"aiSearchLocation", "effectiveAiSearchLocation", "effectiveAiSearchSku", "aiSearchExists"}
    assert state["reads"] == state["attempts"] == []


@pytest.mark.parametrize("mode,setting", [("normal", SERIALIZED_FALLBACK_REGIONS), ("regional", ""), ("regional", "[]")])
def test_explicit_provisioning_task_mode_cannot_run_the_wrong_path(main_cli, monkeypatch, mode, setting):
    env, state = main_cli
    env["aiSearchFallbackLocationArrayDev"] = setting
    monkeypatch.setattr(fallback.sys, "argv", [
        *fallback.sys.argv, "--provisioning-mode", mode,
    ])
    with pytest.raises(ValueError, match="mode"):
        fallback.main()
    assert state["reads"] == state["attempts"] == []


@pytest.mark.parametrize("source", ["yaml", "dotenv", "missing"])
def test_preflight_empty_file_values_and_missing_settings_remain_disabled(main_cli, source):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    executable = str(bash) if bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash is not installed")
    variables = Path.cwd() / "variables.yaml"
    variables.write_text("variables:\n  aiSearchFallbackLocationArrayDev: ''\n", encoding="utf-8")
    dotenv = Path.cwd() / "settings.env"
    dotenv.write_text("AI_SEARCH_FALLBACK_LOCATION_ARRAY_DEV=''\n", encoding="utf-8")
    default_dotenv = BICEP / "copy_to_local_settings/github-actions/.env.template"
    script = preflight_functions() + f"""
set -eu
VARS_YAML={shlex.quote(str(variables) if source == 'yaml' else '')}
ENV_FILE={shlex.quote(str(default_dotenv if source == 'yaml' else dotenv) if source != 'missing' else '')}
value="$(getval aiSearchFallbackLocationArrayDev AI_SEARCH_FALLBACK_LOCATION_ARRAY_DEV '[]' preserve-empty)"
printf 'VALUE=%s\\n' "$value"
"""
    result = REAL_RUN([executable, "-c", script], cwd=ROOT, env=PROCESS_ENV, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("VALUE=[]" if source == "missing" else "VALUE=")


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_main_existing_service_updates_explicit_sku_in_actual_region(main_cli, environment, capsys):
    env, state = main_cli
    env["dev_test_prod"] = environment
    fallback.main()
    assert state["attempts"] == [("northeurope", "standard2")]
    assert state["reads"] == [SEARCH_ID, SEARCH_ID]
    assert state["list_calls"] == 0
    suffix = "Dev" if environment == "dev" else "StageProd"
    output = capsys.readouterr().out
    assert "variable=AIF_AISEARCH_PROVISIONED_LOCATION]northeurope" in output
    assert "variable=AIF_AISEARCH_PROVISIONED_SKU]standard2" in output
    assert f"variable=skuAISearch{suffix}]" not in output
    assert "variable=effectiveAiSearchSku]" not in output


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_main_exact_get_resource_not_found_permits_creation(main_cli, environment, capsys):
    env, state = main_cli
    env["dev_test_prod"] = environment
    state["resource"] = None
    fallback.main()
    assert state["attempts"] == [("westeurope", "standard2")]
    assert state["reads"] == [SEARCH_ID, SEARCH_ID]
    assert state["list_calls"] == 0
    assert "variable=aiSearchExists]false" in capsys.readouterr().out


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_main_denied_exact_get_does_not_create_despite_empty_collection(main_cli, environment, capsys):
    env, state = main_cli
    env["dev_test_prod"] = environment
    state["read_error"] = "ERROR: (AuthorizationFailed) Access denied."
    with pytest.raises(RuntimeError, match="AuthorizationFailed"):
        fallback.main()
    assert state["attempts"] == []
    assert state["reads"] == [SEARCH_ID]
    assert state["list_calls"] == 0
    assert "variable=aiSearchProvisioned]" not in capsys.readouterr().out


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_main_existing_partial_service_blocks_update_with_empty_arrays(main_cli, environment, capsys):
    env, state = main_cli
    env["dev_test_prod"] = environment
    state["resource"]["properties"]["provisioningState"] = "Failed"
    with pytest.raises(RuntimeError, match="Never delete"):
        fallback.main()
    assert state["attempts"] == []
    assert state["reads"] == [SEARCH_ID]
    assert state["list_calls"] == 0
    assert "variable=aiSearchProvisioned]" not in capsys.readouterr().out


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_main_partial_service_blocks_regional_retry_despite_empty_collection(main_cli, environment, capsys):
    env, state = main_cli
    env["dev_test_prod"] = environment
    env["aiSearchFallbackLocationArrayDev"] = '["northeurope"]'
    env["aiSearchFallbackLocationArrayStageProd"] = '["northeurope"]'
    state["resource"] = None
    state["capacity_failure"] = True
    with pytest.raises(RuntimeError, match="Never delete"):
        fallback.main()
    assert state["attempts"] == [("westeurope", "standard2")]
    assert state["reads"] == [SEARCH_ID, SEARCH_ID]
    assert state["list_calls"] == 0
    assert "variable=aiSearchProvisioned]" not in capsys.readouterr().out


@pytest.mark.parametrize("message,absent", [
    ('{"error":{"code":"ResourceNotFound"}}', True),
    ('{"statusCode":404}', False),
    ('ERROR: {"error":{"code":"ResourceNotFound"},"statusCode":404}', True),
    ('{"error":{"code":"ResourceNotFound"', False),
    ('{"error":{"code":"ResourceNotFound"}} trailing text', False),
    ('{"error":{"code":"ResourceNotFound","details":[{"code":"AuthorizationFailed"}]}}', False),
    ('{"error":{"code":"ResourceNotFound"},"statusCode":403}', False),
    ('{"error":{"code":"ResourceNotFound"},"statusCode":500}', False),
    ("HTTP 404 Not Found", False),
    ("ERROR: (ResourceNotFound) Missing.\nCode: ResourceNotFound", True),
    ("ERROR: (ResourceNotFound) Missing.\nCode: AuthorizationFailed", False),
    ("ERROR: (ResourceNotFound) Missing.\nHTTP 500 Internal Server Error", False),
    ("ERROR: (AuthorizationFailed) Access denied; upstream returned HTTP 404.", False),
    ("ERROR: (ResourceGroupNotFound) Resource group missing.", False),
    ("ERROR: (TooManyRequests) Retry later.", False),
    ("Failed request: status unavailable.", False),
])
def test_only_explicit_exact_get_not_found_is_absence(monkeypatch, message, absent):
    response = subprocess.CompletedProcess(["az"], 1, stdout="", stderr=message)
    command = Mock(return_value=response)
    monkeypatch.setattr(fallback.subprocess, "run", command)
    if absent:
        assert fallback.read_service(SEARCH_ID) is None
    else:
        with pytest.raises(RuntimeError):
            fallback.read_service(SEARCH_ID)
    arguments = command.call_args.args[0]
    assert arguments[1:3] == ["resource", "show"]
    assert arguments[arguments.index("--ids") + 1] == SEARCH_ID


def registration_helper(name, value, defined=True, selected=""):
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    executable = str(bash) if bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash is not installed")
    source = (BICEP / "copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    helper = re.search(r"(?ms)^create_or_update_repo_variable\(\) \{.*?^}", source).group()
    setup = f"{name}={shlex.quote(value)}" if defined else f"unset {name}"
    script = f"""
set -u
single_param_name={shlex.quote(selected)}
GITHUB_NEW_REPO='owner/repo'
YELLOW=''
NC=''
gh() {{ printf 'GH_CALL'; printf '|%s' "$@"; printf '\\n'; }}
{helper}
{setup}
create_or_update_repo_variable {shlex.quote(name)} {shlex.quote(value)}
"""
    # Execute only the extracted helper with a shell-function gh stub, never the registration script.
    result = subprocess.run([executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("name", [
    "AI_SEARCH_FALLBACK_LOCATION_ARRAY_DEV",
    "AI_SEARCH_FALLBACK_LOCATION_ARRAY_STAGEPROD",
])
@pytest.mark.parametrize("defined,value,expected", [
    (True, "", "[]"),
    (True, "[]", "[]"),
    (False, "", None),
    (True, '["westeurope","northeurope"]', '["westeurope","northeurope"]'),
    (True, SERIALIZED_FALLBACK_REGIONS, SERIALIZED_FALLBACK_REGIONS),
])
def test_registration_clears_only_explicit_empty_region_fields(name, defined, value, expected):
    output = registration_helper(name, value, defined=defined)
    if expected is None:
        assert "GH_CALL" not in output
    else:
        assert f"GH_CALL|variable|set|{name}|--repo|owner/repo|--body|{expected}\n" in output


@pytest.mark.parametrize("name", ["UNRELATED_EMPTY", "AI_SEARCH_LOCATION", "SKU_AISEARCH_DEV_ARRAY"])
def test_registration_preserves_unrelated_empty_skip(name):
    assert "GH_CALL" not in registration_helper(name, "")


def test_registration_preserves_single_parameter_filter_for_empty_region():
    assert "GH_CALL" not in registration_helper("AI_SEARCH_FALLBACK_LOCATION_ARRAY_DEV", "", selected="OTHER")


@pytest.mark.parametrize("change", ["late-binding", "denial", "existing-missing", "existing-region", "existing-failed"])
def test_retry_rechecks_identity_after_sleep_before_any_next_attempt(monkeypatch, change):
    original = healthy("northeurope", "standard") if change.startswith("existing-") else None
    state = {"resource": original}
    attempt = Mock(return_value=(False, {"code": "InsufficientResourcesAvailable"}))

    def lookup():
        if state["resource"] == "denied":
            raise RuntimeError("AuthorizationFailed")
        return state["resource"]

    def sleep(delay):
        assert delay == 5
        if change == "late-binding":
            state["resource"] = healthy("westeurope", "standard2")
        elif change == "denial":
            state["resource"] = "denied"
        elif change == "existing-missing":
            state["resource"] = None
        elif change == "existing-region":
            state["resource"] = healthy("eastus2", "standard")
        else:
            state["resource"] = healthy("northeurope", "standard")
            state["resource"]["properties"]["provisioningState"] = "Failed"

    monkeypatch.setattr(fallback.time, "sleep", sleep)
    with pytest.raises(RuntimeError):
        fallback.recover([("westeurope", "standard2"), ("westeurope", "standard"), ("eastus2", "standard2")],
                         original, attempt, lookup)
    assert attempt.call_count == 1


@pytest.mark.parametrize("change", ["healthy-binding", "failed-binding", "denial"])
def test_main_rechecks_same_exact_id_after_delay_and_stops(main_cli, monkeypatch, change):
    env, state = main_cli
    env["dev_test_prod"] = "dev"
    env["aiSearchFallbackLocationArrayDev"] = '["northeurope"]'
    state.update(resource=None, capacity_failure=True, leave_unbound=True)

    def sleep(delay):
        assert delay == 5
        if change == "denial":
            state["read_error"] = "ERROR: (AuthorizationFailed) Access denied."
        else:
            state["resource"] = healthy()
            if change == "failed-binding":
                state["resource"]["properties"]["provisioningState"] = "Failed"

    monkeypatch.setattr(fallback.time, "sleep", sleep)
    with pytest.raises(RuntimeError, match="bound|Exact Search resource GET failed"):
        fallback.main()
    assert state["attempts"] == [("westeurope", "standard2")]
    assert state["reads"] == [SEARCH_ID] * 3


def ado_values(output):
    return dict(re.findall(r"(?m)^##vso\[task\.setvariable variable=([^\]]+)\](.*)$", output))


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_finalize_cli_requires_no_network_file_or_azure_and_publishes_ready(main_cli, environment, monkeypatch, capsys):
    env, state = main_cli
    env.update(dev_test_prod=environment, AIF_AISEARCH_STATE="provisioned", aiSearchProvisioned="true",
               AIF_AISEARCH_NETWORK_SUCCEEDED="true", AIF_AISEARCH_PROVISIONED_LOCATION="North Europe",
               AIF_AISEARCH_PROVISIONED_SKU="standard2")
    env.pop("admin_location")
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--finalize"])
    fallback.main()
    values = ado_values(capsys.readouterr().out)
    assert values["aiSearchLocation"] == values["effectiveAiSearchLocation"] == "northeurope"
    assert values["effectiveAiSearchSku"] == "standard2"
    selected = "skuAISearchDev" if environment == "dev" else "skuAISearchStageProd"
    unselected = "skuAISearchStageProd" if environment == "dev" else "skuAISearchDev"
    assert values[selected] == "standard2"
    assert unselected not in values
    assert values["AIF_AISEARCH_STATE"] == "ready"
    assert values["AIF_AISEARCH_READY"] == "true"
    assert state["attempts"] == state["reads"] == []


@pytest.mark.parametrize("override", [
    {"AIF_AISEARCH_STATE": "disabled"}, {"AIF_AISEARCH_NETWORK_SUCCEEDED": "false"},
    {"aiSearchProvisioned": "false"}, {"AIF_AISEARCH_PROVISIONED_SKU": "$(unresolved)"},
    {"AIF_AISEARCH_PROVISIONED_LOCATION": "$(unresolved)"},
])
def test_finalize_refuses_incomplete_or_invalid_provisional_state(main_cli, monkeypatch, override, capsys):
    env, _ = main_cli
    env.update(dev_test_prod="dev", AIF_AISEARCH_STATE="provisioned", aiSearchProvisioned="true",
               AIF_AISEARCH_NETWORK_SUCCEEDED="true", AIF_AISEARCH_PROVISIONED_LOCATION="northeurope",
               AIF_AISEARCH_PROVISIONED_SKU="standard2")
    env.update(override)
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--finalize"])
    with pytest.raises(ValueError):
        fallback.main()
    assert "variable=aiSearchLocation]" not in capsys.readouterr().out


def test_network_file_required_only_for_actual_provisioning(main_cli, monkeypatch, capsys):
    env, state = main_cli
    env["dev_test_prod"] = "dev"
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--plan"])
    fallback.main()
    assert json.loads(capsys.readouterr().out) == [["westeurope", "standard2"]]
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py"])
    with pytest.raises(SystemExit) as error:
        fallback.main()
    assert error.value.code == 2
    assert state["attempts"] == state["reads"] == []


class Attributes(dict):
    def __getattr__(self, name):
        return self.get(name, "")


def step_enabled(step, provider, env, outcomes, successful):
    expression = step["condition" if provider == "ado" else "if"]
    if provider == "ado":
        expression = expression.replace("${{ parameters.phase }}", "infra")
        for before, after in (("and(", "AND("), ("or(", "OR("), ("in(", "IN(")):
            expression = expression.replace(before, after)
        scope = {"variables": defaultdict(str, env), "AND": lambda *v: all(v), "OR": lambda *v: any(v),
                 "IN": lambda value, *options: value in options, "eq": lambda a, b: a == b,
                 "ne": lambda a, b: a != b, "succeeded": lambda: successful}
    else:
        expression = expression.replace("&&", " and ").replace("||", " or ")
        scope = {"env": Attributes(env), "inputs": SimpleNamespace(phase="infra"),
                 "steps": Attributes({key: SimpleNamespace(outcome=value) for key, value in outcomes.items()}),
                 "success": lambda: successful}
        if not successful and "success()" not in expression:
            return False  # GitHub's implicit success() for ordinary step conditions.
    return bool(eval(expression, {"__builtins__": {}}, scope))


def provider_steps(provider):
    if provider == "ado":
        path = BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml"
        steps = yaml.safe_load(path.read_text(encoding="utf-8"))["steps"]
        key = "displayName"
    else:
        path = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
        steps = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["deploy-project"]["steps"]
        key = "name"
    return [next(step for step in steps if step.get(key) == name)
            for name in ("63a-search-mode", "63a-search-provisioning", "63a-search-regional-fallback",
                         "63-cognitive-services", "63b-search-ready", "64-databases")]


def provider_fallback_default(provider, environment):
    templates = BICEP / "copy_to_local_settings"
    if provider == "ado":
        variables = yaml.safe_load((templates / "azure-devops/esml-yaml-pipelines/variables/variables.yaml").read_text(encoding="utf-8"))["variables"]
        return variables[f"aiSearchFallbackLocationArray{'Dev' if environment == 'dev' else 'StageProd'}"]
    source = (templates / "github-actions/.env.template").read_text(encoding="utf-8")
    name = f"AI_SEARCH_FALLBACK_LOCATION_ARRAY_{'DEV' if environment == 'dev' else 'STAGEPROD'}"
    return re.search(rf"(?m)^{name}='([^']*)'", source).group(1)


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
@pytest.mark.parametrize("setting", [None, "", "[]", SERIALIZED_FALLBACK_REGIONS])
def test_ado_optional_bindings_preserve_legacy_missing_settings(
        main_cli, monkeypatch, capsys, environment, setting):
    env, state = main_cli
    env["dev_test_prod"] = environment
    optional = {
        "aiSearchLocation": ("admin_location", None),
        "aiSearchFallbackLocationArrayDev": (None, "[]"),
        "aiSearchFallbackLocationArrayStageProd": (None, "[]"),
        "skuAISearchDevArray": (None, "[]"),
        "skuAISearchStageProdArray": (None, "[]"),
        "aisearchRetryCapcityArray": (None, "false"),
    }
    settings = {key: value for key, value in env.items() if key not in optional}
    selected = f"aiSearchFallbackLocationArray{'Dev' if environment == 'dev' else 'StageProd'}"
    if setting is not None:
        settings[selected] = setting
    for step in provider_steps("ado")[:3]:
        bound = settings.copy()
        for key, (fallback_key, literal) in optional.items():
            fallback_expression = f"variables['{fallback_key}']" if fallback_key else f"'{literal}'"
            assert step["env"][key] == f"$[coalesce(variables['{key}'], {fallback_expression})]"
            bound[key] = settings.get(key) or (settings[fallback_key] if fallback_key else literal)
        monkeypatch.setattr(fallback.os, "environ", bound)
        monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--select-mode"])
        fallback.main()
        values = ado_values(capsys.readouterr().out)
        assert values["AIF_AISEARCH_MODE"] == ("regional" if setting == SERIALIZED_FALLBACK_REGIONS else "normal")
        assert state["reads"] == state["attempts"] == []


@pytest.mark.parametrize("provider", ["ado", "github"])
@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
@pytest.mark.parametrize("regional_setting", ["", "[]", SERIALIZED_FALLBACK_REGIONS])
@pytest.mark.parametrize("scenario", ["provision-failed", "exhausted", "network-failed", "network-skipped", "no-search", "auto-search", "ready"])
def test_provider_split_lifecycle_executes_network_script_and_only_finalizes_full_success(
        main_cli, monkeypatch, capsys, provider, environment, scenario, regional_setting):
    env, state = main_cli
    env.update(dev_test_prod=environment, deleteAllServicesForProject="false",
               debug_disable_63_cognitive_services="false", enableAFoundryCaphost="false",
               enableAIFoundry="false", aiSearchLocation="westeurope", PrjDepl="")
    # The unselected environment SKU must remain its source value.
    unselected = "skuAISearchStageProd" if environment == "dev" else "skuAISearchDev"
    env[unselected] = "basic"
    suffix = "Dev" if environment == "dev" else "StageProd"
    env[f"aiSearchFallbackLocationArray{suffix}"] = regional_setting
    # The other environment's region opt-in must never affect this environment's task gate.
    env[f"aiSearchFallbackLocationArray{'StageProd' if environment == 'dev' else 'Dev'}"] = (
        "[]" if regional_setting else SERIALIZED_FALLBACK_REGIONS)
    if scenario == "no-search":
        env["enableAISearch"] = "false"
    if scenario == "auto-search":
        env.update(enableAISearch="false", enableAFoundryCaphost="true", enableAIFoundry="true",
                   debug_disable_63_cognitive_services="true")
    if scenario == "provision-failed":
        state["read_error"] = "ERROR: (AuthorizationFailed) Access denied."
    if scenario in {"exhausted", "ready"}:
        attempt_count = 18 if regional_setting == SERIALIZED_FALLBACK_REGIONS else 3
        state.update(resource=None, capacity_failure=scenario == "exhausted", leave_unbound=True,
                     failures_remaining=attempt_count - 1 if scenario == "ready" else 0)
        env[f"skuAISearch{suffix}Array"] = '["basic","standard"]'
        env["aisearchRetryCapcityArray"] = "true"
    selector, normal, regional, network, finalizer, downstream = provider_steps(provider)
    outcomes = {name: "skipped" for name in (
        "search_mode_63a", "search_provisioning_63a", "search_regional_fallback_63a", "cognitive_services_63")}
    assert step_enabled(selector, provider, env, outcomes, True)
    original_args = fallback.sys.argv[:]
    monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--select-mode"])
    fallback.main()
    env.update(ado_values(capsys.readouterr().out))
    outcomes["search_mode_63a"] = "success"
    is_regional = regional_setting == SERIALIZED_FALLBACK_REGIONS
    assert step_enabled(normal, provider, env, outcomes, True) == (scenario != "no-search" and not is_regional)
    assert step_enabled(regional, provider, env, outcomes, True) == (scenario != "no-search" and is_regional)
    provision = regional if is_regional else normal
    provision_id = "search_regional_fallback_63a" if is_regional else "search_provisioning_63a"
    mode = "regional" if is_regional else "normal"
    command = provision.get("run", provision.get("inputs", {}).get("inlineScript", ""))
    assert f"--provisioning-mode {mode}" in command
    monkeypatch.setattr(fallback.sys, "argv", [*original_args, "--provisioning-mode", mode])
    successful = True
    try:
        if scenario != "no-search":
            fallback.main()
            outcomes[provision_id] = "success"
    except RuntimeError:
        assert scenario in {"provision-failed", "exhausted"}
        successful = False
        outcomes[provision_id] = "failure"
    provisional = ado_values(capsys.readouterr().out)
    assert not set(provisional) & {"aiSearchLocation", "effectiveAiSearchLocation", "effectiveAiSearchSku",
                                   "skuAISearchDev", "skuAISearchStageProd"}
    env.update(provisional)
    assert env["aiSearchLocation"] == env["admin_location"] == "westeurope"
    if scenario == "no-search":
        assert state["reads"] == state["attempts"] == []
        assert env["AIF_AISEARCH_STATE"] == "disabled"
        assert "aiSearchExists" not in provisional  # Keep original DNS/CMK discovery.
    if scenario == "network-skipped":
        env["debug_disable_63_cognitive_services"] = "true"
    network_ran = step_enabled(network, provider, env, outcomes, successful)
    assert network_ran == (scenario not in {"provision-failed", "exhausted", "network-skipped"})
    expected_location = ("germanywestcentral" if is_regional else "westeurope") if scenario == "ready" else "northeurope"
    expected_sku = "standard" if scenario == "ready" else "standard2"
    if scenario in {"exhausted", "ready"}:
        assert state["attempts"] == [
            (location, sku) for location in ["westeurope", *(DEFAULT_FALLBACK_REGIONS if is_regional else [])]
            for sku in ("standard2", "basic", "standard")
        ]
        assert state["reads"] == [SEARCH_ID] * (attempt_count * 2)
        assert [call.args for call in fallback.time.sleep.call_args_list] == [(5,)] * (attempt_count - 1)
        if scenario == "ready":
            assert env["aiSearchExists"] == "false"
            assert env["AIF_AISEARCH_READY"] == "false"
    if network_ran:
        bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        executable = str(bash) if bash.is_file() else shutil.which("bash")
        if not executable:
            pytest.skip("Bash is not installed")
        script = network["inputs"]["inlineScript"] if provider == "ado" else network["run"]
        if provider == "ado":
            script = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", lambda m: env.get(m[1], ""), script)
        else:
            script = re.sub(r"\$\{\{\s*env\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", lambda m: env.get(m[1], ""), script)
            script = re.sub(r"\$\{\{.*?\}\}", "Standard_LRS", script)
        stub = """
az() {
  if [ "$1 $2" = 'account set' ]; then return 0; fi
  printf 'AZ_ARG:%s\\n' "$@"
  return "$NETWORK_RESULT"
}
"""
        result = REAL_RUN([executable, "-c", stub + script], cwd=ROOT,
                          env=PROCESS_ENV | env | {"NETWORK_RESULT": "9" if scenario == "network-failed" else "0"},
                          capture_output=True, text=True, timeout=30)
        assert result.returncode == (9 if scenario == "network-failed" else 0), result.stderr
        arguments = re.findall(r"(?m)^AZ_ARG:(.*)$", result.stdout)
        assert arguments[arguments.index("--location") + 1] == "westeurope"
        assert "location=westeurope" in arguments
        assert f"aiSearchLocation={'westeurope' if scenario == 'no-search' else expected_location}" in arguments
        selected = "skuAISearchDev" if environment == "dev" else "skuAISearchStageProd"
        assert f"{selected}={expected_sku}" in arguments
        assert f"{unselected}=basic" in arguments
        if scenario == "ready":
            assert "aiSearchExists=false" in arguments
            assert "aiSearchProvisioned=true" in arguments
        env.update(ado_values(result.stdout))
        successful = result.returncode == 0
        outcomes["cognitive_services_63"] = "success" if successful else "failure"
    finalize = step_enabled(finalizer, provider, env, outcomes, successful)
    assert finalize == (scenario in {"ready", "auto-search"})
    if finalize:
        command = finalizer.get("run", finalizer.get("inputs", {}).get("arguments", ""))
        assert "--finalize" in command and "--network-parameters" not in command
        if provider == "github":
            assert finalizer["env"]["AIF_AISEARCH_NETWORK_SUCCEEDED"] == "${{ steps.cognitive_services_63.outcome == 'success' }}"
            env["AIF_AISEARCH_NETWORK_SUCCEEDED"] = "true"
            env["GITHUB_ENV"] = str(Path.cwd() / "github-ready.env")
        monkeypatch.setattr(fallback.sys, "argv", ["search-region-fallback.py", "--finalize"])
        fallback.main()
        if provider == "github":
            final_values = dict(line.split("=", 1) for line in Path(env["GITHUB_ENV"]).read_text(encoding="utf-8").splitlines())
        else:
            final_values = ado_values(capsys.readouterr().out)
        assert final_values["aiSearchLocation"] == final_values["effectiveAiSearchLocation"] == expected_location
        assert final_values["effectiveAiSearchSku"] == expected_sku
        assert final_values[selected] == expected_sku and unselected not in final_values
        assert final_values["AIF_AISEARCH_READY"] == "true"
        assert final_values["AIF_AISEARCH_STATE"] == "ready"
    else:
        assert env.get("AIF_AISEARCH_READY") != "true"
    assert step_enabled(downstream, provider, env, outcomes, successful) == (
        scenario not in {"provision-failed", "exhausted", "network-failed"})
