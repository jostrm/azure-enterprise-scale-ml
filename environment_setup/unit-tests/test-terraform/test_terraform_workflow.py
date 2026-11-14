"""Contracts of the GitHub Actions template infra-common-terraform.yml and of the CI that runs this suite.

The Terraform workflow mirrors infra-common.yml: same dispatch inputs, jobs, environments, identity (OIDC
azure/login), preflight, persona and report steps; Terraform replaces the three `az deployment sub create`
steps with plan-then-apply under the shared retry helper. It passes Terraform only the configuration file and
what the Bicep job takes from secrets, GitHub variables or its own steps: every root variable is set, and
nothing else (no second parameter list).
"""
from __future__ import annotations

import re

import yaml

from harness import BICEP_WORKFLOW, REPO_ROOT, ROOT_MODULE, TERRAFORM_WORKFLOW

TERRAFORM_VERSION = "1.17.1"


def load(path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def steps(job) -> dict:
    return {step["name"]: step for step in job["steps"]}


def test_dispatch_inputs_permissions_and_jobs_mirror_the_bicep_workflow():
    bicep, terraform = load(BICEP_WORKFLOW), load(TERRAFORM_WORKFLOW)
    assert terraform["on"] == bicep["on"]
    assert terraform["permissions"] == {"contents": "read", "id-token": "write"} == bicep["permissions"]
    assert list(terraform["jobs"]) == list(bicep["jobs"]) == ["common-dev", "common-stage", "common-prod"]
    for name, job in terraform["jobs"].items():
        for key in ("name", "if", "needs", "environment", "runs-on"):
            assert job.get(key) == bicep["jobs"][name].get(key), (name, key)


def test_shared_steps_are_identical_and_only_the_deployment_steps_differ():
    bicep, terraform = load(BICEP_WORKFLOW), load(TERRAFORM_WORKFLOW)
    deployment = {"01_az_bicep_common_rg", "Debug networking inputs (before 02)", "02_az_bicep_private_networking",
                  "03_az_bicep_deploy_resources"}
    terraform_only = {"Load the configuration file (GitHub Environment mode)", "Set up Terraform", "Terraform inputs",
                      "Terraform init (remote state)",
                      "01-03 terraform plan and apply (11-rgCommon, 12-networkCommon, 13-rgLevel)"}
    for name, job in terraform["jobs"].items():
        bicep_steps, terraform_steps = steps(bicep["jobs"][name]), steps(job)
        assert set(bicep_steps) - deployment == set(terraform_steps) - terraform_only, name
        for step_name in set(bicep_steps) - deployment:
            expected = yaml.dump(bicep_steps[step_name]).replace(
                "bicep/copy_to_local_settings/github-actions/infra-common.yml",
                "terraform/copy_to_local_settings/github-actions/infra-common-terraform.yml")
            assert yaml.dump(terraform_steps[step_name]) == expected, (name, step_name)
        for key, value in job["env"].items():
            if key != "TF_ROOT":
                assert bicep["jobs"][name]["env"][key] == value, (name, key)
    assert "az deployment" not in TERRAFORM_WORKFLOW.read_text(encoding="utf-8")


def test_terraform_is_pinned_authenticated_with_oidc_and_planned_before_apply_with_retries():
    workflow = load(TERRAFORM_WORKFLOW)
    for name, job in workflow["jobs"].items():
        named = steps(job)
        setup = named["Set up Terraform"]
        assert re.fullmatch(r"hashicorp/setup-terraform@[0-9a-f]{40}", setup["uses"].split(" ")[0]), name
        assert setup["with"]["terraform_version"] == TERRAFORM_VERSION
        assert re.fullmatch(r"\d+\.\d+\.\d+", setup["with"]["terraform_version"])
        logins = [step for step in job["steps"] if step.get("uses", "").startswith("azure/login@")]
        assert any("client-id" in step.get("with", {}) for step in logins), name
        inputs = named["Terraform inputs"]["run"]
        assert "ARM_USE_OIDC=true" in inputs and "ARM_CLIENT_ID=" in inputs and "ARM_TENANT_ID=" in inputs
        init = named["Terraform init (remote state)"]["run"]
        assert "init -input=false" in init and "use_azuread_auth=true" in init
        assert 'key=aifactory/$common_rg/esml-common.tfstate' in init
        apply = named["01-03 terraform plan and apply (11-rgCommon, 12-networkCommon, 13-rgLevel)"]["run"]
        plan_at, apply_at = apply.index(" plan -input=false"), apply.index(" apply -input=false")
        assert plan_at < apply_at and "-out=tfplan" in apply and "apply -input=false -no-color -lock-timeout=20m tfplan" in apply
        assert "scripts/modules/aif-retry.sh" in apply and "aif_retry " in apply and "--base-delay" in apply
        assert "-- aif_tf_plan_apply" in apply, "the retry re-plans: each attempt plans from refreshed state"
        assert "rm -f" in apply, "the saved plan holds sensitive values and is removed"


def test_the_workflow_sets_every_root_variable_and_nothing_else():
    declared = set(re.findall(r'^variable "(\w+)"', (ROOT_MODULE / "variables.tf").read_text(encoding="utf-8"), re.M))
    text = TERRAFORM_WORKFLOW.read_text(encoding="utf-8")
    for name, job in load(TERRAFORM_WORKFLOW)["jobs"].items():
        run = steps(job)["Terraform inputs"]["run"]
        assert set(re.findall(r"TF_VAR_(\w+)=", run)) == declared, name
    assert "terraform.tfvars" not in text and "-var " not in text and "-var-file" not in text


def test_terraform_folder_readme_documents_the_template():
    readme = (TERRAFORM_WORKFLOW.parent / "readme.md").read_text(encoding="utf-8")
    assert "infra-common-terraform.yml" in readme
    for variable in ("TFSTATE_RESOURCE_GROUP", "TFSTATE_STORAGE_ACCOUNT", "TFSTATE_CONTAINER"):
        assert variable in readme


def test_ci_installs_pinned_terraform_and_bicep_and_runs_this_suite_on_ubuntu_and_windows():
    workflow = load(REPO_ROOT / ".github" / "workflows" / "infrastructure-tests.yml")
    job = workflow["jobs"]["terraform"]
    assert {row["os"] for row in job["strategy"]["matrix"]["include"]} == {"ubuntu-22.04", "windows-2022"}
    named = steps(job)
    setup = next(step for step in job["steps"] if step.get("uses", "").startswith("hashicorp/setup-terraform@"))
    assert re.fullmatch(r"hashicorp/setup-terraform@[0-9a-f]{40}", setup["uses"])
    assert setup["with"]["terraform_version"] == TERRAFORM_VERSION
    assert setup["with"]["terraform_wrapper"] == "false"
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
    assert any("test-terraform/ci/install_bicep.py" in step.get("run", "") for step in named.values())
    assert any("test-terraform/run_ci.py" in step.get("run", "") for step in named.values())
    assert "${{ secrets." not in (REPO_ROOT / ".github" / "workflows" / "infrastructure-tests.yml").read_text(encoding="utf-8")
