"""Offline contracts for reusing common ACR without redeploying it."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from base.config import env_defaults, yaml_defaults
from domain.pipeline_contracts import ADO_SERVICES, GHA_PHASE, load_pipeline, objects
from unit.test_ado_json_initialization import config


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup/aifactory/bicep"
CORE = BICEP / "esml-genai-1/02-core-infrastructure.bicep"
REGISTER = BICEP / "copy_to_local_settings/github-actions/03a-GH-create-or-update-github-variables.sh"


def core_step(path):
    return next(
        step for step in objects(load_pipeline(path))
        if step.get("name", step.get("displayName")) == "62-core-infrastructure"
    )


def module_block(name):
    text = CORE.read_text(encoding="utf-8")
    match = re.search(
        rf"^module {re.escape(name)} .+?(?=^(?:module|resource|var|param|output) |\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    assert match, name
    return match.group()


def test_shared_registry_and_private_endpoint_have_a_default_true_update_gate():
    text = CORE.read_text(encoding="utf-8")
    assert "param updateCommonACR bool = true" in text
    shared = module_block("acrCommonUpdate")
    assert "= if (useCommonACR && updateCommonACR)" in shared
    assert "'../modules/containerRegistry.bicep'" in shared
    assert "privateEndpointName:" in shared
    assert "tags: tagsProject" in shared


def test_opt_out_does_not_create_replacement_registry_or_disable_project_access():
    for name in ("acr", "miRbacCmnACR", "miPrjRbacCmnACR", "sacc", "kv1"):
        assert "updateCommonACR" not in module_block(name)
    assert "!useCommonACR" in module_block("acr")
    assert "updateCommonACR" not in module_block("privateDnsContainerRegistry")


def test_json_yaml_and_github_defaults_preserve_existing_behavior():
    baseline = json.loads((ROOT / "environment_setup/aifactory/variables.json").read_text(encoding="utf-8"))["dev"]
    assert baseline["updateCommonACR"] == "true"
    assert yaml_defaults()["updateCommonACR"] == "true"
    assert env_defaults()["UPDATE_COMMON_ACR"] == "true"
    assert '  "UPDATE_COMMON_ACR"' in REGISTER.read_text(encoding="utf-8")


def test_ado_and_github_forward_update_choice_as_data():
    ado = core_step(ADO_SERVICES)
    gha = core_step(GHA_PHASE)
    assert ado["env"]["UPDATE_COMMON_ACR"] == "$(updateCommonACR)"
    assert gha["env"]["UPDATE_COMMON_ACR"] == "${{ env.updateCommonACR }}"
    for script in (ado["inputs"]["inlineScript"], gha["run"]):
        assert '--parameters updateCommonACR="$UPDATE_COMMON_ACR"' in script
    assert "updateCommonACR: ${{ vars.UPDATE_COMMON_ACR || 'true' }}" in GHA_PHASE.read_text(encoding="utf-8")


def test_existing_application_insights_forwarding_is_unchanged():
    assert '--parameters enableApplicationInsights="$(enableApplicationInsights)"' in core_step(ADO_SERVICES)["inputs"]["inlineScript"]
    assert '--parameters enableApplicationInsights="${{ env.enableApplicationInsights }}"' in core_step(GHA_PHASE)["run"]


def test_json_and_yaml_refresh_preserve_false(config, tmp_path):
    active = tmp_path / "variables.json"
    active.write_text('{"dev":{"updateCommonACR":"false"}}', encoding="utf-8")
    config.merge_json_template(ROOT / "environment_setup/aifactory/variables.json", active)
    assert json.loads(active.read_text(encoding="utf-8"))["dev"]["updateCommonACR"] == "false"
    active = tmp_path / "variables.yaml"
    active.write_text('variables:\n  updateCommonACR: "false"\n', encoding="utf-8")
    config.merge_yaml_template(ADO_SERVICES.parents[2] / "variables/variables.yaml", active)
    assert '  updateCommonACR: "false"' in active.read_text(encoding="utf-8")


@pytest.mark.parametrize("platform", ["ado", "gha"])
@pytest.mark.parametrize("value", [None, "true", "false"])
def test_runtime_preserves_true_false_and_missing_defaults(platform, value):
    result = run_resolution(platform, value)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ("true" if value is None else value)


@pytest.mark.parametrize("value", ["true", "false"])
def test_ado_expansion_cannot_reenable_an_explicit_opt_out(value):
    result = run_resolution("ado", value, expand=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == value


def test_ado_unresolved_legacy_macro_keeps_previous_default():
    result = run_resolution("ado", "$(updateCommonACR)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "true"


@pytest.mark.parametrize("platform", ["ado", "gha"])
@pytest.mark.parametrize("value", ["", "FALSE", "0", "$(printf UNSAFE)"])
def test_invalid_values_fail_before_azure_without_evaluation(platform, value):
    result = run_resolution(platform, value)
    assert result.returncode != 0
    assert "must be true or false" in result.stdout + result.stderr
    assert "UNSAFE" not in result.stdout + result.stderr


def run_resolution(platform, value, expand=False):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Git Bash required")
    step = core_step(ADO_SERVICES if platform == "ado" else GHA_PHASE)
    script = step["inputs"]["inlineScript"] if platform == "ado" else step["run"]
    marker = "# Generate admin password first" if platform == "ado" else "ADMIN_PASSWORD="
    script = script.split(marker, 1)[0]
    assert "UPDATE_COMMON_ACR" in script
    environ = dict(os.environ)
    environ.pop("UPDATE_COMMON_ACR", None)
    if value is not None:
        environ["UPDATE_COMMON_ACR"] = value
        if expand:
            script = script.replace("$(updateCommonACR)", value)
    return subprocess.run(
        [bash, "-c", script + '\nprintf "%s\\n" "$UPDATE_COMMON_ACR"\n'],
        env=environ, capture_output=True, text=True, timeout=15,
    )
