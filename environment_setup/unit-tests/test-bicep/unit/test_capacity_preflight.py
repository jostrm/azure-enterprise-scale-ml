"""Offline capacity preflight contracts; no authentication or Azure commands."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts"
PREFLIGHT = SCRIPTS / "preflight.sh"
HELPER = SCRIPTS / "ai-search-capacity-retry.sh"
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"


def bash_executable():
    executable = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    if not executable.is_file():
        executable = Path(shutil.which("bash") or "/unavailable")
    if not executable.is_file():
        pytest.skip("Bash is required for offline shell contracts")
    return str(executable)


def helper_run(command):
    return subprocess.run(
        [bash_executable(), "--noprofile", "--norc", "-c",
         f"set -eu; source {shlex.quote(HELPER.as_posix())}; {command}"],
        capture_output=True, text=True, timeout=15, check=False, cwd=ROOT,
    )


@pytest.mark.parametrize("command,expected", [
    ('aif_ai_search_candidate_order " STANDARD " " BASIC , Standard , standard2 " " TRUE "', ["standard", "basic", "standard2"]),
    ('aif_ai_search_candidate_order basic basic true', ["basic"]),
    ('aif_ai_search_candidate_order standard "unused,," " FALSE "', ["standard"]),
    ('aif_capacity_candidate_order Standard_D2s_v3 "Standard_B1ms,standard_d2s_v3,Standard_E2s_v3" true PostgreSQL',
     ["standard_d2s_v3", "standard_b1ms", "standard_e2s_v3"]),
    ('aif_capacity_candidate_order D4 "Consumption,d4,D8" yes "Container Apps"', ["d4", "consumption", "d8"]),
])
def test_candidate_order_is_selected_first_casefolded_and_errexit_safe(command, expected):
    result = helper_run(command)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == expected


@pytest.mark.parametrize("selected,configured,retry", [
    ("standard", "", "true"),
    ("standard", "basic,standard,", "true"),
    ("standard", "basic,standard, ", "true"),
    ("standard", ",standard", "true"),
    ("standard", "basic,,standard", "true"),
    ("standard", "basic,standard,standard2,standard3", "true"),
    ("standard", "basic,STANDARD, standard ", "true"),
    ("standard", "basic,standard2", "true"),
    ("standard", "basic,stand ard", "true"),
    ("standard", "basic\nstandard", "true"),
    ("", "basic,standard", "false"),
    ("stand ard", "unused", "false"),
    ("standard", "standard", "maybe"),
    ("standard", "standard", ""),
])
def test_candidate_order_rejects_malformed_values(selected, configured, retry):
    result = helper_run("aif_ai_search_candidate_order " + " ".join(
        shlex.quote(value) for value in (selected, configured, retry)
    ))
    assert result.returncode == 2, result.stdout + result.stderr


def usage(skus=("basic", "standard", "standard2")):
    return {"value": [
        {"name": {"value": sku}, "limit": 3, "currentValue": 0} for sku in skus
    ]}


def parse_search(monkeypatch, capsys, payload):
    source = PREFLIGHT.read_text(encoding="utf-8")
    code = source.split("az_jq_search() {", 1)[1].split("<<'PY'", 1)[1].split("\n", 1)[1].split("\nPY\n", 1)[0]
    monkeypatch.setenv("PF_JSON", payload if isinstance(payload, str) else json.dumps(payload))
    monkeypatch.setattr(sys, "argv", ["preflight", "basic"])
    exec(compile(code, str(PREFLIGHT), "exec"), {})
    return capsys.readouterr().out.strip()


@pytest.mark.parametrize("field,value", [
    ("limit", None), ("currentValue", None),
    ("limit", True), ("currentValue", False),
    ("limit", -1), ("currentValue", -1),
    ("limit", "8"), ("currentValue", "0"),
    ("limit", "8x"), ("currentValue", "unknown"),
    ("limit", 1.5), ("currentValue", 0.5),
    ("limit", float("nan")), ("currentValue", float("inf")),
    ("limit", 2**63), ("currentValue", 2**63),
])
def test_search_parser_rejects_invalid_quota_numbers(monkeypatch, capsys, field, value):
    payload = usage(("basic",))
    payload["value"][0][field] = value
    assert parse_search(monkeypatch, capsys, payload) == "INVALID INVALID false"


@pytest.mark.parametrize("field", ["limit", "currentValue"])
def test_search_parser_requires_both_quota_fields(monkeypatch, capsys, field):
    payload = usage(("basic",))
    del payload["value"][0][field]
    assert parse_search(monkeypatch, capsys, payload) == "INVALID INVALID false"


@pytest.mark.parametrize("payload", [
    "not-json", "null", "[]", "{}", '{"value":null}', '{"value":{}}',
    '{"value":[null]}', '{"value":[{"name":null}]}',
    '{"value":[{"name":{"value":4}}]}',
    usage(("basic", "BASIC")),
])
def test_search_parser_rejects_malformed_or_ambiguous_catalogues(monkeypatch, capsys, payload):
    assert parse_search(monkeypatch, capsys, payload) == "INVALID INVALID false"


@pytest.mark.parametrize("payload,expected", [
    (usage(("basic",)), "3 0 true"),
    ({"value": [{"name": {"value": "BASIC"}, "limit": 3.0, "currentValue": 1.0}]}, "3 1 true"),
    (usage(("standard",)), "MISSING MISSING true"),
    ({"value": []}, "MISSING MISSING true"),
])
def test_search_parser_distinguishes_valid_unlisted_and_quota_values(monkeypatch, capsys, payload, expected):
    assert parse_search(monkeypatch, capsys, payload) == expected


MOCK_AZ = r'''
# Shell equivalents avoid repeatedly launching Windows executables for env reads.
printenv() {
  [[ -v "${1:-}" ]] || return 1
  printf '%s\n' "${!1}"
}
command() {
  if [[ "${MOCK_AZ_MISSING:-false}" == true && "${1:-}" == -v && "${2:-}" == az ]]; then
    return 1
  fi
  builtin command "$@"
}
az() {
  printf 'MOCK_AZ:%s\n' "$*" >&2
  case "$1 $2" in
    "account show") return "${MOCK_ACCOUNT_STATUS:-0}" ;;
    "account set") return "${MOCK_SELECT_STATUS:-0}" ;;
    "policy assignment") printf '[]' ;;
    "provider show")
      if [[ "$*" == *registrationState* ]]; then
        printf 'Registered'
      else
        printf '%s' '{"registrationState":"Registered","resourceTypes":[{"resourceType":"searchServices","locations":["East US 2"]},{"resourceType":"flexibleServers","locations":["East US 2"]},{"resourceType":"managedEnvironments","locations":["East US 2"]}]}'
      fi
      ;;
    "rest --method")
      [[ "$*" == *Microsoft.Search/locations/*/usages* ]] || return 99
      printf '%s' "${MOCK_SEARCH_USAGE:-}"
      return "${MOCK_SEARCH_STATUS:-0}"
      ;;
    *) return 99 ;;
  esac
}
'''

# Override only the CLI capture transport (avoids filesystem scratch/error files).
# Quota parsing, settings resolution, main loop, exit policy and EXIT report hook
# are the actual preflight implementation.
MOCK_CAPTURE = r'''
az_capture() {
  AZ_OUT=""
  AZ_TRANSIENT=""
  if AZ_OUT="$(az "$@")"; then
    return 0
  fi
  [[ "${MOCK_TRANSIENT:-false}" != true ]] || AZ_TRANSIENT=1
  return 1
}
'''


@pytest.fixture
def offline_preflight():
    workspace = ROOT / f".capacity-preflight-test-{uuid4().hex}"
    workspace.mkdir()
    source = PREFLIGHT.read_text(encoding="utf-8")
    source = source.replace(
        'PYBIN="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"',
        "PYBIN=" + shlex.quote(Path(sys.executable).as_posix()) +
        '\n[[ "${MOCK_PYTHON_MISSING:-false}" != true ]] || PYBIN=""',
    )
    marker = '# 8. Run checks per target subscription'
    assert marker in source
    source = source.replace(marker, MOCK_CAPTURE + "\n" + marker, 1)
    script = workspace / "preflight.sh"
    script.write_text(MOCK_AZ + "\n" + source, encoding="utf-8")
    shutil.copyfile(HELPER, workspace / HELPER.name)
    shutil.copyfile(SCRIPTS / "deploy-capacity-resource.py", workspace / "deploy-capacity-resource.py")
    shutil.copyfile(SCRIPTS / "region_report.py", workspace / "region_report.py")

    def run(settings=None, *, arguments=(), environment="dev", subscription=SUBSCRIPTION,
            reports=False, yaml_settings=None, env_settings=None, capacity_helper=True):
        env = os.environ.copy()
        for names in re.findall(r"\b(?:getval|get_capacity_value) ([A-Za-z0-9_]+) ([A-Za-z0-9_]+)", source):
            for name in names:
                env.pop(name, None)
                env.pop(name.upper(), None)
        for name in list(env):
            if name.startswith(("PREFLIGHT_", "MOCK_", "LZ_PREFLIGHT_", "AIFACTORY_REPORT_")):
                env.pop(name)
        for name in ("dev_test_prod", "dev_test_prod_sub_id", "TF_BUILD", "GITHUB_ACTIONS"):
            env.pop(name, None)
        env.update({
            "enableAISearch": "true", "enableAIFoundry": "false",
            "enableAzureOpenAI": "false", "enableCosmosDB": "false",
            "enableElasticsearch": "false", "enablePostgreSQL": "false",
            "enableContainerApps": "false", "enablePublicGenAIAccess": "true",
            "aifactory_common_only_dev_environment": "true",
            "PREFLIGHT_WARN_ONLY": "true", "MOCK_SEARCH_USAGE": json.dumps(usage()),
        })
        env.update(settings or {})
        if reports:
            env.update({"PREFLIGHT_REPORT_DIR": str(workspace / "reports"), "TENANT_ID": TENANT})
        args = ["--root", workspace.as_posix(), "--warn-only"]
        if yaml_settings is not None:
            path = workspace / "variables.yaml"
            path.write_text(yaml_settings, encoding="utf-8")
            args += ["--variables-yaml", path.as_posix()]
        if env_settings is not None:
            path = workspace / "settings.env"
            path.write_text(env_settings, encoding="utf-8")
            args += ["--env-file", path.as_posix()]
        if not capacity_helper:
            (workspace / "deploy-capacity-resource.py").unlink()
        if environment is not None:
            args += ["--environment", environment]
        if subscription is not None:
            args += ["--subscription", subscription]
        args += list(arguments)
        result = subprocess.run(
            [bash_executable(), "--noprofile", "--norc", script.as_posix(), *args],
            cwd=workspace, env=env, capture_output=True, text=True, timeout=90, check=False,
        )
        report_files = list((workspace / "reports").glob("*.json"))
        report_data = [json.loads(path.read_text(encoding="utf-8")) for path in report_files]
        return result, report_data

    try:
        yield run
    finally:
        shutil.rmtree(workspace)


def search_calls(result):
    return [line for line in result.stderr.splitlines()
            if line.startswith("MOCK_AZ:rest ") and "Microsoft.Search/locations/" in line]


@pytest.mark.parametrize("target,suffix", [("dev", "Dev"), ("test", "StageProd"), ("prod", "StageProd")])
@pytest.mark.parametrize("legacy", ['["basic",1]', '["basic","standard2"]'])
def test_ado_automatic_uppercase_alias_is_validated_before_azure(offline_preflight, target, suffix, legacy):
    result, _ = offline_preflight({
        ("skuAISearch" + suffix + "Array").upper(): legacy,
        ("skuArrayAISearch" + suffix).upper(): "basic,standard",
    }, environment=target, arguments=("--skip-azure-lookups",))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SEARCH_RETRY_CONFIG_INVALID" in result.stdout
    assert "MOCK_AZ:" not in result.stderr


@pytest.mark.parametrize("target,suffix,selected", [
    ("dev", "Dev", "basic"), ("test", "StageProd", "standard"), ("prod", "StageProd", "standard"),
])
def test_ado_automatic_uppercase_alias_checks_custom_candidates(offline_preflight, target, suffix, selected):
    result, reports = offline_preflight({
        ("skuAISearch" + suffix + "Array").upper(): '["standard","basic"]',
    }, environment=target, reports=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(search_calls(result)) == 2
    expected = [selected, "standard" if selected == "basic" else "basic"]
    observations = [
        item["sku"] for report in reports for item in report["observations"]
        if item["check_id"] == "search_sku_quota" and item["status"] == "passed"
    ]
    assert observations == expected


@pytest.mark.parametrize("target", ["dev", "test", "prod"])
@pytest.mark.parametrize("route", ["ado", "github"])
@pytest.mark.parametrize("scenario", ["legacy-custom", "primary-custom", "equal-custom", "conflict"])
def test_search_array_alias_file_settings_resolve_before_live_candidate_checks(
    offline_preflight, target, route, scenario,
):
    default = ["basic", "standard", "standard2"]
    custom = ["standard3", "basic", "standard"]
    primary, legacy = {
        "legacy-custom": (default, custom),
        "primary-custom": (custom, default),
        "equal-custom": ([" STANDARD3 ", " BASIC ", " STANDARD "], custom),
        "conflict": (custom, ["basic", "standard", "storage_optimized_l1"]),
    }[scenario]
    suffix = "Dev" if target == "dev" else "StageProd"
    if route == "ado":
        settings_file = {"yaml_settings": (
            f"variables:\n  skuAISearch{suffix}: standard\n"
            f"  skuArrayAISearch{suffix}: {json.dumps(json.dumps(primary))}\n"
            f"  skuAISearch{suffix}Array: '{','.join(legacy)}'\n"
        )}
    else:
        public_suffix = "DEV" if target == "dev" else "STAGE_PROD"
        settings_file = {"env_settings": (
            f"SKU_AISEARCH_{public_suffix.replace('_', '')}=standard\n"
            f"SKU_ARRAY_AISEARCH_{public_suffix.replace('_', '')}='{','.join(primary)}'\n"
            f"SKU_AI_SEARCH_{public_suffix}_ARRAY='{json.dumps(legacy)}'\n"
        )}
    result, reports = offline_preflight({
        "MOCK_SEARCH_USAGE": json.dumps(usage(("basic", "standard", "standard3", "storage_optimized_l1"))),
    }, environment=target, reports=True, **settings_file)
    if scenario == "conflict":
        assert result.returncode == 1, result.stdout + result.stderr
        assert "Conflicting AI Search capacity arrays" in result.stdout
        assert "SEARCH_RETRY_CONFIG_INVALID" in result.stdout
        assert "MOCK_AZ:" not in result.stderr
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(search_calls(result)) == 3
    ok_lines = [line for line in result.stdout.splitlines() if "[OK] AI Search" in line]
    assert [re.search(r"AI Search '([^']+)'", line)[1] for line in ok_lines] == [
        "standard", "standard3", "basic",
    ]
    quotas = [item for report in reports for item in report["observations"]
              if item["check_id"] == "search_sku_quota"]
    assert {item["sku"] for item in quotas} == {"standard", "standard3", "basic"}
    assert all(item["status"] == "passed" for item in quotas)


@pytest.mark.parametrize("settings", [
    {"skuAISearchDevArray": '["standard3", "basic", "standard"]'},
    {"skuArrayAISearchDev": '["standard3", "basic", "standard"]'},
    {"skuArrayAISearchDev": "standard3,basic,standard", "skuAISearchDevArray": ""},
])
def test_search_array_alias_missing_and_empty_legacy_bindings_do_not_hide_custom_values(offline_preflight, settings):
    result, _ = offline_preflight({
        **settings, "skuAISearchDev": "standard",
        "MOCK_SEARCH_USAGE": json.dumps(usage(("basic", "standard", "standard3"))),
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(search_calls(result)) == 3
    assert "AI Search 'standard3'" in result.stdout and "AI Search 'standard2'" not in result.stdout


@pytest.mark.parametrize("configured", [
    '["basic",', '["basic", 1]', '{"sku":"basic"}', '"basic"', "1", "[]",
])
@pytest.mark.parametrize("spelling", ["skuArrayAISearchDev", "skuAISearchDevArray"])
def test_search_array_alias_malformed_values_block_before_any_azure(offline_preflight, configured, spelling):
    result, _ = offline_preflight({spelling: configured})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SEARCH_RETRY_CONFIG_INVALID" in result.stdout
    assert "MOCK_AZ:" not in result.stderr


@pytest.mark.parametrize("missing", ["python", "helper"])
def test_search_array_alias_resolver_unavailable_is_a_configuration_failure(offline_preflight, missing):
    result, _ = offline_preflight(
        {"MOCK_PYTHON_MISSING": "true"} if missing == "python" else {},
        arguments=("--skip-azure-lookups",), capacity_helper=missing != "helper",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SEARCH_RETRY_CONFIG_INVALID" in result.stdout and "MOCK_AZ:" not in result.stderr


@pytest.mark.parametrize("disabled", ["search", "retry"])
def test_search_array_alias_disabled_config_only_modes_do_not_require_python(offline_preflight, disabled):
    result, _ = offline_preflight({
        "enableAISearch": "false" if disabled == "search" else "true",
        "aisearchRetryCapcityArray": "invalid" if disabled == "search" else "false",
        "skuArrayAISearchDev": "", "skuAISearchDevArray": '{"invalid":1}',
        "MOCK_PYTHON_MISSING": "true",
    }, arguments=("--skip-azure-lookups",), capacity_helper=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SEARCH_RETRY_CONFIG_INVALID" not in result.stdout and "MOCK_AZ:" not in result.stderr


def test_search_checks_all_three_candidates_and_reports_the_specific_sku(offline_preflight):
    result, reports = offline_preflight({"skuAISearchDev": " STANDARD "}, reports=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(search_calls(result)) == 3
    ok_lines = [line for line in result.stdout.splitlines() if "[OK] AI Search" in line]
    assert ["'standard'" in ok_lines[0], "'basic'" in ok_lines[1], "'standard2'" in ok_lines[2]] == [True] * 3
    observations = [item for report in reports for item in report["observations"]]
    assert {item["sku"] for item in observations if item["check_id"] == "search_sku_quota"} == {
        "basic", "standard", "standard2",
    }
    assert all(item["status"] == "passed" for item in observations if item["check_id"] == "search_sku_quota")


@pytest.mark.parametrize("failure,expected", [
    ("exhausted", "SEARCH_QUOTA_AT_LIMIT"),
    ("unlisted", "SEARCH_SKU_UNAVAILABLE"),
    ("malformed", "SEARCH_QUOTA_UNVALIDATED"),
])
def test_bad_fallback_candidate_blocks_even_warn_only_and_keeps_completed_report(offline_preflight, failure, expected):
    payload = usage()
    if failure == "exhausted":
        payload["value"][1]["currentValue"] = 3
    elif failure == "unlisted":
        del payload["value"][1]
    else:
        del payload["value"][1]["currentValue"]
    result, reports = offline_preflight({"MOCK_SEARCH_USAGE": json.dumps(payload)}, reports=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(search_calls(result)) == 3
    assert "PREFLIGHT RESULT:" in result.stdout and expected in result.stdout
    observations = [item for report in reports for item in report["observations"]]
    assert observations, result.stderr
    quotas = [item for item in observations if item["check_id"] == "search_sku_quota"]
    assert any(item["sku"] == "basic" and item["status"] == "passed" for item in quotas)
    assert any(item["sku"] == "standard2" and item["status"] == "passed" for item in quotas)
    if failure == "malformed":
        assert any(item["sku"] == "standard" and item["status"] == "unknown" for item in quotas)
    elif failure == "exhausted":
        assert any(item["sku"] == "standard" and item["status"] == "failed" for item in quotas)
    else:
        assert any(item["sku"] == "standard" and item["status"] == "failed"
                   for item in observations if item["check_id"] == "search_sku_availability")
    summary = [item for item in observations if item["check_id"].startswith("preflight-job:")]
    assert summary and summary[0]["status"] == "failed"
    assert summary[0]["message"].startswith("Preflight completed;")
    assert not any("incomplete" in item["message"].lower() for item in observations)


@pytest.mark.parametrize("extra", [
    {"MOCK_SEARCH_USAGE": "not-json"},
    {"MOCK_SEARCH_USAGE": ""},
    {"MOCK_SEARCH_STATUS": "1"},
    {"MOCK_SEARCH_STATUS": "1", "MOCK_TRANSIENT": "true"},
])
def test_unconfirmable_search_lookup_blocks_all_candidate_gate(offline_preflight, extra):
    result, _ = offline_preflight(extra)
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(search_calls(result)) == 3
    assert "PREFLIGHT RESULT:" in result.stdout
    assert "Search candidate quota headroom was not confirmed" in result.stdout


@pytest.mark.parametrize("payload", ["not-json", json.dumps(usage(("basic",))), json.dumps({
    "value": [{"name": {"value": "basic"}, "limit": 0, "currentValue": 0}],
})])
def test_disabled_search_retry_checks_only_selected_with_original_warn_only_policy(offline_preflight, payload):
    result, _ = offline_preflight({
        "aisearchRetryCapcityArray": "false", "skuArrayAISearchDev": "invalid,,",
        "MOCK_SEARCH_USAGE": payload,
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(search_calls(result)) == 1
    assert "SEARCH_RETRY_CONFIG_INVALID" not in result.stdout


@pytest.mark.parametrize("settings,code", [
    ({"skuArrayAISearchDev": "basic,standard,"}, "SEARCH_RETRY_CONFIG_INVALID"),
    ({"skuArrayAISearchDev": ""}, "SEARCH_RETRY_CONFIG_INVALID"),
    ({"aisearchRetryCapcityArray": "maybe"}, "SEARCH_RETRY_CONFIG_INVALID"),
    ({"enablePostgreSQL": "true", "skuArrayPostgreSQLDev": "Standard_B1ms,Standard_F2"}, "POSTGRES_RETRY_CONFIG_INVALID"),
    ({"enablePostgreSQL": "true", "skuTierPostgreSQLDev": "GeneralPurpose"}, "POSTGRES_RETRY_CONFIG_INVALID"),
    ({"enablePostgreSQL": "true", "postgreSQLRetryCapacityArray": "maybe"}, "POSTGRES_RETRY_CONFIG_INVALID"),
    ({"enableContainerApps": "true", "skuArrayContainerAppsDev": "Consumption,D4,D16"}, "CONTAINER_APPS_RETRY_CONFIG_INVALID"),
    ({"enableContainerApps": "true", "skuArrayContainerAppsDev": "Consumption,D4,d4"}, "CONTAINER_APPS_RETRY_CONFIG_INVALID"),
    ({"enableContainerApps": "true", "containerAppsRetryCapacityArray": ""}, "CONTAINER_APPS_RETRY_CONFIG_INVALID"),
])
def test_static_capacity_validation_blocks_invalid_configs_even_with_azure_skipped(offline_preflight, settings, code):
    result, _ = offline_preflight(settings, arguments=("--skip-azure-lookups",))
    assert result.returncode == 1, result.stdout + result.stderr
    assert code in result.stdout and "PREFLIGHT RESULT:" in result.stdout
    assert "MOCK_AZ:" not in result.stderr


def test_invalid_configuration_is_checked_before_any_azure_lookup(offline_preflight):
    result, _ = offline_preflight({"skuArrayAISearchDev": "basic,standard,"})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "MOCK_AZ:" not in result.stderr


def test_disabled_services_and_disabled_retries_ignore_unused_arrays(offline_preflight):
    result, _ = offline_preflight({
        "enableAISearch": "false", "skuArrayAISearchDev": "", "aisearchRetryCapcityArray": "invalid",
        "skuArrayPostgreSQLDev": "", "postgreSQLRetryCapacityArray": "invalid",
        "skuArrayContainerAppsDev": "", "containerAppsRetryCapacityArray": "invalid",
    }, arguments=("--skip-azure-lookups",))
    assert result.returncode == 0, result.stdout + result.stderr
    result, _ = offline_preflight({
        "enablePostgreSQL": "true", "postgreSQLRetryCapacityArray": "false", "skuArrayPostgreSQLDev": "",
        "enableContainerApps": "true", "containerAppsRetryCapacityArray": "false", "skuArrayContainerAppsDev": "",
    }, arguments=("--skip-azure-lookups",))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("selected,tier", [
    ("standard_b2ms", " burstable "), ("Standard_D2s_v3", "GeneralPurpose"),
    ("Standard_E2s_v3", "MEMORYOPTIMIZED"),
])
def test_pg_family_tiers_and_aca_profiles_are_static_not_capacity_certificates(offline_preflight, selected, tier):
    result, _ = offline_preflight({
        "enablePostgreSQL": "true", "skuPostgreSQLDev": selected, "skuTierPostgreSQLDev": tier,
        "skuArrayPostgreSQLDev": "Standard_B2ms,Standard_D2s_v3,Standard_E2s_v3",
        "enableContainerApps": "true", "skuContainerAppsDev": " d4 ",
        "skuArrayContainerAppsDev": " Consumption , D4 , d8 ",
    }, arguments=("--skip-azure-lookups",))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "per-SKU quota headroom and live allocation capacity are not confirmed" in result.stdout
    assert "retain Consumption" in result.stdout


def test_static_validation_covers_targeted_profiles_even_without_subscription_ids(offline_preflight):
    settings = {"aifactory_common_only_dev_environment": "false", "skuArrayAISearchStageProd": "standard,"}
    result, _ = offline_preflight(settings, environment=None, subscription=None,
                                  arguments=("--skip-azure-lookups",))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[test] Azure AI Search" in result.stdout and "[prod] Azure AI Search" in result.stdout
    result, _ = offline_preflight(settings, environment="dev", subscription=None,
                                  arguments=("--skip-azure-lookups",))
    assert result.returncode == 0, result.stdout + result.stderr


def test_static_validation_covers_pg_and_aca_stage_prod_profiles(offline_preflight):
    result, _ = offline_preflight({
        "aifactory_common_only_dev_environment": "false",
        "enablePostgreSQL": "true", "skuTierPostgreSQLStageProd": "MemoryOptimized",
        "enableContainerApps": "true", "skuArrayContainerAppsStageProd": "Consumption,D4,d4",
    }, environment=None, subscription=None, arguments=("--skip-azure-lookups",))
    assert result.returncode == 1, result.stdout + result.stderr
    for environment in ("test", "prod"):
        assert f"[{environment}] PostgreSQL" in result.stdout
        assert f"[{environment}] Container Apps" in result.stdout
    assert "[dev] PostgreSQL" not in result.stdout and "[dev] Container Apps" not in result.stdout


@pytest.mark.parametrize("route", ["yaml", "env"])
def test_capacity_settings_read_files_and_do_not_default_explicit_empty_arrays(offline_preflight, route):
    if route == "yaml":
        result, _ = offline_preflight(
            arguments=("--skip-azure-lookups",), yaml_settings='variables:\n  skuArrayAISearchDev: ""\n',
        )
    else:
        result, _ = offline_preflight(
            arguments=("--skip-azure-lookups",), env_settings='SKU_ARRAY_AISEARCH_DEV=""\n',
        )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SEARCH_RETRY_CONFIG_INVALID" in result.stdout
    assert "MOCK_AZ:" not in result.stderr


def test_same_subscription_still_checks_distinct_environment_sku_profiles(offline_preflight):
    result, _ = offline_preflight({
        "aifactory_common_only_dev_environment": "false",
        "dev_sub_id": SUBSCRIPTION, "test_sub_id": SUBSCRIPTION, "prod_sub_id": SUBSCRIPTION,
        "skuArrayAISearchDev": "basic", "skuArrayAISearchStageProd": "standard,standard2",
    }, environment=None, subscription=None)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(search_calls(result)) == 5


@pytest.mark.parametrize("settings,subscription", [
    ({"MOCK_AZ_MISSING": "true"}, SUBSCRIPTION),
    ({"MOCK_ACCOUNT_STATUS": "1"}, SUBSCRIPTION),
    ({"MOCK_SELECT_STATUS": "1"}, SUBSCRIPTION),
    ({}, None),
])
def test_search_gate_blocks_unreadable_or_missing_targets_unless_explicitly_bypassed(offline_preflight, settings, subscription):
    result, _ = offline_preflight(settings, subscription=subscription)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "SEARCH_QUOTA_UNVALIDATED" in result.stdout and "PREFLIGHT RESULT:" in result.stdout
    result, _ = offline_preflight(settings, subscription=subscription, arguments=("--skip-regional",))
    assert result.returncode == 0, result.stdout + result.stderr
    result, _ = offline_preflight(settings, subscription=subscription, arguments=("--skip-azure-lookups",))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MOCK_AZ:" not in result.stderr


def test_explicit_skip_bypasses_every_capacity_check(offline_preflight):
    result, _ = offline_preflight({"skuArrayAISearchDev": "invalid,,"}, arguments=("--skip",))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MOCK_AZ:" not in result.stderr


def test_pg_and_aca_use_existing_provider_region_checks_without_quota_endpoints(offline_preflight):
    result, _ = offline_preflight({"enablePostgreSQL": "true", "enableContainerApps": "true"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MOCK_AZ:provider show --namespace Microsoft.DBforPostgreSQL -o json" in result.stderr
    assert "MOCK_AZ:provider show --namespace Microsoft.App -o json" in result.stderr
    assert not any("Microsoft.DBforPostgreSQL" in call or "Microsoft.App" in call for call in search_calls(result))
