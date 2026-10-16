"""Offline contracts for optional shared-registry updates and project telemetry."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from base.config import env_defaults, yaml_defaults
from unit.test_ado_json_initialization import config
from unit.test_resolved_identity_bicep import compact, module_block, source


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
CORE = BICEP / "esml-genai-1/02-core-infrastructure.bicep"
ADO = BICEP / (
    "copy_to_local_settings/azure-devops/esml-yaml-pipelines/"
    "esml-infra-project/jobs/job-2-genai-services.yaml"
)
GHA = BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml"
REGISTER = BICEP / (
    "copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh"
)


def ado_core():
    document = yaml.safe_load(ADO.read_text(encoding="utf-8"))
    return next(step for step in document["steps"] if step.get("displayName") == "62-core-infrastructure")


def test_common_registry_opt_out_does_not_create_a_project_registry():
    text = source(CORE)
    assert "param updateCommonACR bool = true" in text
    assert "=if(useCommonACR&&updateCommonACR){" in compact(module_block(text, "acrCommonUpdate"))
    assert "=if(!acrProjectExists&&!useCommonACR){" in compact(module_block(text, "acr"))
    assert "updateCommonACR" not in module_block(text, "acr")
    assert "updateCommonACR" not in module_block(text, "privateDnsContainerRegistry")


def test_common_registry_opt_out_preserves_access_and_project_foundation():
    text = source(CORE)
    for name in ("miRbacCmnACR", "miPrjRbacCmnACR", "sacc", "kv1"):
        assert "updateCommonACR" not in module_block(text, name)
    assert "resource acrCommon " in text
    assert "=if(enableApplicationInsights){" in compact(module_block(text, "applicationInsights"))
    shared_update = module_block(text, "acrCommonUpdate")
    assert "privateEndpointName:" in shared_update
    assert "tags: tagsProject" in shared_update


@pytest.mark.parametrize("key,env_key", [
    ("updateCommonACR", "UPDATE_COMMON_ACR"),
    ("enableApplicationInsights", "ENABLE_APPLICATION_INSIGHTS"),
])
def test_configuration_defaults_keep_existing_behavior(key, env_key):
    values = json.loads((ROOT / "environment_setup/aifactory/variables.json").read_text())["dev"]
    assert values[key] == "true"
    assert yaml_defaults()[key] == "true"
    assert env_defaults()[env_key] == "true"
    assert f'  "{env_key}"' in REGISTER.read_text(encoding="utf-8")


def test_ado_forwards_both_options_as_environment_data():
    step = ado_core()
    assert step["env"]["UPDATE_COMMON_ACR"] == "$(updateCommonACR)"
    assert step["env"]["ENABLE_APPLICATION_INSIGHTS"] == "$(enableApplicationInsights)"
    script = step["inputs"]["inlineScript"]
    assert '--parameters updateCommonACR="$UPDATE_COMMON_ACR"' in script
    assert '--parameters enableApplicationInsights="$ENABLE_APPLICATION_INSIGHTS"' in script
    assert '--parameters useCommonACR="$(useCommonACR_override)"' in script
    assert '--parameters updateCommonACR="$(updateCommonACR)"' not in script
    assert '--parameters enableApplicationInsights="$(enableApplicationInsights)"' not in script


def test_github_forwards_shared_registry_option_with_compatible_default():
    text = GHA.read_text(encoding="utf-8")
    assert "updateCommonACR: ${{ vars.UPDATE_COMMON_ACR || 'true' }}" in text
    core = text.split("- name: 62-core-infrastructure", 1)[1].split("- name: 63a-search-mode", 1)[0]
    assert '--parameters updateCommonACR="$UPDATE_COMMON_ACR"' in core
    assert "UPDATE_COMMON_ACR: ${{ env.updateCommonACR }}" in core
    assert '--parameters enableApplicationInsights="${{ env.enableApplicationInsights }}"' in core


def test_json_and_yaml_refresh_preserve_explicit_opt_outs(config, tmp_path):
    values = {"updateCommonACR": "false", "enableApplicationInsights": "false"}
    active_json = tmp_path / "variables.json"
    active_json.write_text(json.dumps({"dev": values}), encoding="utf-8")
    config.merge_json_template(ROOT / "environment_setup/aifactory/variables.json", active_json)
    merged = json.loads(active_json.read_text())["dev"]
    assert all(merged[key] == value for key, value in values.items())
    active_yaml = tmp_path / "variables.yaml"
    active_yaml.write_text(
        "variables:\n" + "".join(f'  {key}: "{value}"\n' for key, value in values.items()),
        encoding="utf-8",
    )
    config.merge_yaml_template(ADO.parents[2] / "variables/variables.yaml", active_yaml)
    merged = yaml.safe_load(active_yaml.read_text())["variables"]
    assert all(merged[key] == value for key, value in values.items())


@pytest.mark.parametrize("value", [None, "true", "false", "", "FALSE", "$(printf UNSAFE)"])
def test_github_validates_shared_registry_option_without_evaluating_input(value):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Git Bash required")
    document = yaml.safe_load(GHA.read_text(encoding="utf-8"))
    step = next(
        step for job in document["jobs"].values() for step in job["steps"]
        if step.get("name") == "62-core-infrastructure"
    )
    script = step["run"].split("ADMIN_PASSWORD=", 1)[0]
    environ = dict(os.environ)
    environ.pop("UPDATE_COMMON_ACR", None)
    if value is not None:
        environ["UPDATE_COMMON_ACR"] = value
    result = subprocess.run(
        [bash, "-c", script + '\nprintf "%s\\n" "$UPDATE_COMMON_ACR"\n'],
        env=environ, capture_output=True, text=True, timeout=15,
    )
    if value in (None, "true", "false"):
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ("true" if value is None else value)
    else:
        assert result.returncode != 0
        assert "must be true or false" in result.stderr
        assert "UNSAFE" not in result.stdout + result.stderr


@pytest.mark.parametrize("value,expected", [
    (None, "true true"),
    ("true", "true true"),
    ("false", "false false"),
    ("macro", "true true"),
])
def test_ado_option_resolution_preserves_false_and_legacy_missing_values(value, expected):
    result = run_ado_option_resolution(value)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("registry,insights", [("false", "false"), ("false", "true"), ("true", "false")])
def test_ado_macro_expansion_cannot_turn_explicit_false_back_on(registry, insights):
    result = run_ado_option_resolution(registry, expand_macros=True, insights_value=insights)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{registry} {insights}"


@pytest.mark.parametrize("value", ["", "FALSE", "0", "typo", "$(printf UNSAFE)", "${UNSET}"])
def test_invalid_ado_options_fail_without_evaluating_input(value):
    result = run_ado_option_resolution(value)
    assert result.returncode != 0
    assert "must be true or false" in result.stdout + result.stderr
    assert "UNSAFE" not in result.stdout + result.stderr


def run_ado_option_resolution(value, *, expand_macros=False, insights_value=None):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Git Bash required")
    script = ado_core()["inputs"]["inlineScript"].split("# Generate admin password first", 1)[0]
    assert "UPDATE_COMMON_ACR" in script and "ENABLE_APPLICATION_INSIGHTS" in script
    environ = dict(os.environ)
    for key, macro in (
        ("UPDATE_COMMON_ACR", "$(updateCommonACR)"),
        ("ENABLE_APPLICATION_INSIGHTS", "$(enableApplicationInsights)"),
    ):
        option_value = insights_value if key == "ENABLE_APPLICATION_INSIGHTS" and insights_value is not None else value
        environ.pop(key, None)
        if option_value is not None:
            environ[key] = macro if option_value == "macro" else option_value
            if expand_macros:
                script = script.replace(macro, environ[key])
    return subprocess.run(
        [bash, "-c", script + '\nprintf "%s %s\\n" "$UPDATE_COMMON_ACR" "$ENABLE_APPLICATION_INSIGHTS"\n'],
        env=environ, capture_output=True, text=True, timeout=15,
    )
