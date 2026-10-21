"""Key Vault principal object IDs block the factory preflight, even in WARN_ONLY mode.

modules/kvCmnAccessPolicys.bicep skips every principal that is not a GUID (purple 6383fdd3),
so the shipped technical_admins_ad_object_id default "<todo>_EntraID_ObjectID" would leave the
common/admin vaults without an admin policy. The preflight must stop it before any deployment.
Valid technical admin IDs that Bicep normalizes (purple 474ecff3) only warn: case or spacing renames
role assignments once.
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from .test_capacity_preflight import ROOT, SCRIPTS, offline_preflight  # noqa: F401


CHECKER = SCRIPTS / "kv_principal_object_ids.py"
SETTINGS = ROOT / "environment_setup" / "aifactory" / "bicep" / "copy_to_local_settings"
JSON_TEMPLATE = ROOT / "environment_setup" / "aifactory" / "variables.json"
YAML_TEMPLATE = SETTINGS / "azure-devops" / "esml-yaml-pipelines" / "variables" / "variables.yaml"
ENV_TEMPLATE = SETTINGS / "github-actions" / ".env.template"
GHA_COMMON = SETTINGS / "github-actions" / "infra-common.yml"
GHA_PROJECT = SETTINGS / "github-actions" / "infra-project-phase.yml"
ADO_JOBS = SETTINGS / "azure-devops" / "esml-yaml-pipelines"

ADMIN = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ADMIN2 = "11111111-2222-4333-8444-555555555555"
DATABRICKS = "99999999-8888-4777-8666-555555555555"
AZURE_DATABRICKS_APP_ID = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"  # first-party app ID, same in every tenant
INVALID = "KV_PRINCIPAL_OBJECT_ID_INVALID"
UNREADABLE = "KV_PRINCIPAL_CONFIG_UNREADABLE"
NOT_NORMALIZED = "KV_PRINCIPAL_OBJECT_ID_NOT_NORMALIZED"
BLOCKED = "preflight FAILED: Key Vault principal object IDs"


def load_checker():
    spec = importlib.util.spec_from_file_location("_kv_principal_object_ids", CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return load_checker()


def codes(findings):
    return [finding.code for finding in findings]


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


# --- Values ---------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "<todo>_EntraID_ObjectID",                # variables.json / variables.yaml default
    "<todo>_object_id",                       # .env.template PROJECT_MEMBERS default
    "not-a-guid",
    f"{ADMIN},<todo>",
    f"{ADMIN},,{ADMIN2}",                     # empty entry
    f"{ADMIN},",                              # trailing comma
    ADMIN.replace("-", ""),                   # Key Vault needs the dashed form
    "{" + ADMIN + "}",
    ADMIN[:-1] + "g",                         # not hexadecimal
    f"{ADMIN}\n{ADMIN2}",
    "null",                                   # GenAI project naming would pass 'null' to ARM
])
def test_technical_admins_must_be_comma_separated_guids(checker, value):
    findings, _ = checker.validate({"technical_admins_ad_object_id": value}, ["dev"])
    assert codes(findings) == [INVALID]
    assert "technical_admins_ad_object_id" in findings[0].message
    assert "pipeline environment" in findings[0].message


@pytest.mark.parametrize("value", [
    "", "   ",                                # Bicep grants no technical admin for ''
    ADMIN,
    f" {ADMIN} , {ADMIN2.upper()} ",          # trimmed and case-insensitive
])
def test_technical_admins_accept_guids_or_none(checker, value):
    findings, _ = checker.validate({"technical_admins_ad_object_id": value}, ["dev"])
    assert findings == []


def test_findings_show_placeholders_but_never_object_ids(checker):
    findings, _ = checker.validate({"technical_admins_ad_object_id": f"{ADMIN},<todo>_x"}, ["dev"])
    assert "<todo>_x" in findings[0].message and ADMIN not in findings[0].message


def test_other_invalid_entries_are_reported_by_position(checker):
    # GitHub masks only whole secrets; one mistyped entry of PROJECT_MEMBERS must not be printed.
    findings, _ = checker.validate({"technical_admins_ad_object_id": f"{ADMIN}, typo-1234"}, ["dev"])
    assert "typo-1234" not in findings[0].message and "entry 2 of 2" in findings[0].message


# --- Sources ---------------------------------------------------------------------------------

def source_files(tmp_path, source, settings):
    """Write settings (canonical variables.json names) in one source's own format."""
    dotenv_names = {"technical_admins_ad_object_id": "PROJECT_MEMBERS", "databricksOID": "DATABRICKS_OID",
                    "enableDatabricks": "ENABLE_DATABRICKS", "enablePersonas": "ENABLE_PERSONAS",
                    "persona_access_mode": "PERSONA_ACCESS_MODE"}
    if source == "json":
        return {"variables_json": write(tmp_path / "variables.json", json.dumps({"dev": settings}))}
    if source == "yaml":
        lines = [f'  {key}: "{value}" # <mandatory> comment' for key, value in settings.items()]
        return {"variables_yaml": write(tmp_path / "variables.yaml", "variables:\n" + "\n".join(lines) + "\n")}
    lines = [f'{dotenv_names[key]}="{value}" # comment' for key, value in settings.items()]
    return {"env_file": write(tmp_path / ".env", "\n".join(lines) + "\n")}


@pytest.mark.parametrize("names,label", [
    ({"technical_admins_ad_object_id": "x"}, "technical_admins_ad_object_id in the pipeline environment"),
    ({"TECHNICAL_ADMINS_AD_OBJECT_ID": "x"}, "TECHNICAL_ADMINS_AD_OBJECT_ID in the pipeline environment"),
    ({"PROJECT_MEMBERS": "x"}, "PROJECT_MEMBERS in the pipeline environment"),
])
def test_pipeline_environment_names_of_github_ado_and_dotenv(checker, names, label):
    environ = {name: "<todo>_EntraID_ObjectID" for name in names}
    findings, _ = checker.validate(environ, ["dev"])
    assert codes(findings) == [INVALID] and label in findings[0].message


@pytest.mark.parametrize("source,label", [
    ("json", "technical_admins_ad_object_id in variables.json [dev]"),
    ("yaml", "technical_admins_ad_object_id in variables.yaml"),
    ("dotenv", "PROJECT_MEMBERS in .env"),
])
def test_placeholder_blocks_in_every_settings_file(checker, tmp_path, source, label):
    files = source_files(tmp_path, source, {"technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"})
    findings, _ = checker.validate({}, ["dev"], **files)
    assert codes(findings) == [INVALID] and label in findings[0].message


@pytest.mark.parametrize("path,files_key,label", [
    (JSON_TEMPLATE, "variables_json", "technical_admins_ad_object_id in variables.json [dev]"),
    (YAML_TEMPLATE, "variables_yaml", "technical_admins_ad_object_id in variables.yaml"),
    (ENV_TEMPLATE, "env_file", "PROJECT_MEMBERS in .env"),
])
def test_shipped_template_defaults_fail_fast(checker, path, files_key, label):
    findings, _ = checker.validate({}, ["dev"], **{files_key: path})
    assert codes(findings) == [INVALID], findings
    assert label in findings[0].message


def test_every_file_is_checked_independently(checker, tmp_path):
    files = {**source_files(tmp_path, "json", {"technical_admins_ad_object_id": ADMIN}),
             **source_files(tmp_path, "yaml", {"technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"}),
             **source_files(tmp_path, "dotenv", {"technical_admins_ad_object_id": "<todo>_object_id"})}
    findings, _ = checker.validate({}, ["dev"], **files)
    assert codes(findings) == [INVALID, INVALID]
    assert "variables.yaml" in findings[0].message and ".env" in findings[1].message


@pytest.mark.parametrize("value", [ADMIN, ""])
def test_pipeline_environment_value_wins_over_settings_files(checker, tmp_path, value):
    # CI passes exactly this value to Bicep; a stale file copy must not block or excuse it.
    files = source_files(tmp_path, "json", {"technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"})
    findings, _ = checker.validate({"technical_admins_ad_object_id": value}, ["dev"], **files)
    assert findings == []


def test_unexpanded_ado_macro_is_not_a_pipeline_value(checker, tmp_path):
    files = source_files(tmp_path, "json", {"technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"})
    environ = {"technical_admins_ad_object_id": "$(technical_admins_ad_object_id)"}
    findings, _ = checker.validate(environ, ["dev"], **files)
    assert codes(findings) == [INVALID] and "variables.json [dev]" in findings[0].message


def test_variables_json_uses_the_baseline_stage_prod_and_exact_environment_overlay(checker, tmp_path):
    config = {"dev": {"technical_admins_ad_object_id": ADMIN},
              "stage_prod": {"technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"},
              "test": {"technical_admins_ad_object_id": ADMIN2}}
    path = write(tmp_path / "variables.json", json.dumps(config))
    findings, _ = checker.validate({}, ["dev", "test", "prod"], variables_json=path)
    assert codes(findings) == [INVALID] and "variables.json [prod]" in findings[0].message


@pytest.mark.parametrize("text", ["{not json", "[]", json.dumps({"flat": {}})])
def test_unreadable_variables_json_blocks(checker, tmp_path, text):
    findings, _ = checker.validate({}, ["dev"], variables_json=write(tmp_path / "variables.json", text))
    assert codes(findings) == [UNREADABLE] and "variables.json" in findings[0].message


def test_variables_json_is_not_read_when_the_pipeline_provides_every_principal(checker, tmp_path):
    environ = {"technical_admins_ad_object_id": ADMIN, "databricksOID": DATABRICKS}
    findings, _ = checker.validate(environ, ["dev"], variables_json=write(tmp_path / "variables.json", "{"))
    assert findings == []


# --- Persona access ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,settings", [
    ("json", {"enablePersonas": True}),
    ("json", {"persona_access_mode": "groups-v1"}),
    ("yaml", {"enablePersonas": "true"}),
    ("dotenv", {"enablePersonas": "true"}),
])
def test_groups_v1_persona_access_skips_cleared_principals(checker, tmp_path, source, settings):
    # personas/pipeline.py clears the human channels and Bicep ignores them in groups-v1 mode.
    files = source_files(tmp_path, source, {**settings, "technical_admins_ad_object_id": "<todo>_EntraID_ObjectID",
                                            "enableDatabricks": "true", "databricksOID": "<optional>_ObjectID"})
    findings, notes = checker.validate({}, ["dev"], **files)
    assert findings == [] and any("groups-v1" in note for note in notes)


@pytest.mark.parametrize("names", [("enablePersonas",), ("ENABLEPERSONAS",), ("ENABLE_PERSONAS",)])
def test_groups_v1_in_the_pipeline_environment_skips_the_check(checker, names):
    environ = {"technical_admins_ad_object_id": "<todo>_EntraID_ObjectID", **{name: "true" for name in names}}
    findings, _ = checker.validate(environ, ["dev"])
    assert findings == []


def test_enable_personas_false_outranks_a_groups_v1_mode(checker, tmp_path):
    files = source_files(tmp_path, "json", {"enablePersonas": False, "persona_access_mode": "groups-v1",
                                            "technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"})
    findings, _ = checker.validate({}, ["dev"], **files)
    assert codes(findings) == [INVALID]


def test_github_empty_persona_variable_is_unset(checker):
    environ = {"ENABLE_PERSONAS": "", "persona_access_mode": "groups-v1",
               "technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"}
    findings, _ = checker.validate(environ, ["dev"])
    assert findings == []


def test_pipeline_groups_v1_also_covers_settings_file_fallbacks(checker, tmp_path):
    # The persona bridge already resolved groups-v1 for this run; a legacy file copy must not block it.
    files = source_files(tmp_path, "yaml", {"enablePersonas": "false",
                                            "technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"})
    environ = {"ENABLEPERSONAS": "true", "DATABRICKSOID": "<optional>_ObjectID", "ENABLEDATABRICKS": "true"}
    findings, notes = checker.validate(environ, ["dev"], **files)
    assert findings == [] and any("groups-v1" in note for note in notes)


# --- Databricks ---------------------------------------------------------------------------------

@pytest.mark.parametrize("enabled,value,blocked", [
    ("false", "<optional>_ObjectID", False),  # optional while Databricks is off
    ("false", "", False),
    ("true", "<optional>_ObjectID", True),
    ("true", "<todo>", True),
    ("true", "", False),                      # explicit "no grant": 13-rgLevel skips the module
    ("true", f" {DATABRICKS.upper()} ", False),
    ("true", f"{DATABRICKS},{ADMIN}", True),  # one principalId, a list would be skipped
    ("true", AZURE_DATABRICKS_APP_ID.upper(), True),  # application ID, not the tenant's object ID
])
def test_databricks_object_id_is_one_guid_when_databricks_is_enabled(checker, enabled, value, blocked):
    findings, _ = checker.validate({"enableDatabricks": enabled, "databricksOID": value}, ["dev"])
    assert codes(findings) == ([INVALID] if blocked else [])
    if blocked:
        assert "databricksOID" in findings[0].message


def test_empty_databricks_object_id_with_databricks_enabled_is_noted(checker):
    findings, notes = checker.validate({"enableDatabricks": "true", "databricksOID": ""}, ["dev"])
    assert findings == [] and any("databricksOID" in note and "empty" in note for note in notes)


def test_databricks_application_id_gets_a_specific_hint(checker):
    findings, _ = checker.validate({"enableDatabricks": "true", "databricksOID": AZURE_DATABRICKS_APP_ID}, ["dev"])
    assert "application" in findings[0].message and "object ID" in findings[0].hint


@pytest.mark.parametrize("scope,expected", [
    (None, ["technical_admins_ad_object_id", "databricksOID"]),
    ("common", ["technical_admins_ad_object_id", "databricksOID"]),
    ("project", ["technical_admins_ad_object_id"]),  # only 13-rgLevel (common) reads databricksOID
])
def test_databricks_object_id_is_a_common_scope_check(checker, scope, expected):
    environ = {"technical_admins_ad_object_id": "<todo>", "enableDatabricks": "true", "databricksOID": "<todo>"}
    findings, _ = checker.validate(environ, ["dev"], scope=scope)
    assert [finding.message.split(" ", 1)[0] for finding in findings] == expected


@pytest.mark.parametrize("source,label", [
    ("json", "databricksOID in variables.json [dev]"),
    ("yaml", "databricksOID in variables.yaml"),
    ("dotenv", "DATABRICKS_OID in .env"),
])
def test_databricks_placeholder_blocks_in_every_settings_file(checker, tmp_path, source, label):
    files = source_files(tmp_path, source, {"enableDatabricks": "true", "databricksOID": "<optional>_ObjectID"})
    findings, _ = checker.validate({}, ["dev"], **files)
    assert codes(findings) == [INVALID] and label in findings[0].message


def test_ado_uppercase_databricks_names(checker):
    findings, _ = checker.validate({"ENABLEDATABRICKS": "true", "DATABRICKSOID": "<optional>_ObjectID"}, ["dev"])
    assert codes(findings) == [INVALID] and "DATABRICKSOID in the pipeline environment" in findings[0].message


def test_pipeline_databricks_flag_falls_back_to_settings_files(checker, tmp_path):
    files = source_files(tmp_path, "yaml", {"enableDatabricks": "true"})
    findings, _ = checker.validate({"databricksOID": "<optional>_ObjectID"}, ["dev"], **files)
    assert codes(findings) == [INVALID] and "pipeline environment" in findings[0].message


# --- Normalization warnings (Bicep trims, lower-cases and de-duplicates since purple 474ecff3) ------

@pytest.mark.parametrize("value,reason", [
    (ADMIN.upper(), "upper-case"),
    (f"{ADMIN2},{ADMIN.upper()}", "upper-case"),
    (f" {ADMIN}", "whitespace"),
    (f"{ADMIN} , {ADMIN2}", "whitespace"),
    (f"{ADMIN}\n", "whitespace"),             # a GitHub secret pasted with its line break
    (f"{ADMIN},{ADMIN2},{ADMIN}", "duplicate"),
    (f"{ADMIN},{ADMIN.upper()}", "duplicate"),  # the same principal once lower-cased
])
def test_valid_but_unnormalized_technical_admins_warn_without_blocking(checker, value, reason):
    result = checker.assess({"technical_admins_ad_object_id": value}, ["dev"])
    assert result.findings == []
    assert codes(result.warnings) == [NOT_NORMALIZED]
    assert reason in result.warnings[0].message
    assert "technical_admins_ad_object_id in the pipeline environment" in result.warnings[0].message


@pytest.mark.parametrize("value", ["", "   ", "\n", ADMIN, f"{ADMIN},{ADMIN2}"])
def test_normalized_or_empty_technical_admins_do_not_warn(checker, value):
    assert checker.assess({"technical_admins_ad_object_id": value}, ["dev"]).warnings == []


@pytest.mark.parametrize("value", [f"{ADMIN.upper()},,{ADMIN2}", f"{ADMIN.upper()},", " null "])
def test_blocked_values_fail_without_an_extra_warning(checker, value):
    # Empty and 'null' entries stay blocking: esml-util templates still split the list themselves.
    result = checker.assess({"technical_admins_ad_object_id": value}, ["dev"])
    assert codes(result.findings) == [INVALID] and result.warnings == []


def test_case_or_spacing_warning_names_the_one_time_409_and_its_fix(checker):
    warning = checker.assess({"technical_admins_ad_object_id": ADMIN.upper()}, ["dev"]).warnings[0]
    assert "role-assignment names" in warning.message and "RoleAssignmentExists (409)" in warning.message
    assert "same principal, role and scope" in warning.hint and "az role assignment delete" in warning.hint
    assert "101-rbac-common-rg" in warning.hint and "continueOnError: true" in warning.hint


def test_duplicate_only_warning_does_not_predict_a_409(checker):
    # Names are seeded per object ID, so dropping a repeated entry renames nothing.
    warning = checker.assess({"technical_admins_ad_object_id": f"{ADMIN},{ADMIN}"}, ["dev"]).warnings[0]
    assert "409" not in warning.message + warning.hint


def test_warnings_list_every_deviation_but_never_the_object_ids(checker):
    # GitHub masks the whole PROJECT_MEMBERS secret, not its entries.
    warning = checker.assess({"PROJECT_MEMBERS": f" {ADMIN.upper()} ,{ADMIN2},{ADMIN2}\n"}, ["dev"]).warnings[0]
    assert all(reason in warning.message for reason in ("upper-case", "whitespace", "duplicate"))
    text = (warning.message + " " + warning.hint).lower()
    assert ADMIN[:8] not in text and ADMIN2[:8] not in text and ADMIN[-12:] not in text


@pytest.mark.parametrize("source,label", [
    ("json", "technical_admins_ad_object_id in variables.json [dev]"),
    ("yaml", "technical_admins_ad_object_id in variables.yaml"),
    ("dotenv", "PROJECT_MEMBERS in .env"),
])
def test_unnormalized_technical_admins_warn_in_every_settings_file(checker, tmp_path, source, label):
    files = source_files(tmp_path, source, {"technical_admins_ad_object_id": f"{ADMIN2}, {ADMIN.upper()}"})
    result = checker.assess({}, ["dev"], **files)
    assert result.findings == [] and codes(result.warnings) == [NOT_NORMALIZED]
    assert label in result.warnings[0].message


def test_databricks_object_id_case_does_not_warn(checker):
    # One Key Vault access-policy principal: no role-assignment name is seeded with it.
    result = checker.assess({"enableDatabricks": "true", "databricksOID": f" {DATABRICKS.upper()} "}, ["dev"])
    assert result.findings == [] and result.warnings == []


def test_groups_v1_persona_access_does_not_warn(checker):
    result = checker.assess({"technical_admins_ad_object_id": ADMIN.upper(), "enablePersonas": "true"}, ["dev"])
    assert result.warnings == []


def test_validate_still_returns_only_findings_and_notes(checker):
    findings, notes = checker.validate({"technical_admins_ad_object_id": ADMIN.upper()}, ["dev"])
    assert findings == [] and any("are valid in: the pipeline environment" in note for note in notes)


# --- Command line --------------------------------------------------------------------------------

def run_checker(*arguments):
    return subprocess.run(
        [sys.executable, "-I", str(CHECKER), *arguments],
        capture_output=True, text=True, timeout=30, check=False, env={"SYSTEMROOT": "C:\\Windows"},
    )


def test_command_line_prints_tab_separated_findings(tmp_path):
    path = write(tmp_path / "variables.json", json.dumps({"dev": {"technical_admins_ad_object_id": "<todo>"}}))
    result = run_checker("--variables-json", str(path), "--environment", "dev", "--scope", "project")
    assert result.returncode == 0, result.stderr
    fail = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("FAIL\t")]
    assert len(fail) == 1 and fail[0][1] == INVALID and len(fail[0]) == 4


def test_command_line_prints_tab_separated_warnings(tmp_path):
    path = write(tmp_path / "variables.json", json.dumps({"dev": {"technical_admins_ad_object_id": ADMIN.upper()}}))
    result = run_checker("--variables-json", str(path), "--environment", "dev", "--scope", "project")
    assert result.returncode == 0, result.stderr
    lines = [line.split("\t") for line in result.stdout.splitlines()]
    warn = [fields for fields in lines if fields[0] == "WARN"]
    assert len(warn) == 1 and warn[0][1] == NOT_NORMALIZED and len(warn[0]) == 4
    assert not [fields for fields in lines if fields[0] == "FAIL"]


def test_command_line_rejects_an_unknown_scope():
    assert run_checker("--environment", "dev", "--scope", "hub").returncode == 2


# --- preflight.sh end to end (Git Bash is slow on Windows: keep these few) ------------------------

def kv_lines(result, marker):
    return [line for line in result.stdout.splitlines() if marker in line and "KV_PRINCIPAL" in line]


def test_preflight_blocks_the_shipped_variables_json_in_warn_only_mode(offline_preflight):
    result, _ = offline_preflight({"TF_BUILD": "True"}, arguments=("--skip-azure-lookups",),
                                  json_settings=JSON_TEMPLATE.read_text(encoding="utf-8"))
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert BLOCKED in output and "variables.json [dev]" in output
    errors = kv_lines(result, "##vso[task.logissue type=error]")
    assert errors and all("WARN_ONLY" not in line for line in errors), output


def test_preflight_blocks_the_shipped_env_template_with_a_github_error(offline_preflight):
    result, _ = offline_preflight({"GITHUB_ACTIONS": "true"}, arguments=("--skip-azure-lookups",),
                                  env_settings=ENV_TEMPLATE.read_text(encoding="utf-8"))
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert BLOCKED in output and "PROJECT_MEMBERS in .env" in output
    assert kv_lines(result, "::error::"), output


def test_preflight_passes_explicit_files_environment_and_project_scope(offline_preflight, tmp_path):
    config = write(tmp_path / "variables.json", json.dumps({
        "dev": {"technical_admins_ad_object_id": ADMIN},
        "stage_prod": {"technical_admins_ad_object_id": "<todo>_EntraID_ObjectID"}}))
    result, _ = offline_preflight(
        arguments=("--skip-azure-lookups", "--scope", "project", "--variables-json", config.as_posix()),
        environment="prod", yaml_settings='variables:\n  technical_admins_ad_object_id: "<todo>"\n'
                                         '  enableDatabricks: "true"\n  databricksOID: "<todo>"\n')
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "variables.json [prod]" in output and "technical_admins_ad_object_id in variables.yaml" in output
    assert "databricksOID in" not in output  # project scope: no project template reads databricksOID


def test_preflight_trusts_valid_pipeline_values_over_a_stale_variables_json(offline_preflight):
    result, _ = offline_preflight(
        {"technical_admins_ad_object_id": f"{ADMIN},{ADMIN2}", "databricksOID": DATABRICKS, "enableDatabricks": "true"},
        arguments=("--skip-azure-lookups", "--scope", "common"),
        json_settings=JSON_TEMPLATE.read_text(encoding="utf-8"))
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "KV_PRINCIPAL" not in output


def test_preflight_warns_about_unnormalized_technical_admins_without_blocking(offline_preflight):
    result, _ = offline_preflight({"TF_BUILD": "True", "technical_admins_ad_object_id": f"{ADMIN.upper()}, {ADMIN2}"},
                                  arguments=("--skip-azure-lookups", "--scope", "project"))
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert BLOCKED not in output and f"[WARN] {NOT_NORMALIZED}" in output
    assert kv_lines(result, "##vso[task.logissue type=warning]"), output
    assert not kv_lines(result, "##vso[task.logissue type=error]"), output
    assert ADMIN.upper() not in output and ADMIN2 not in output


def test_preflight_without_python_warns_that_principals_were_not_validated(offline_preflight):
    result, _ = offline_preflight({"technical_admins_ad_object_id": "<todo>", "MOCK_PYTHON_MISSING": "true",
                                   "enableAISearch": "false"},
                                  arguments=("--skip-azure-lookups",), capacity_helper=False)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[WARN] KV_PRINCIPAL_UNVALIDATED" in output and BLOCKED not in output


# --- Pipeline wiring ------------------------------------------------------------------------------

def github_preflight_steps(path):
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])
            if "scripts/preflight.sh" in step.get("run", "")]


def ado_preflight_step(name):
    steps = yaml.safe_load((ADO_JOBS / name).read_text(encoding="utf-8"))["steps"]
    return next(step for step in steps if "preflight.sh" in step.get("inputs", {}).get("scriptPath", ""))


def test_github_common_preflight_checks_the_common_scope_with_the_databricks_switch():
    steps = github_preflight_steps(GHA_COMMON)
    assert len(steps) == 3
    for step in steps:
        assert "--scope common" in step["run"]
        assert "vars.ENABLE_DATABRICKS" in step["env"]["enableDatabricks"]
        assert "env.enableDatabricks" in step["env"]["enableDatabricks"]  # JSON override first


def test_github_project_preflight_checks_the_project_scope():
    steps = github_preflight_steps(GHA_PROJECT)
    assert len(steps) == 1
    assert "--scope project" in steps[0]["run"] and "databricksOID" not in steps[0]["env"]


@pytest.mark.parametrize("name,scope", [
    ("esml-infra-common/jobs/job-1-aif-cmn.yaml", "common"),
    ("esml-infra-project/jobs/job-1-genai-networking.yaml", "project"),
    ("esml-infra-project/jobs/job-2-genai-services.yaml", "project"),
])
def test_ado_preflight_maps_principals_explicitly_so_secret_variables_reach_the_gate(name, scope):
    step = ado_preflight_step(name)
    assert f"--scope {scope}" in step["inputs"]["arguments"]
    assert step["env"]["technical_admins_ad_object_id"] == "$(technical_admins_ad_object_id)"
    assert ("databricksOID" in step["env"]) == (scope == "common")
