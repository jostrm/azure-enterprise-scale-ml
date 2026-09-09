"""Offline checks for the update launcher's JSON producer and pipeline consumer."""

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
LAUNCHER = ROOT / "bootstrap" / "GH-update-aifactory-and-run-project.sh"
IDENTITY = {
    "GITHUB_USERNAME": "example",
    "GITHUB_USE_SSH": "true",
    "GITHUB_TEMPLATE_REPO": "example/template",
    "GITHUB_NEW_REPO": "example/new-repo",
    "GITHUB_NEW_REPO_VISIBILITY": "private",
}
MARKER = (
    '"${PYTHON[@]}" - "$CONFIG_FILE" "$CONFIG_TEMPLATE_FILE" "$RUNNER_LABEL" '
    '"$state_dir/current.env" <<\'PY\'\n'
)


@pytest.mark.parametrize("has_env", [True, False])
def test_inline_merge_backfills_only_missing_github_identity(tmp_path, monkeypatch, has_env):
    launcher = LAUNCHER
    # Execute only the Python merge block, never any shell command or launcher.
    code = launcher.read_text(encoding="utf-8").split(MARKER, 1)[1].split("\nPY", 1)[0]
    active = {
        "dev": {
            "projectPrefix": "", "projectSuffix": "",
            "GITHUB_NEW_REPO": "explicit/keep",
            "GITHUB_USERNAME": "",
            "unmapped": {"keep": [False, 0, ""]},
        },
        "stage_prod": {"projectPrefix": "", "projectSuffix": "", "stage_only": "keep"},
        "extra_section": {"untouched": True},
        "_wizard": {"custom": "keep"},
    }
    original = copy.deepcopy(active)
    template = {
        "dev": {
            "projectPrefix": "esml-", "projectSuffix": "-rg",
            "GITHUB_USERNAME": "", "GITHUB_USE_SSH": "false",
            "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
            "GITHUB_NEW_REPO": "", "GITHUB_NEW_REPO_VISIBILITY": "public",
        },
    }
    active_path = tmp_path / "active.json"
    template_path = tmp_path / "template.json"
    env_path = tmp_path / "current.env"
    active_path.write_text(json.dumps(active), encoding="utf-8")
    template_path.write_text(json.dumps(template), encoding="utf-8")
    if has_env:
        env_path.write_text(
            "\n".join(f"export {key}='{value}' # comment" for key, value in IDENTITY.items())
            + "\nGITHUB_TOKEN=do-not-copy\nAZURE_CLIENT_SECRET=do-not-copy\n",
            encoding="utf-8-sig",
        )
    before = {path: path.read_bytes() for path in (template_path, env_path) if path.exists()}
    monkeypatch.setattr("sys.argv", ["merge", str(active_path), str(template_path), "unit-runner", str(env_path)])
    exec(compile(code, str(launcher), "exec"), {"__name__": "__main__"})
    result = json.loads(active_path.read_text(encoding="utf-8"))
    for section in ("dev", "stage_prod"):
        for key, value in original[section].items():
            assert result[section][key] == value
        for key in IDENTITY:
            if key not in original[section]:
                assert result[section][key] == (
                    IDENTITY[key] if has_env else template["dev"][key]
                )
    assert result["extra_section"] == original["extra_section"]
    assert result["_wizard"] == {"custom": "keep", "orchestrator": "gha"}
    assert result["dev"]["selfHostedRunnerLabel"] == "unit-runner"
    assert result["dev"]["useSelfHostedBuildAgent"] == "true"
    assert all(path.read_bytes() == value for path, value in before.items())
    assert "do-not-copy" not in active_path.read_text(encoding="utf-8")


def test_source_template_contains_only_generic_github_identity():
    template_path = ROOT / "environment_setup" / "aifactory" / "variables.json"
    values = json.loads(template_path.read_text(encoding="utf-8"))["dev"]
    assert {key: values[key] for key in IDENTITY} == {
        "GITHUB_USERNAME": "",
        "GITHUB_USE_SSH": "false",
        "GITHUB_TEMPLATE_REPO": "azure/enterprise-scale-aifactory",
        "GITHUB_NEW_REPO": "",
        "GITHUB_NEW_REPO_VISIBILITY": "public",
    }
    assert "_wizard" not in values


def test_all_canonical_templates_include_default_false_hub_intent():
    base = ROOT / "environment_setup" / "aifactory"
    document = json.loads((base / "variables.json").read_text(encoding="utf-8"))
    assert set(document) == {"dev"}
    assert document["dev"]["enableAIFactoryHub"] is False
    assert document["dev"]["centralDnsZoneByPolicyInHub"] is False
    templates = base / "bicep" / "copy_to_local_settings"
    yaml_text = (templates / "azure-devops" / "esml-yaml-pipelines" /
                 "variables" / "variables.yaml").read_text(encoding="utf-8")
    env_text = (templates / "github-actions" / ".env.template").read_text(encoding="utf-8")
    upload = (templates / "github-actions" /
              "03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    for key, env_key in (("enableAIFactoryHub", "ENABLE_AI_FACTORY_HUB"),
                         ("centralDnsZoneByPolicyInHub", "CENTRAL_DNS_ZONE_BY_POLICY_IN_HUB")):
        assert re.search(r"^\s+" + key + r': "false"', yaml_text, re.M)
        assert re.search(r"^" + env_key + r'="false"', env_text, re.M)
        assert f'"{env_key}"' in upload


def test_json_override_consumer_defers_annotations_for_python_39():
    path = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    source = path.read_text(encoding="utf-8")
    assert "from __future__ import annotations" in source.splitlines()[:10]


def test_pipeline_consumer_ignores_wizard_metadata_and_reserved_github_identity(tmp_path, monkeypatch):
    path = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    spec = importlib.util.spec_from_file_location("json_overrides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values, section = module.selected_values({
        "dev": {"projectPrefix": "", **IDENTITY},
        "_wizard": {"orchestrator": "gha"},
    }, "dev")
    assert section == "dev"
    assert "_wizard" not in values
    github_env = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    applied, skipped = module.apply(values, "github", None)
    assert applied == 1
    assert set(skipped) == set(IDENTITY)
    assert "projectPrefix<<" in github_env.read_text(encoding="utf-8")
    assert "GITHUB_" not in github_env.read_text(encoding="utf-8")


@pytest.fixture
def json_override_module():
    path = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    spec = importlib.util.spec_from_file_location("dashboard_json_overrides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("dns,own", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("pipeline_format", ["github", "azure-devops"])
@pytest.mark.parametrize("environment,section", [("dev", "dev"), ("prod", "stage_prod")])
def test_hub_pair_uses_existing_camel_keys_without_dropping_flags(
        json_override_module, tmp_path, monkeypatch, capsys, dns, own,
        pipeline_format, environment, section):
    original = {section: {"centralDnsZoneByPolicyInHub": dns, "enableAIFactoryHub": own}}
    config = copy.deepcopy(original)
    values, selected = json_override_module.selected_values(config, environment)
    assert selected == section
    assert values == {key: str(value).lower() for key, value in original[section].items()}
    output = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(output))
    applied, skipped = json_override_module.apply(values, pipeline_format, None)
    assert applied == 2 and skipped == []
    text = output.read_text(encoding="utf-8") if pipeline_format == "github" else capsys.readouterr().out
    for key, value in original[section].items():
        if pipeline_format == "github":
            assert f"{key}<<" in text
            assert f"\n{str(value).lower()}\n" in text
        else:
            assert f"##vso[task.setvariable variable={key}]{str(value).lower()}" in text
    assert config == original


@pytest.mark.parametrize("value", ["", "https://portal.azure.com/#dashboard/private/example"])
@pytest.mark.parametrize("environment,section", [("dev", "dev"), ("stage", "stage_prod"), ("prod", "stage_prod")])
def test_dashboard_config_key_maps_to_existing_shell_safe_name(json_override_module, value, environment, section):
    values, selected = json_override_module.selected_values({
        section: {"aifactory-dash-01": value, "projectPrefix": ""},
    }, environment)
    assert selected == section
    assert values == {"AIFACTORY_DASHBOARD_URL": value, "projectPrefix": ""}


@pytest.mark.parametrize("names", [
    ["aifactory-dash-01", "AIFACTORY_DASHBOARD_URL"],
    ["AIFACTORY_DASHBOARD_URL", "aifactory-dash-01"],
])
def test_conflicting_aliases_fail_without_printing_values(json_override_module, capsys, names):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {
            names[0]: "private-value-a", names[1]: "private-value-b",
        }}, "dev")
    error = capsys.readouterr().err
    assert "Conflicting configuration values" in error
    assert "private-value" not in error
    values, _ = json_override_module.selected_values({"dev": dict.fromkeys(names, "")}, "dev")
    assert values == {"AIFACTORY_DASHBOARD_URL": ""}


@pytest.mark.parametrize("name", ["other-hyphen", "x\nINJECTED", "x;echo", "1invalid"])
def test_dashboard_alias_does_not_relax_variable_name_validation(json_override_module, name):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {name: "value"}}, "dev")


@pytest.mark.parametrize("pipeline_format", ["github", "azure-devops"])
@pytest.mark.parametrize("deployment_environment", ["dev", "stage", "test", "prod"])
def test_full_canonical_template_applies_with_dashboard_key_offline(tmp_path, pipeline_format, deployment_environment):
    consumer = ROOT / "environment_setup" / "aifactory" / "bicep" / "scripts" / "apply-json-config-overrides.py"
    template = ROOT / "environment_setup" / "aifactory" / "variables.json"
    original = template.read_bytes()
    environment = os.environ.copy()
    github_env = tmp_path / "github-env"
    environment["GITHUB_ENV"] = str(github_env)
    result = subprocess.run(
        [sys.executable, str(consumer), "--file", str(template), "--environment", deployment_environment,
         "--format", pipeline_format],
        env=environment, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Applied " in result.stdout
    if pipeline_format == "github":
        assert "AIFACTORY_DASHBOARD_URL<<" in github_env.read_text(encoding="utf-8")
        assert "SCALING_MODE<<" in github_env.read_text(encoding="utf-8")
        assert "\nshared-subscriptions\n" in github_env.read_text(encoding="utf-8")
        assert "scaling-mode<<" not in github_env.read_text(encoding="utf-8")
    else:
        assert "##vso[task.setvariable variable=AIFACTORY_DASHBOARD_URL]" in result.stdout
        assert "##vso[task.setvariable variable=SCALING_MODE]shared-subscriptions" in result.stdout
        assert "variable=scaling-mode" not in result.stdout
    assert template.read_bytes() == original


@pytest.mark.parametrize("mode", ["own-subscriptions", "shared-subscriptions"])
@pytest.mark.parametrize("environment,section", [
    ("dev", "dev"), ("stage", "stage_prod"), ("test", "stage_prod"), ("prod", "stage_prod"),
])
@pytest.mark.parametrize("pipeline_format", ["github", "azure-devops"])
def test_full_template_scaling_mode_alias(json_override_module, tmp_path, monkeypatch, capsys,
                                        mode, environment, section, pipeline_format):
    template = ROOT / "environment_setup" / "aifactory" / "variables.json"
    config = json.loads(template.read_text(encoding="utf-8"))
    config[section] = {**config["dev"], "scaling-mode": mode}
    values, selected = json_override_module.selected_values(config, environment)
    assert selected == section
    assert values["SCALING_MODE"] == mode
    assert "scaling-mode" not in values
    assert values["common_vnet_cidr"] == config[section]["common_vnet_cidr"]
    output = tmp_path / "github-env"
    monkeypatch.setenv("GITHUB_ENV", str(output))
    json_override_module.apply(values, pipeline_format, None)
    if pipeline_format == "github":
        text = output.read_text(encoding="utf-8")
        assert "SCALING_MODE<<" in text
        assert f"\n{mode}\n" in text
    else:
        assert f"##vso[task.setvariable variable=SCALING_MODE]{mode}" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["scaling-mode", "SCALING_MODE"])
@pytest.mark.parametrize("value", ["", "own", "shared", "Own-subscriptions",
                                  " own-subscriptions", "shared-subscriptions\n",
                                  None, True, 1, [], {}])
def test_invalid_scaling_modes_are_rejected(json_override_module, name, value):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {name: value}}, "dev")


@pytest.mark.parametrize("names", [
    ("scaling-mode", "SCALING_MODE"), ("SCALING_MODE", "scaling-mode"),
])
def test_scaling_alias_conflicts_are_rejected(json_override_module, capsys, names):
    with pytest.raises(SystemExit):
        json_override_module.selected_values({"dev": {
            names[0]: "own-subscriptions", names[1]: "shared-subscriptions",
        }}, "dev")
    assert "Conflicting configuration values" in capsys.readouterr().err
    values, _ = json_override_module.selected_values({
        "dev": dict.fromkeys(names, "own-subscriptions"),
    }, "dev")
    assert values == {"SCALING_MODE": "own-subscriptions"}


def test_canonical_scaling_templates_and_github_upload_use_safe_names():
    templates = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
    env_text = (templates / "github-actions/.env.template").read_text(encoding="utf-8")
    yaml_text = (templates / "azure-devops/esml-yaml-pipelines/variables/variables.yaml").read_text(encoding="utf-8")
    upload_text = (templates / "github-actions/03a-GH-create-or-update-github-variables.sh").read_text(encoding="utf-8")
    assert re.search(r'^SCALING_MODE="shared-subscriptions"', env_text, re.MULTILINE)
    assert re.search(r'^  scaling-mode: "shared-subscriptions"', yaml_text, re.MULTILINE)
    assert '"SCALING_MODE"' in upload_text.split("repo_level_vars=(", 1)[1].split("\n)", 1)[0]


@pytest.mark.parametrize("current_mode", [None, "own-subscriptions", "shared-subscriptions"])
def test_update_env_backfills_scaling_mode_without_overwriting_user_value(tmp_path, monkeypatch,
                                                                          current_mode):
    marker = '"${PYTHON[@]}" - ".env" ".env.template" "$RUNNER_LABEL" <<\'PY\'\n'
    code = LAUNCHER.read_text(encoding="utf-8").split(marker, 1)[1].split("\nPY", 1)[0]
    active = tmp_path / "active.env"
    template = tmp_path / "template.env"
    active.write_text(
        f'SCALING_MODE="{current_mode}"\n' if current_mode is not None else "",
        encoding="utf-8",
    )
    source = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings/github-actions/.env.template"
    template.write_bytes(source.read_bytes())
    original = active.read_bytes()
    monkeypatch.setattr("sys.argv", ["merge", str(active), str(template), "unit-runner"])
    exec(compile(code, str(LAUNCHER), "exec"), {"__name__": "__main__"})
    assert f'SCALING_MODE="{current_mode or "shared-subscriptions"}"' in template.read_text(encoding="utf-8")
    assert active.read_bytes() == original


@pytest.mark.parametrize("cidr,octet", [
    ("172.16.XX.0/20", "0"),
    ("172.16.XX.0/20", "16"),
    ("172.16.XX.0/20", "32"),
    ("172.16.0.0/18", "15"),
    ("172.16.0.0/18", "20"),
    ("172.16.0.0/18", "25"),
    ("172.16.0.0/16", "61"),
])
def test_preflight_substitutes_vnet_and_subnet_templates_offline(bash_executable, cidr, octet):
    preflight = ROOT / "environment_setup/aifactory/bicep/scripts/preflight.sh"
    text = preflight.read_text(encoding="utf-8")
    substitution = re.search(r"(?m)^sub_xx\(\).*?$", text).group(0)
    validation = text.split("  local out _cidr_data\n", 1)[1].split('  local had=""', 1)[0]
    script = (
        "set -euo pipefail\n" + substitution + "\nvalidate() {\n" + validation +
        '\nprintf "%s" "$out"\n}\nvalidate\n'
    )
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"BASH_ENV", "ENV", "SHELLOPTS"}}
    environment.update({
        "PYBIN": Path(sys.executable).as_posix(),
        "COMMON_VNET_CIDR": cidr,
        "DEV_CIDR_RANGE": octet,
        "COMMON_SUBNET_CIDR": "172.16.XX.0/26",
        "COMMON_SUBNET_SCORING_CIDR": "172.16.XX.64/26",
        "COMMON_PBI_SUBNET_CIDR": "172.16.XX.128/26",
        "COMMON_BASTION_SUBNET_CIDR": "172.16.XX.192/26",
    })
    result = subprocess.run(
        [bash_executable, "--noprofile", "--norc", "-c", script],
        env=environment, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("current_mode", [None, "own-subscriptions", "shared-subscriptions"])
def test_scaleset_template_merge_preserves_mode_in_all_formats(tmp_path, current_mode):
    helper = ROOT / "bootstrap/lib/aifactory_scaleset_config.py"
    spec = importlib.util.spec_from_file_location("scaling_bootstrap_config", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    formats = {
        "env": ('SCALING_MODE="{}"\n', module.merge_env_template),
        "yaml": ('variables:\n  scaling-mode: "{}"\n', module.merge_yaml_template),
        "json": ('{{"dev":{{"scaling-mode":"{}"}}}}', module.merge_json_template),
    }
    for extension, (pattern, merge) in formats.items():
        active = tmp_path / f"active.{extension}"
        template = tmp_path / f"template.{extension}"
        empty = '{"dev":{}}' if extension == "json" else "variables:\n" if extension == "yaml" else ""
        active.write_text(pattern.format(current_mode) if current_mode else empty, encoding="utf-8")
        template.write_text(pattern.format("shared-subscriptions"), encoding="utf-8")
        merge(template, active)
        assert (current_mode or "shared-subscriptions") in active.read_text(encoding="utf-8")


@pytest.fixture
def bash_executable():
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        bash = str(candidate) if candidate.is_file() else None
    else:
        bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash is required for offline launcher prompt tests.")
    return bash


def run_sync_blocks(tmp_path, bash_executable, answer, *, use_json="y", update=None, uploader_exit=0):
    text = LAUNCHER.read_text(encoding="utf-8")
    function = text.split("confirm_update_github_variables() {", 1)[1].split(
        '\njson_override_choice="${AIFACTORY_USE_JSON_OVERRIDE:-}"', 1
    )[0]
    config_choice = text.split('\njson_override_choice=', 1)[1].split("\nfor command in git gh;", 1)[0]
    sync = text.split('aif_section "05 / Synchronize GitHub configuration"', 1)[1].split(
        "\ngrep -q 'AIFACTORY_CONFIG_JSON'", 1
    )[0]
    dispatch = text.split('\ngh workflow run "$WORKFLOW_FILE"', 1)[1].split('\nrun_id=""', 1)[0]
    config = tmp_path / "aifactory" / "variables.json"
    config.parent.mkdir()
    config.write_text('{"dev":{"projectPrefix":""}}', encoding="utf-8")
    (tmp_path / ".env").write_text('GITHUB_NEW_REPO="example/factory"\n', encoding="utf-8")
    # Execute only the prompt, upload decision, and dispatch blocks. All outbound
    # commands are functions; never source/run the update, git, or deployment steps.
    script = (
        'set -euo pipefail\n'
        'source "$AIF_TEST_LIBRARY"\n'
        'readonly CONFIG_FILE="aifactory/variables.json"\n'
        'readonly ENVIRONMENT="dev" WORKFLOW_FILE="infra-project.yml" RUNNER_LABEL="unit-runner"\n'
        'PYTHON=("$AIF_TEST_PYTHON")\n'
        'bash() { printf "BULK:%s\\n" "$*"; cat >/dev/null; return "$AIF_TEST_UPLOADER_EXIT"; }\n'
        'gh() { printf "GH:%s\\n" "$*"; if [[ "$1" == "secret" ]]; then cat >/dev/null; fi; }\n'
        'confirm_update_github_variables() {' + function +
        '\njson_override_choice=' + config_choice +
        '\n' + sync +
        '\ngh workflow run "$WORKFLOW_FILE"' + dispatch
    )
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"BASH_ENV", "ENV", "AIFACTORY_UPDATE_GITHUB_VARIABLES", "SHELLOPTS"}}
    environment.update({
        "AIF_TEST_LIBRARY": (ROOT / "bootstrap" / "ui" / "terminal.sh").as_posix(),
        "AIF_TEST_PYTHON": Path(sys.executable).as_posix(),
        "AIF_TEST_UPLOADER_EXIT": str(uploader_exit),
        "AIFACTORY_USE_JSON_OVERRIDE": use_json,
        "AIF_COLOR": "never",
    })
    if update is not None:
        environment["AIFACTORY_UPDATE_GITHUB_VARIABLES"] = update
    return subprocess.run(
        [bash_executable, "--noprofile", "--norc", "-c", script],
        input=answer, text=True, capture_output=True, cwd=tmp_path, env=environment,
        timeout=30, check=False,
    )


@pytest.mark.parametrize("answer", ["n\n", "N\n", "no\n", "\n", ""])
def test_json_override_no_skips_bulk_sync_but_keeps_json_transport_and_dispatch(tmp_path, bash_executable, answer):
    result = run_sync_blocks(tmp_path, bash_executable, answer)
    assert result.returncode == 0, result.stderr
    assert "Update GitHub variables and secrets from .env? [y/N]:" in result.stderr
    assert "Please enter" not in result.stderr
    assert "BULK:" not in result.stdout
    assert "Skipped bulk GitHub" in result.stdout
    assert result.stdout.count("GH:secret set AIFACTORY_CONFIG_JSON") == 1
    assert "--repo example/factory --env dev" in result.stdout
    assert "--raw-field config_file=aifactory/variables.json" in result.stdout


@pytest.mark.parametrize("answer", ["y\n", "Y\n", "yes\n", "YES\n"])
def test_json_override_yes_runs_existing_bulk_sync_once(tmp_path, bash_executable, answer):
    result = run_sync_blocks(tmp_path, bash_executable, answer)
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("BULK:10-GH-create-or-update-github-variables.sh") == 1
    assert "GH:secret set AIFACTORY_CONFIG_JSON" in result.stdout
    assert "--raw-field config_file=aifactory/variables.json" in result.stdout


def test_invalid_prompt_answer_reprompts_and_can_decline(tmp_path, bash_executable):
    result = run_sync_blocks(tmp_path, bash_executable, "later\nN\n")
    assert result.returncode == 0, result.stderr
    assert result.stderr.count("Update GitHub variables and secrets from .env? [y/N]:") == 2
    assert "Please enter" in result.stderr
    assert "BULK:" not in result.stdout


@pytest.mark.parametrize("update,expected_bulk", [("y", True), ("n", False)])
def test_explicit_unattended_choice_does_not_prompt(tmp_path, bash_executable, update, expected_bulk):
    result = run_sync_blocks(tmp_path, bash_executable, "", update=update)
    assert result.returncode == 0, result.stderr
    assert ("BULK:" in result.stdout) == expected_bulk
    assert "Update GitHub variables and secrets from .env? [y/N]:" not in result.stderr


def test_non_json_route_preserves_existing_sync_and_empty_override(tmp_path, bash_executable):
    result = run_sync_blocks(tmp_path, bash_executable, "", use_json="n")
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("BULK:10-GH-create-or-update-github-variables.sh") == 1
    assert "AIFACTORY_CONFIG_JSON" not in result.stdout
    assert "--raw-field config_file= --raw-field runner_selection=" in result.stdout
    assert "Update GitHub variables" not in result.stderr


def test_bulk_sync_failure_stops_before_secret_upload_or_dispatch(tmp_path, bash_executable):
    result = run_sync_blocks(tmp_path, bash_executable, "y\n", uploader_exit=7)
    assert result.returncode == 7
    assert "GH:" not in result.stdout


def test_modified_launcher_has_valid_bash_syntax(bash_executable):
    result = subprocess.run(
        [bash_executable, "--noprofile", "--norc", "-n"],
        input=LAUNCHER.read_text(encoding="utf-8"), capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
