"""Offline contracts for JSON-first pipeline identity routing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

from domain.pipeline_contracts import load_pipeline


ROOT = Path(__file__).resolve().parents[4]
TEMPLATES = ROOT / "environment_setup/aifactory/bicep/copy_to_local_settings"
GHA_COMMON = TEMPLATES / "github-actions/infra-common.yml"
GHA_PROJECT = TEMPLATES / "github-actions/infra-project.yml"
GHA_PHASE = TEMPLATES / "github-actions/infra-project-phase.yml"
ADO_COMMON = TEMPLATES / "azure-devops/esml-yaml-pipelines/esml-infra-common/infra-aifactory-common.yaml"
ADO_COMMON_JOB = TEMPLATES / "azure-devops/esml-yaml-pipelines/esml-infra-common/jobs/job-1-aif-cmn.yaml"
SCRIPT = ROOT / "environment_setup/aifactory/bicep/scripts/apply-json-config-overrides.py"


def load_override_module():
    spec = importlib.util.spec_from_file_location("json_identity_overrides", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_json_oidc_identity_uses_exact_environment_subscription(tmp_path, monkeypatch):
    module = load_override_module()
    document = {
        "dev": {
            "AZURE_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
            "tenantId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "dev_sub_id": "22222222-2222-2222-2222-222222222222",
            "test_sub_id": "33333333-3333-3333-3333-333333333333",
            "prod_sub_id": "44444444-4444-4444-4444-444444444444",
        },
        "stage_prod": {
            "tenantId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "test_sub_id": "77777777-7777-7777-7777-777777777777",
            "prod_sub_id": "88888888-8888-8888-8888-888888888888",
        },
    }
    values, section = module.selected_values(document, "prod")
    assert section == "stage_prod"
    github_env, github_output = tmp_path / "env", tmp_path / "output"
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    module.apply(values, "github", None)
    module.github_identity(values, "prod")
    outputs = dict(line.split("=", 1) for line in github_output.read_text().splitlines())
    assert outputs == {
        "azure_client_id": document["dev"]["AZURE_CLIENT_ID"],
        "azure_tenant_id": document["stage_prod"]["tenantId"],
        "azure_subscription_id": document["stage_prod"]["prod_sub_id"],
    }


def test_github_json_identity_mode_avoids_environment_identity_values():
    common = load_pipeline(GHA_COMMON)
    assert common["on"]["workflow_dispatch"]["inputs"]["use_json_config_override"]["default"] == "false"
    for job in common["jobs"].values():
        steps = job["steps"]
        resolver = next(step for step in steps if step.get("id") == "json_identity")
        oidc = next(step for step in steps if step.get("name") == "Azure login with OpenID Connect (OIDC)"
                    and step["if"] == "${{ inputs.use_json_config_override }}")
        assert "--github-identity-output" in resolver["run"]
        assert oidc["with"] == {
            "client-id": "${{ steps.json_identity.outputs.azure_client_id }}",
            "tenant-id": "${{ steps.json_identity.outputs.azure_tenant_id }}",
            "subscription-id": "${{ steps.json_identity.outputs.azure_subscription_id }}",
        }

    project = load_pipeline(GHA_PROJECT)
    assert project["on"]["workflow_dispatch"]["inputs"]["json_identity_auth"]["default"] == "false"
    configure = project["jobs"]["configure"]
    assert configure["env"]["AIFACTORY_CONFIG_JSON"] == (
        "${{ !inputs.json_identity_auth && secrets[inputs.config_secret] || '' }}"
    )
    for key in ("azure_client_id", "azure_tenant_id", "azure_subscription_id"):
        assert configure["outputs"][key] == "${{ steps.json_identity.outputs." + key + " }}"

    phase = load_pipeline(GHA_PHASE)
    inputs = phase["on"]["workflow_call"]["inputs"]
    assert inputs["json_identity_auth"]["type"] == "boolean"
    steps = phase["jobs"]["deploy-project"]["steps"]
    oidc = next(step for step in steps if step.get("name") == "Azure login with OpenID Connect (OIDC)"
                and step["if"] == "${{ inputs.json_identity_auth }}")
    assert oidc["with"]["subscription-id"] == "${{ inputs.azure_subscription_id }}"


def test_azure_devops_common_pipeline_applies_json_before_azure_cli_tasks():
    pipeline = yaml.safe_load(ADO_COMMON.read_text(encoding="utf-8"))
    inputs = pipeline["parameters"]
    assert {entry["name"] for entry in inputs} >= {"configFile", "useJsonConfigOverride"}
    source = ADO_COMMON.read_text(encoding="utf-8")
    assert source.count(
        "${{ if eq(parameters.useJsonConfigOverride, true) }}:\n"
        "      configOverrideFile: ${{ parameters.configFile }}"
    ) == 3
    job = yaml.safe_load(ADO_COMMON_JOB.read_text(encoding="utf-8"))
    override = job["steps"][1]
    assert override["task"] == "PythonScript@0"
    assert "apply-json-config-overrides.py" in override["inputs"]["scriptPath"]
    assert "--format azure-devops" in override["inputs"]["arguments"]
