"""Regression contracts for completing AKS after a partial AML deployment."""

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
BICEP = ROOT / "environment_setup" / "aifactory" / "bicep"


def module_block(text, name):
    start = text.index(f"module {name} ")
    end = text.find("\nmodule ", start + 1)
    return text[start:end if end >= 0 else len(text)]


def test_aks_completion_does_not_require_recreating_workspace():
    source = (BICEP / "esml-genai-1" / "07-ml-data-platform.bicep").read_text()
    block = module_block(source, "amlv2Aks")
    declaration = block.splitlines()[0]
    assert "if(enableAzureMachineLearning && enableAksForAzureML)" in declaration
    assert "!amlExists" not in declaration
    assert "...(!amlExists && enableAzureMachineLearning ? [amlv2] : [])" in block
    assert "aksExists: aksExists" in block
    assert "if(!amlExists && enableAzureMachineLearning)" in module_block(source, "amlv2").splitlines()[0]


def test_only_verified_existing_attachment_skips_compute_write():
    platform = (BICEP / "esml-genai-1" / "07-ml-data-platform.bicep").read_text()
    source = (BICEP / "modules" / "machineLearningAks.bicep").read_text()
    compute = source[source.index("resource machineLearningCompute "):]
    for text in (platform, source):
        assert "param aksComputeExists bool = false" in text
    assert "aksComputeExists: aksComputeExists" in module_block(platform, "amlv2Aks")
    assert "!aksComputeExists" in compute.splitlines()[0]
    assert "!aksExists" not in compute.splitlines()[0]
    assert "env == 'dev' && !aksExists" in source
    assert "(env == 'test' || env == 'prod') && !aksExists" in source


def test_new_attachment_to_existing_cluster_keeps_networking_without_resizing():
    source = (BICEP / "modules" / "machineLearningAks.bicep").read_text()
    compute = source[source.index("resource machineLearningCompute "):]
    assert "}, !aksExists ? {" in compute
    assert "agentCount: env == 'dev' ? aksNodes_dev : aksNodes_testProd" in compute
    assert "agentVmSize: env == 'dev' ? aksVmSku_dev : aksVmSku_testProd" in compute
    assert "resourceId: aksResourceId" in compute
    assert "aksNetworkingConfiguration:" in compute and "loadBalancerSubnet: aksSubnetName" in compute


def test_new_attachment_description_uses_configured_skus():
    platform = (BICEP / "esml-genai-1" / "07-ml-data-platform.bicep").read_text()
    block = module_block(platform, "amlv2Aks")
    assert "aksVmSku_dev: aks_dev_sku_param" in block
    assert "aksVmSku_testProd: aks_test_prod_sku_param" in block
    assert "aksNodes_dev: aks_dev_nodes_param" in block
    assert "aksNodes_testProd: aks_test_prod_nodes_param" in block
    source = (BICEP / "modules" / "machineLearningAks.bicep").read_text()
    compute = source[source.index("resource machineLearningCompute "):]
    assert "description: 'Serve model ONLINE inference on AKS powered webservice. Defaults: Dev=${aksVmSku_dev}. TestProd=${aksVmSku_testProd}'" in compute


def test_pipeline_discovers_exact_attachment_immediately_before_ml_deployment():
    ado = yaml.safe_load((BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/esml-infra-project/jobs/job-2-genai-services.yaml").read_text(encoding="utf-8-sig"))
    github = yaml.safe_load((BICEP / "copy_to_local_settings/github-actions/infra-project-phase.yml").read_text(encoding="utf-8-sig"))
    ado_task = next(step for step in ado["steps"] if step.get("displayName") == "67-data_ml_platform")
    gh_task = next(step for job in github["jobs"].values() for step in job.get("steps", []) if step.get("name") == "67-data_ml_platform")
    for script in (ado_task["inputs"]["inlineScript"], gh_task["run"]):
        discovery = script.index("scripts/discover-aml-aks-attachment.py")
        deployment = script.index("az deployment sub create")
        assert discovery < deployment
        assert 'aksComputeExists="$_aksComputeExists"' in script[deployment:]
        assert '_aksComputeExists=false' in script[:discovery]
        assert 'enableAzureMachineLearning' in script[:discovery]
        assert 'enableAksForAzureML' in script[:discovery]
        assert "|| exit 1" in script[discovery:deployment]
        assert "--common-resource-group" in script[discovery:deployment]
        assert "--add-workspace" in script[discovery:deployment]
        assert "az ml" not in script[:deployment]


def test_approved_aks_defaults_match_all_variable_templates():
    expected = {
        "admin_aks_gpu_sku_dev_override": "Standard_D4s_v5",
        "admin_aks_nodes_dev_override": 2,
        "admin_aks_version_override": "1.35.7",
    }
    config = json.loads((BICEP.parent / "variables.json").read_text(encoding="utf-8-sig"))
    ado = yaml.safe_load((BICEP / "copy_to_local_settings/azure-devops/esml-yaml-pipelines/variables/variables.yaml").read_text(encoding="utf-8-sig"))
    for name, value in expected.items():
        assert config["dev"][name] == value
        assert ado["variables"][name] == value
    github = BICEP / "copy_to_local_settings/github-actions"
    environment = (github / ".env.template").read_text(encoding="utf-8-sig")
    workflow = (github / "infra-project-phase.yml").read_text(encoding="utf-8-sig")
    for name, value in expected.items():
        assert f'{name.upper()}="{value}"' in environment
        assert f"{name}: ${{{{ vars.{name.upper()} || '{value}' }}}}" in workflow
