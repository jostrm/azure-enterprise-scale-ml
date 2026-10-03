"""Structure tests for the optional health model pipelines (ADO and GitHub Actions)."""
from __future__ import annotations

import re

import pytest

yaml = pytest.importorskip("yaml")

from conftest import HEALTHMODEL, REPO

SETTINGS = REPO / "environment_setup/aifactory/bicep/copy_to_local_settings"
ADO = SETTINGS / "azure-devops/esml-yaml-pipelines/esml-infra-project/infra-project-healthmodel.yaml"
GHA = SETTINGS / "github-actions/infra-project-healthmodel.yml"
TOOL = "azure-enterprise-scale-ml/healthmodel/aif_healthmodel.py"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def ado_parameters():
    return {p["name"]: p for p in load(ADO)["parameters"]}


def gha_inputs(trigger="workflow_dispatch"):
    document = load(GHA)
    return document.get("on", document.get(True))[trigger]["inputs"]


def test_launcher_referenced_by_pipelines_exists():
    assert (HEALTHMODEL / "aif_healthmodel.py").is_file()
    for path in (ADO, GHA):
        assert TOOL in path.read_text(encoding="utf-8")


def test_ado_pipeline_is_manual_plan_by_default_and_uses_existing_variables():
    document = load(ADO)
    assert document["trigger"] == "none" and document["pr"] == "none"
    assert {"template": "../variables/variables.yaml"} in document["variables"]
    params = ado_parameters()
    assert params["mode"]["default"] == "plan" and params["mode"]["values"] == ["plan", "deploy"]
    assert params["scope"]["values"] == ["project", "common", "all"]
    assert params["registerProvider"]["default"] is False and params["prune"]["default"] is False
    assert params["environment"]["values"] == ["dev", "stage", "test", "prod"]


def test_ado_job_runs_through_the_selected_service_connection():
    document = load(ADO)
    job = document["jobs"][0]
    task = next(step for step in job["steps"] if step.get("task") == "AzureCLI@2")
    assert task["inputs"]["azureSubscription"] == "${{ variables.healthModelServiceConnection }}"
    script = task["inputs"]["inlineScript"]
    assert "--register-provider" in script and "--prune" in script
    # Deploy-only switches are only added in deploy mode.
    assert re.search(r"if \(\$env:HM_MODE -eq 'deploy'\)", script)
    checkout = job["steps"][0]
    assert checkout["checkout"] == "self" and checkout["submodules"] == "recursive"
    assert checkout["persistCredentials"] is False


def test_gha_workflow_supports_dispatch_and_call_with_identical_inputs():
    dispatch, call = gha_inputs("workflow_dispatch"), gha_inputs("workflow_call")
    assert set(dispatch) == set(call)
    assert dispatch["mode"]["default"] == "plan" and dispatch["mode"]["options"] == ["plan", "deploy"]
    assert dispatch["scope"]["options"] == ["project", "common", "all"]
    assert dispatch["register_provider"]["default"] is False and dispatch["prune"]["default"] is False
    assert len(dispatch) <= 10, "keep within the classic workflow_dispatch input limit"


def test_gha_job_uses_environment_mapping_and_oidc_login():
    document = load(GHA)
    assert document["permissions"] == {"contents": "read", "id-token": "write"}
    job = document["jobs"]["healthmodel"]
    assert "vars.AIFACTORY_GITHUB_ENVIRONMENTS" in job["environment"]
    login = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("azure/login"))
    assert login["with"] == {"client-id": "${{ secrets.AZURE_CLIENT_ID }}", "tenant-id": "${{ secrets.TENANT_ID }}",
                             "subscription-id": "${{ vars.AZURE_SUBSCRIPTION_ID }}"}
    checkout = job["steps"][0]
    assert checkout["with"]["persist-credentials"] is False


def test_both_pipelines_offer_the_same_choices():
    params = ado_parameters()
    dispatch = gha_inputs()
    assert params["scope"]["values"] == dispatch["scope"]["options"]
    assert params["mode"]["values"] == dispatch["mode"]["options"]
    for ado_name, gha_name in (("projectNumber", "project_number"), ("configFile", "config_file"),
                               ("alertEmails", "alert_emails"), ("registerProvider", "register_provider"),
                               ("prune", "prune")):
        assert ado_name in params and gha_name in dispatch


def test_pipelines_never_echo_configuration_or_tokens():
    for path in (ADO, GHA):
        text = path.read_text(encoding="utf-8")
        assert "Get-Content" not in text and "cat aifactory" not in text
        assert "get-access-token" not in text
